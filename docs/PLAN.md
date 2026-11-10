# Проверка трудовых договоров по ТК РФ — план (v2, работа в два агента)

## Контекст

- **ТЗ** (`ТЗ_ИИ-агент_v5.1.docx`) — конвейер проверки документа, а не чат: загрузка DOCX/PDF → фоновая задача → структурированный отчёт (цитата из договора + цитата нормы, категория «Критическая / Рекомендательная / Информационная», рекомендация, подсветка) → история, выгрузка PDF/DOCX; 4 роли с изоляцией организаций; база знаний с редакциями и откатом; обезличивание до вызова LLM; журналы; mock-режим LLM. Приёмка: retrieval@3 ≥ 85 % (Ф-04), точность/полнота ≥ 0,85 / 0,80, 0 % замечаний без цитаты, 0 ПДн во внешней модели.
- **«Архитектура системы и БД»** (консультация, не догма) — модульный монолит api + worker, Postgres 16 + pgvector, Redis + ARQ, findings построчно, нормативка в БД с неизменяемыми версиями, гибридный поиск + реранкер, промпты в БД, тип `AnonymizedText`, таблицы `retrievals`/`llm_calls`/evals, DDL на 26 таблиц, план из 10 шагов. Берём как основу, но **упрощаем под локальный учебный деплой** (см. «Отступления»).
- **`contract-checker`** — рабочий MVP примерно на 3,5 тыс. строк; ядро переносим (парсер, чанкер, правила, `result_validation.py`, GigaChat-клиент с сертификатом НУЦ, mock, оценка, 40 размеченных договоров). Нормативка сейчас — **14 фрагментов по 6 статьям**.
- **`MosPoly_ai_agent`** — пустой целевой репозиторий.
- **Решения:** свой сервис FastAPI + React, без OpenWebUI. LLM и эмбеддер — GigaChat **на разных ключах**. Локальный деплой через `docker compose`. Работают два агента параллельно.

## Векторный поиск и реранкер — как устроено

### Индексация нормативки (воркер, один раз на версию)
1. Эксперт загружает версию источника (JSON-формат из MVP, позже — DOCX/HTML ТК с автоматической нарезкой) → `regulation_versions(status=draft)`.
2. Нарезка: **статья → часть** (одна часть ≈ 1 фрагмент, длинные части делятся по пунктам), в `regulation_chunks` пишутся `article`, `part`, `text`.
3. Текст для эмбеддинга получает контекстный заголовок: `"ТК РФ, ст. 91 «Понятие рабочего времени…», ч. 2: <текст>"` — это заметно поднимает качество поиска по коротким частям.
4. Эмбеддинги — **GigaChat Embeddings** (отдельный ключ), батчами, с повтором при 429. Результат сохраняется в `regulation_chunks.embedding`. Колонка `vector` **без фиксированной размерности** (у моделей `Embeddings` и `EmbeddingsGigaR` размерности разные), модель записывается в `regulation_versions.embedding_model`. При смене модели — команда `reindex`.
5. Кеш эмбеддингов `embedding_cache(model, sha256(text)) → vector`: повторные прогоны оценки на 40 договорах не тратят квоту.
6. Активация версии — одна транзакция (`draft → active`, прежняя → `archived`), пересчёт не нужен; откат = активация архивной версии.
7. Индекс: при объёме ≤ 10⁴ фрагментов точный перебор в pgvector занимает миллисекунды. HNSW добавляем, только если база разрастётся (для него нужна фиксированная размерность → отдельная миграция).

### Поиск по пункту договора (`knowledge/retrieval.py`)
Запрос — **уже обезличенный** текст пункта (плюс заголовок раздела). Три независимых канала, все ограничены активными версиями источников профиля и датой действия редакции:
1. **Dense:** `embedding <=> :q` (косинусное расстояние), top-20.
2. **Lexical:** `tsvector('russian')`, top-20. Важно: `websearch_to_tsquery` по длинному пункту соединяет слова через AND и почти никогда ничего не находит. Поэтому строим OR-запрос из лемм (`to_tsquery` с `|`, стоп-слова отфильтрованы) и ранжируем `ts_rank_cd`.
3. **Article hints:** явные ссылки «ст. 91» в тексте + словарь тем → статей (отпуск → 115, испытание → 70, …; хранится в профиле проверки). Найденные статьи добавляются в выдачу через `find_by_article`.

Слияние — **RRF** (k = 60) в одном SQL-запросе (по образцу из п. 5.5 документа архитектуры) → кандидаты top-N (по умолчанию 12) → **реранкер** → top-k (по умолчанию 4) с порогом `similarity_floor` уходят в LLM. Все ранги и скоры (`vector_score`, `lexical_score`, `fused_score`, `rerank_score`, `was_sent_to_llm`) пишутся в `retrievals`: так видно, где ошибся поиск, а где модель.

### Реранкер — порт с тремя адаптерами (`RERANKER = none | gigachat | http`)
- `none` — отдаём top-k по RRF. **Это значение по умолчанию**, пока база маленькая: при 14 фрагментах реранкер ничего не даст.
- `gigachat` — **listwise LLM-rerank**: один вызов на пункт, модели передаются пункт и 12 кандидатов (id + первые ~400 символов), она возвращает JSON `[{id, relevance 0–3}]`, `json_schema` строгий. Используем дешёвую модель (`GIGACHAT_RERANK_MODEL`, по умолчанию GigaChat-2) на ключе LLM. Цена — плюс один вызов на пункт, поэтому стоит кеш по `(хеш пункта, версия БЗ)` и общий ограничитель скорости.
- `http` — любой сервис с API `/rerank` в формате Jina/TEI/Cohere: `{query, documents} → [{index, score}]`. Подключается только адресом в `.env`; локально его не поднимаем, но вариант открыт (например, TEI с `bge-reranker-v2-m3` на машине с GPU).

Какой адаптер включать, решаем **по метрикам**: команда `evaluate-retrieval` считает recall@3/@5 и MRR по разметке `evals/demo_cases.json` (у каждого ожидаемого замечания уже есть пара `chunk_id → article`) для конфигураций dense / lexical / hybrid / hybrid+rerank. Порог Ф-04 — 85 % в top-3.

**Главный рычаг качества — не реранкер, а расширение базы знаний:** согласованный перечень статей (вопрос В-3), нарезка по частям, разъяснения Роструда. Это задача RAG-инженера и эксперта; инструмент импорта даём мы.

## Отступления от документа архитектуры (локальный учебный деплой)
- Роли — по ТЗ (Ф-15): `user`, `org_admin`, `kb_expert`, `service_admin` (в документе `admin/lawyer/viewer/regulator`).
- Не делаем сейчас: `api_keys`, SSE (оставляем polling), `/analytics`, `/metrics`, кеш по sha256, OCR (оставляем точку расширения).
- `rules` / `profile_rules` — пороги правил хранятся в `check_profiles.params JSONB`, сами правила остаются кодом из `rules.py`.
- Промпты в БД (`prompt_versions`) оставляем: начальные версии заливаются из `backend/app/llm/prompts/*.yaml`.
- Оригинал файла хранится во временном каталоге воркера и удаляется в `finally`; S3 не нужен.

## Целевая структура репозитория
```
MosPoly_ai_agent/
├─ docker-compose.yml, docker-compose.dev.yml, .env.example, Makefile, scripts/*.ps1
├─ certs/russian_trusted_root_ca_pem.crt
├─ backend/  (Dockerfile; pyproject; alembic/; app/; tests/)
│   app/core          config, db, logging, errors, security deps (get_current_user)
│   app/domain        чистая логика без IO: models, rules, chunker, anonymizer, validation, categories
│   app/documents     парсер DOCX/PDF с координатами, валидация файла
│   app/knowledge     модели БЗ, импорт, индексация, retrieval, reranker
│   app/llm           gigachat/auth.py (общий токен-менеджер), llm_client, embedder, mock, rate limiter, prompts
│   app/analysis      оркестратор пайплайна, ARQ-задачи, сторож зависших задач
│   app/auth          пользователи, организации, роли, JWT
│   app/reports       PDF/DOCX
│   app/audit         audit_log
│   app/api/v1        роутеры + schemas.py (контракт фронта)
│   app/cli.py        seed, import-kb, reindex, check-gigachat, evaluate, evaluate-retrieval
├─ frontend/ (Dockerfile → nginx; Vite + React + TS)
├─ data/ (regulations, contracts — из MVP), evals/
└─ docs/ CONTRACTS.md, ARCHITECTURE.md
```

## Разделение работ на два агента

**Принцип:** первым делом агент A делает **Шаг 0 — фундамент и контракты** (≈ один заход) и пушит его в `main`. После этого агенты работают параллельно в своих зонах. Зоны не пересекаются по файлам; общие файлы (`schemas.py`, миграции) меняются только по правилам ниже.

### Шаг 0 — фундамент (агент A, блокирует B)
- Монорепозиторий, `docker-compose.yml`: db `pgvector/pgvector:pg16`, redis, api, worker, web; healthchecks; `.env.example`; Makefile и `.ps1`-скрипты.
- `core/config.py` (pydantic-settings со всеми ключами, включая `GIGACHAT_LLM_*` и `GIGACHAT_EMBED_*`), `core/db.py` (SQLAlchemy 2 async + asyncpg), alembic.
- **Начальная миграция со всеми таблицами** (на основе DDL из документа архитектуры с отступлениями выше): orgs, users, document_types, check_profiles, regulation_*, prompt_versions, documents, analyses, analysis_chunks, findings, finding_citations, retrievals, llm_calls, embedding_cache, audit_log, eval_*. Так у B не будет конфликтов миграций на старте.
- `api/v1/schemas.py` — **все** Pydantic-DTO для фронта (Auth, User, Org, DocumentType, AnalysisCreate/Status/Result, Finding с `category`, `highlight: {block_id, start, end, page}`, `RegulationSource/Version`, `Error`). Роутеры-заглушки: отдают фикстуры, чтобы фронт мог работать до готовности бэкенда.
- `core/security.py`: `get_current_user` и `require_role(...)` — сигнатуры фиксированы; реализация-заглушка `AUTH_DEV_USER` (B заменит её на JWT).
- Перенос ядра MVP в `domain/`, `documents/`, `llm/` + перенос тестов, `pytest` зелёный.
- `docs/CONTRACTS.md`: эндпоинты, DTO, коды ошибок, статусы анализа, владение файлами, правила работы с миграциями и ветками.

### Агент A (я) — «конвейер и RAG»
1. Шаг 0 (выше).
2. **LLM / эмбеддер:** `gigachat/auth.py` (два экземпляра токен-менеджера с разными ключами), `GigaChatEmbedder` с батчами и кешем, LLM-клиент с `json_schema` и повтором, общий rate limiter (Redis token bucket), журнал `llm_calls`, промпты из БД.
3. **База знаний:** импорт версий, нарезка по частям, индексация в воркере, активация/архив/откат — сервисный слой и API `regulations` (UI админки делает B).
4. **Поиск:** dense + lexical + article hints + RRF в SQL, порт реранкера с тремя адаптерами, запись в `retrievals`, `evaluate-retrieval`.
5. **Пайплайн:** `AnonymizedText` + Natasha для ФИО и адресов, тест «0 ПДн в исходящих запросах», парсер/чанкер с координатами для подсветки, правила, параллельные вызовы LLM (семафор 5), проверка цитат, перевод статусов в 3 категории + рекомендация, findings построчно, частичный результат при падении LLM.
6. **ARQ-воркер:** задачи `analyze`, `index_regulation_version`, heartbeat + сторож, удаление файла, статусы `queued/extracting/analyzing/completed/failed`.
7. **API анализа:** `POST /analyses`, `GET /analyses/{id}`, `/findings`, `GET /analyses` (история) — с фильтрацией по `org_id`/`owner_id` через `get_current_user`.
8. **Оценка:** `evaluate` (rules-only / full) с записью в `eval_runs`, перенос `demo_cases.json`.

### Агент B (коллега) — «пользователь, отчёты, фронт»
1. **Auth:** argon2 + JWT (access/refresh), `POST /auth/token`, `/auth/me`, организации, пользователи, CRUD для `org_admin`/`service_admin`, реальная реализация `get_current_user`/`require_role`, матрица прав (НФ-09), seed админа из `.env`, тесты изоляции.
2. **Audit:** `audit/service.py` — `log_event(actor, action, entity, payload)` без ПДн. A вызывает его из своих сервисов (сигнатура фиксирована в Шаге 0).
3. **Отчёты:** `reports/` — `GET /analyses/{id}/report?format=pdf|docx`: критические замечания первыми, цитаты, источник с редакцией, предупреждение Ф-18. PDF через WeasyPrint (системные библиотеки ставятся в Dockerfile), DOCX через python-docx. Работает поверх DTO `AnalysisResult`, поэтому может стартовать на фикстурах.
4. **Frontend** (React + Vite + TS, TanStack Query, Mantine, React Router, клиент генерируется из OpenAPI через `openapi-typescript`): вход; новая проверка (тип + drag-and-drop, ошибки на русском); статус с прогрессом (polling); отчёт (текст договора с подсветкой по `highlight`, карточки по категориям, фильтры, скачивание PDF/DOCX, плашка Ф-18); история; админка БЗ для `kb_expert` (список версий, загрузка, активация, откат — API от A); пользователи организации для `org_admin`.
5. **Web-контейнер:** многоэтапный Dockerfile → nginx, проксирование `/api` на api; dev-режим с Vite HMR в `docker-compose.dev.yml`.
6. **README для участников:** запуск на Windows (Docker Desktop) и Linux, получение ключей GigaChat (два ключа), частые ошибки; CI (GitHub Actions: ruff, pytest, сборка фронта).

### Правила совместной работы
- Ветки `a/*` и `b/*`, PR в `main`, маленькие PR. Владение каталогами: A — `domain, documents, knowledge, llm, analysis, cli, api/v1/{analyses,regulations}`; B — `auth, audit, reports, frontend, api/v1/{auth,users,orgs,reports}`, README, CI.
- `api/v1/schemas.py` и `docs/CONTRACTS.md` — общие: изменения только аддитивные, отдельным маленьким PR, с упоминанием в описании.
- Миграции: каждая новая ревизия создаётся от актуального `main` (`alembic revision` после `git pull`); при двух головах — `alembic merge`. В Шаге 0 все таблицы уже есть, поэтому новых миграций будет мало.
- Тесты бэкенда — на `EMBEDDING_PROVIDER=hashing`, `LLM_PROVIDER=mock` и тестовом Postgres из compose; сеть не нужна.

## Проверка
- `docker compose up -d --build` на чистой Windows-машине → http://localhost:8080 → вход сид-админом → загрузка `problematic_01_multiple_violations.docx` в mock-режиме → статус → отчёт с подсветкой → PDF/DOCX → запись в истории; пользователь другой организации этот анализ не видит.
- `make test` (= `docker compose run --rm api pytest`): перенесённые тесты MVP + изоляция, обезличивание (0 ПДн в перехваченных запросах), валидация файлов, повтор и частичный результат при сбое LLM, CHECK на цитаты.
- С ключами: `cli check-gigachat` (проверяет оба ключа) → `cli import-kb data/regulations` → `cli evaluate-retrieval` (таблица dense / lexical / hybrid / +rerank, recall@3 ≥ 0,85) → `cli evaluate --full` (точность и полнота по 40 договорам, запись в `eval_runs`).

# Контракты и правила совместной работы

Документ для двух параллельно работающих команд (агентов):

- **A — «конвейер и RAG»**: обработка документа, обезличивание, база знаний, поиск, реранкер, LLM, воркер, API проверок и нормативки, оценка качества.
- **B — «пользователь, отчёты, фронт»**: авторизация и роли, пользователи и организации, аудит, выгрузка PDF/DOCX, React-интерфейс, web-контейнер, README и CI.

Цель документа: B может строить UI и отчёты, не дожидаясь A, и наоборот. Источник истины для форматов — `backend/app/api/v1/schemas.py` и `http://localhost:8000/docs`.

## 1. Владение кодом

| Путь | Владелец | Примечание |
|---|---|---|
| `backend/app/domain/` | A | чистая логика без IO |
| `backend/app/documents/` | A | парсер, загрузка, координаты блоков |
| `backend/app/knowledge/` | A | нормативка, индексация, поиск, реранкер |
| `backend/app/llm/` | A | GigaChat (LLM и эмбеддинги), mock, промпты, rate limiter |
| `backend/app/analysis/` | A | оркестратор, ARQ-воркер |
| `backend/app/evals/`, `backend/app/cli.py` | A | B может добавлять свои команды в cli (например `create-user`) |
| `backend/app/api/v1/{documents,document_types,analyses,regulations}.py` | A | |
| `backend/app/auth/` | B | JWT, пароли, пользователи, организации |
| `backend/app/audit/` | B | |
| `backend/app/reports/` | B | PDF/DOCX |
| `backend/app/api/v1/{auth,reports}.py` | B | |
| `frontend/` | B | |
| `README.md`, `.github/` | B | A дополняет разделы про LLM/RAG |
| `backend/app/core/security.py` | B | **сигнатуры фиксированы** (см. п. 4) |
| `backend/app/api/v1/schemas.py`, `docs/CONTRACTS.md` | общие | только аддитивные изменения, отдельным PR |
| `backend/app/core/{config,db,models,errors,logging,seed}.py`, `alembic/` | общие | см. п. 6 про миграции |
| `docker-compose*.yml`, `backend/Dockerfile`, `.env.example` | общие | маленькие PR, описывать изменения |

## 2. API v1

Базовый префикс `/api/v1`. Авторизация — `Authorization: Bearer <access_token>`. Пока `AUTH_DEV_MODE=true`, все запросы выполняются от имени сид-админа.

| Метод и путь | Владелец | Состояние | Назначение |
|---|---|---|---|
| `POST /auth/token` | B | 501 | вход `{email, password}` → `TokenPair` |
| `POST /auth/refresh` | B | 501 | `{refresh_token}` → `TokenPair` |
| `POST /auth/logout` | B | 501 | отзыв refresh-токена |
| `GET /auth/me` | B | ✅ (dev) | `MeOut`: пользователь, организация, `permissions` |
| `GET/POST /users`, `PATCH /users/{id}` | B | 501 | пользователи организации (org_admin) |
| `GET/POST /organizations` | B | 501 | организации (service_admin) |
| `GET /document-types` | A | ✅ | каталог типов документов |
| `POST /documents` | A | ✅ | multipart `file` → `DocumentUploaded` (валидация Ф-01) |
| `POST /analyses` | A | ✅ | `{document_id, document_type_id}` + заголовок `Idempotency-Key` → 202 `AnalysisCreated` |
| `GET /analyses` | A | ✅ | история: `?status=&page=&page_size=` → `Page[AnalysisListItem]` |
| `GET /analyses/{id}` | A | ✅ | статус: `AnalysisStatusOut` (опрос каждые 1–2 с) |
| `GET /analyses/{id}/result` | A | ✅ | `AnalysisResult`; 409, если проверка ещё не завершена |
| `DELETE /analyses/{id}` | A | ✅ | отмена или удаление |
| `GET /analyses/{id}/report?format=pdf\|docx` | B | 501 | файл отчёта |
| `GET /regulations` | A | ✅ | источники с версиями |
| `POST /regulations?activate=` | A | ✅ | multipart `file` (JSON) → версия `draft`, индексация в воркере → `ready` |
| `GET /regulations/versions/{id}/chunks` | A | ✅ | фрагменты версии |
| `POST /regulations/versions/{id}/activate` | A | ✅ | активация или откат |
| `POST /regulations/versions/{id}/archive` | A | ✅ | архивирование |
| `POST /regulations/versions/{id}/reindex` | A | ✅ | пересчёт эмбеддингов версии |
| `GET /healthz`, `GET /readyz` | общие | ✅ | пробы |

Эндпоинты проверок и нормативки работают по-настоящему (конвейер, воркер, БД). Фикстуры в `api/v1/fixtures.py` оставлены для разработки отчётов и вёрстки (`fixture_result()` — полный `AnalysisResult` с подсветкой).

Статусы версий нормативки: `draft` → `indexing` → `ready` → `active` / `archived`, при ошибке индексации — `failed` (причина в `error_message`). Код ошибки при пустой базе — `knowledge_base_empty`.

### Сценарий фронта (Ф-11)

1. `POST /documents` → `document_id`. При ошибке 422 показать `error.message` (текст уже на русском).
2. `POST /analyses` с `Idempotency-Key: <uuid, сгенерированный на клиенте>` → `analysis_id`.
3. Опрашивать `GET /analyses/{id}`, пока статус не станет `completed`/`failed`; показывать `stage` и `progress`.
4. `GET /analyses/{id}/result` → отчёт:
   - `blocks` — текст договора по абзацам; `findings[].highlights` — подсветка `[start, end)` внутри `block_id`;
   - `findings` уже отсортированы: критические первыми (Ф-10); `category_label` — готовая подпись;
   - `technical_issues` — технические сбои, показываются **отдельно** от юридических замечаний;
   - `is_partial=true` — плашка «проверены не все пункты»;
   - `disclaimer` показывается всегда (Ф-18).
5. `GET /analyses/{id}/report?format=pdf|docx` — скачивание.

### Формат ошибки

Любая ошибка (4xx/5xx):

```json
{"error": {"code": "file_too_large", "message": "Файл слишком большой. Максимальный размер — 10 МБ.", "details": {}}}
```

Коды загрузки: `unsupported_format`, `empty_file`, `file_too_large`, `corrupted_file`, `no_text_layer`, `not_employment_contract`. Общие коды: `unauthorized`, `forbidden`, `not_found`, `conflict`, `validation_error`, `not_implemented`.

### Статусы проверки

`queued` → `extracting` → `analyzing` → `completed` | `failed` | `cancelled`. Подписи на русском — `status_label`.

### Категории замечаний (Ф-07)

`critical` («Критическая»), `recommended` («Рекомендательная»), `info` («Информационная»).

## 3. Роли и права (Ф-15, НФ-09)

| Действие | user | kb_expert | org_admin | service_admin |
|---|---|---|---|---|
| Загрузить договор, запустить проверку | ✅ | ✅ | ✅ | ✅ |
| Видеть свои проверки | ✅ | ✅ | ✅ | ✅ |
| Видеть все проверки своей организации | — | — | ✅ | ✅ (все) |
| Управлять пользователями своей организации | — | — | ✅ | ✅ |
| Управлять нормативной базой | — | ✅ | — | ✅ |
| Управлять организациями | — | — | — | ✅ |

`GET /auth/me` возвращает `permissions` (`analyses:create`, `analyses:read_org`, `users:manage`, `regulations:manage`, `organizations:manage`): по ним UI решает, что показывать.

## 4. Зафиксированные интерфейсы (менять только по договорённости)

```python
# app/core/security.py — реализацию get_current_user меняет B
@dataclass(frozen=True)
class CurrentUser: id, organization_id, role: UserRole, email, full_name
async def get_current_user(...) -> CurrentUser
def require_role(*roles: UserRole) -> Depends   # service_admin проходит всегда
def can_read_analysis(user, *, organization_id, created_by) -> bool

# app/audit/service.py — B
async def log_event(session, *, actor, action, entity_type, entity_id, payload=None, ip_address=None)
# action: "document.upload", "analysis.create", "analysis.delete", "regulation.upload",
#         "regulation.activate", "regulation.archive", "user.create", "user.update", "auth.login", ...
# В payload нельзя класть ПДн, тексты договоров и секреты.

# Для отчётов (B): получить готовый результат
# app/analysis/results.py (A, готово):
async def load_analysis_result(session, analysis_id, user: CurrentUser) -> AnalysisResult
#   проверяет права (can_read_analysis), 404 для чужих, 409 если проверка не завершена.
```

## 5. Данные и инварианты

- Исходный файл удаляется после извлечения текста (НФ-04). В БД хранятся только обезличенные тексты (`analysis_chunks.text`, `analyses.document_blocks`, цитаты в `findings`).
- В логах и `audit_log` нет ПДн и ключей (НФ-12). Логгер с маскированием — `app/core/logging.py`.
- Замечание в статусе violation не может существовать без обеих цитат: это проверяет CHECK-ограничение в БД (НФТ-5).
- Секреты — только в `.env`; `.env` не коммитится.

## 6. Git и миграции

- Ветки: `a/<тема>` и `b/<тема>`; PR в `main`; маленькие PR; перед PR — `git pull --rebase origin main`.
- Схема БД целиком создана в миграции `0001`. Новая миграция создаётся только от свежего `main`:
  `docker compose run --rm api alembic revision --autogenerate -m "..."`. Если в `main` оказалось две головы — `alembic merge heads`.
- Изменения `schemas.py` — только аддитивные (новое поле с умолчанием, новая модель). PR с изменением контракта называть `contract: ...`.
- Перед пушем: `make test` и `make lint` (или `scripts/test.ps1`).

## 7. Тесты

- Юнит-тесты домена — без сети и БД.
- Тесты с БД помечаются `@pytest.mark.db` и пропускаются, если PostgreSQL недоступен; фикстура `client` в `tests/conftest.py`.
- В тестах используются `LLM_PROVIDER=mock` и `EMBEDDING_PROVIDER=hashing`; внешние вызовы запрещены.

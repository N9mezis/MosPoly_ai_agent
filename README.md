# Проверка трудовых договоров по ТК РФ

ИИ-агент загружает трудовой договор (DOCX/PDF), обезличивает его, находит применимые нормы ТК РФ (гибридный поиск по базе знаний), проверяет пункты правилами и языковой моделью (GigaChat) и формирует отчёт: замечания с цитатами из договора и нормы, категорией и рекомендацией.

Стек: Python 3.12, FastAPI, SQLAlchemy, PostgreSQL 16 + pgvector, Redis + ARQ, React + Vite, Docker Compose. Модели вызываются только по API, локального инференса нет.

Интерфейс поддерживает загрузку, просмотр статуса и истории проверок, отчёт с подсветкой и выгрузку в PDF и DOCX. План — [docs/PLAN.md](docs/PLAN.md), контракты — [docs/CONTRACTS.md](docs/CONTRACTS.md), устройство поиска — [docs/RAG.md](docs/RAG.md).

## Быстрый старт

Нужен [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/macOS) или Docker Engine + Compose (Linux).

**Windows (PowerShell):**

```powershell
git clone https://github.com/N9mezis/MosPoly_ai_agent.git
cd MosPoly_ai_agent
.\scripts\up.ps1
```

**Linux / macOS / WSL:**

```bash
git clone https://github.com/N9mezis/MosPoly_ai_agent.git && cd MosPoly_ai_agent && make up
```

Затем откройте:

- интерфейс — http://localhost:8080
- документация API (Swagger) — http://localhost:8000/docs
- готовность сервисов — http://localhost:8000/readyz

По умолчанию `LLM_PROVIDER=mock` и `EMBEDDING_PROVIDER=hashing`: всё работает без ключей и без обращения к внешним сервисам.

Для первой проверки загрузите любой DOCX из `data/contracts/problematic/`. API при старте применяет миграции, создаёт демо-пользователя и загружает нормативную базу, если она пуста. Если анализ не стартует, проверьте состояние API и воркера командой `docker compose ps` и посмотрите логи через `docker compose logs api worker`.

### Вход и режим разработки

В локальном `.env` по умолчанию включён `AUTH_DEV_MODE=true`: API выполняет запросы от имени демо-администратора. Для проверки настоящего входа до первого запуска задайте в `.env` `AUTH_DEV_MODE=false`, случайный `JWT_SECRET` длиной от 32 байт и свой `SEED_ADMIN_PASSWORD`. Для входа используйте `SEED_ADMIN_EMAIL` и заданный пароль. Если база уже создана, используется сохранённый в ней пароль.

Фронтенд хранит access-токен в памяти, а refresh-токен в `localStorage`, чтобы восстанавливать сессию после обновления страницы. Хранение refresh-токена в `localStorage` — компромисс учебного проекта.

## Подключение GigaChat

В [личном кабинете](https://developers.sber.ru/studio) создайте два проекта GigaChat API и получите по Authorization key для каждого. Один ключ используется для генерации, второй для эмбеддингов. Впишите их в `.env`:

```dotenv
LLM_PROVIDER=gigachat
GIGACHAT_LLM_CREDENTIALS=...
GIGACHAT_LLM_MODEL=GigaChat-2

EMBEDDING_PROVIDER=gigachat
GIGACHAT_EMBED_CREDENTIALS=...
GIGACHAT_EMBED_MODEL=Embeddings
```

Затем перезапустите контейнеры: `docker compose up -d`. Сертификат НУЦ Минцифры уже лежит в `certs/` и подключается автоматически. Ключи хранятся только в `.env`, который не попадает в Git.

## Команды

| Действие | Linux / WSL | Windows |
|---|---|---|
| Запустить | `make up` | `.\scripts\up.ps1` |
| Режим разработки (hot-reload) | `make dev` | `.\scripts\dev.ps1` |
| Логи api и worker | `make logs` | `.\scripts\logs.ps1` |
| Тесты | `make test` | `.\scripts\test.ps1` |
| Линтер | `make lint` | `.\scripts\lint.ps1` |
| Служебные команды | `docker compose run --rm api python -m app.cli <cmd>` | `.\scripts\cli.ps1 <cmd>` |
| Остановить | `make down` | `.\scripts\down.ps1` |

На чистой базе сначала запустите проект и дождитесь готовности API, затем запускайте тесты. Проверки с меткой `db` требуют PostgreSQL с pgvector и применёнными миграциями. GitHub Actions проверяет Ruff, весь набор pytest на отдельной БД и сборку фронтенда через `npm ci && npm run build`.

## Структура

```
backend/      FastAPI + воркер ARQ (один образ, два режима)
  app/domain      чистая логика: правила, чанкер, обезличивание, проверка цитат
  app/documents   парсинг DOCX/PDF, приём файлов
  app/knowledge   нормативная база, поиск, реранкер
  app/llm         GigaChat (LLM и эмбеддинги), mock
  app/analysis    конвейер проверки, воркер
  app/auth        пользователи, роли, JWT
  app/reports     PDF/DOCX
  app/api/v1      роутеры и DTO (контракт фронта)
frontend/     React + Vite, в проде отдаётся nginx
data/         нормативка (JSON) и 40 размеченных договоров
evals/        разметка для оценки качества
docs/         план, контракты, проектные документы
```

## Частые проблемы

- **Порт занят** — поменяйте `WEB_PORT` / `API_PORT` / `DB_PORT` в `.env`.
- **`CERTIFICATE_VERIFY_FAILED` при обращении к GigaChat** — проверьте, что `certs/russian_trusted_root_ca_pem.crt` на месте; не отключайте проверку TLS.
- **Скрипты `.sh` падают с `\r`** — клон с CRLF; образ сам исправляет окончания строк, но лучше включить `git config core.autocrlf input`.
- **Контейнер остановился с кодом 137** — проверьте `docker compose ps -a` и логи. Если процесс завершён из-за нехватки памяти, увеличьте доступную Docker Desktop память и повторите запуск.

Результаты носят рекомендательный характер и не являются юридическим заключением.

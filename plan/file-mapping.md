# File Mapping — быстрая навигация для ИИ

> Читай это в начале каждого контекстного окна, затем нужные `docs/`.

## Полная структура проекта (целевая)
> Дерево папок и runtime-архитектура — authoritative в `../docs/05-architecture-and-deployment.md` §1–2.
> Кратко: `docs/` (документация), `plan/` (план), `migrations/` (схема БД),
> `deploy/` (systemd + deploy.sh), `bot/` (код: `services/`, `handlers/` + точки входа).
> На сервере код живёт в `/opt/buklbot/`.

## Документация (docs/)
| Файл | Что внутри | Когда открывать |
|---|---|---|
| `docs/00-index.md` | индекс документации (мапинг) | точка входа |
| `docs/01-tech-spec.md` | Техзадание, решения, структура, verification | общий обзор задачи |
| `docs/02-business-logic.md` | Все сценарии и крайние случаи (псевдокод) | реализация поведения |
| `docs/03-modules-and-conflicts.md` | Зависимости модулей, риски конфликтов | перед правкой модуля |
| `docs/04-data-contract.md` | **SSOT**: таблицы, enum, env, API агента, имена в коде | ВСЕГДА при работе с данными |
| `docs/05-architecture-and-deployment.md` | структура папок, runtime-архитектура, деплой | структура/выкатка |

## План работ (plan/)
| Файл | Что внутри |
|---|---|
| `plan/00-initial-plan.md` | исходный план из режима Plan (историческая основа) |
| `plan/implementation-plan.md` | пошаговый план, что параллельно / что последовательно |
| `plan/file-mapping.md` | этот файл |

## Память (вне проекта)
`C:\Users\1\.claude\projects\c--bukl2\memory\` — креды сервера, протокол, обзор проекта.

## Целевые модули кода (ещё НЕ написаны)
| Путь | Роль | Слой |
|---|---|---|
| `bot/config.py` | env-конфиг | инфра |
| `bot/texts.py` | все тексты кнопок/сообщений | инфра |
| `bot/db.py` | asyncpg pool + запросы | инфра |
| `bot/states.py` | FSM состояния | инфра |
| `bot/keyboards.py` | reply/inline клавиатуры | представление |
| `bot/services/settings.py` | чтение settings из БД | инфра/сервис |
| `bot/services/vps_agent.py` | клиент VPS-агента | сервис |
| `bot/services/subscriptions.py` | единая точка статуса подписки | сервис |
| `bot/services/payments.py` | заявки на оплату | сервис |
| `bot/services/referrals.py` | реферальная логика | сервис |
| `bot/services/traffic.py` | сбор трафика | сервис |
| `bot/handlers/start.py` | /start, регистрация | вход |
| `bot/handlers/menu.py` | поддержка, мои ключи, рефералка | вход |
| `bot/handlers/payment.py` | FSM покупки/продления | вход |
| `bot/handlers/admin.py` | подтверждение/отклонение | вход |
| `bot/webhook_server.py` | приём /agent/expire | вход |
| `bot/scheduler.py` | напоминания + трафик-джоб | вход |
| `bot/main.py` | сборка всего | вход |
| `migrations/001_init.sql` | схема БД | контракт |
| `deploy/buklbot.service` | systemd | деплой |

## Сервер
VPS `87.121.47.233` (root). Креды и команда входа — в memory `server-access.md`.
Агент: `/opt/vps-agent/` (Node, `:3000`). Не дампить `.env`/`tokens.json`.

---

# Деплой
Полная схема деплоя, runtime-архитектура, связки портов/секретов и команды —
в `../docs/05-architecture-and-deployment.md` §2–6. Здесь не дублируем во избежание расхождений.

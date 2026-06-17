# Пошаговый план реализации

> Этап сейчас: только документация. Этот файл — порядок будущей разработки кода.
> Легенда: 🟦 последовательно (блокирует следующее) · 🟩 параллельно (агенты одновременно).
> Перед каждым шагом — чек из `../CLAUDE.md` (конфликт/логика/контракт).
> Полная структура папок и runtime-архитектура — в `file-mapping.md`.

## Этап 0 — Фундамент ✅ ВЫПОЛНЕН (🟦 последовательно)
0.1 ✅ Контракт `docs/04-data-contract.md` подтверждён.
0.2 ✅ `migrations/001_init.sql`: 10 таблиц + индексы + RLS(deny-all) + сиды `tariffs`(2), `settings`(7).
0.3 ✅ Миграция `001_init` применена через Supabase MCP; схема проверена (`list_tables` = 10 таблиц).
    Advisor: только INFO «RLS enabled, no policy» — ожидаемо (бот ходит прямым PG-соединением).
> Готово к Этапу 1. TODO в БД перед боевым запуском: задать реальные `payment_admin_id`,
> `payment_requisites`, `support_username` (сейчас плейсхолдеры).

## Этап 1 — Инфраструктура ✅ ВЫПОЛНЕН (🟩 4 агента Sonnet, параллельно)
| Агент | Файлы | Статус |
|---|---|---|
| A1 | `bot/config.py`, `.env.example` | ✅ 7 env-констант + validate() |
| A2 | `bot/db.py` (asyncpg pool + хелперы) | ✅ init/close/pool/fetch/fetchrow/fetchval/execute |
| A3 | `bot/texts.py` (тексты, BTN_*), `bot/states.py` | ✅ 7 кнопок, ~22 текста, BuyFlow(3 состояния) |
| A4 | `bot/services/settings.py` | ✅ get/get_int/get_all/refresh + TTL-кэш |
> Оркестратор добавил `bot/__init__.py`, `bot/services/__init__.py`, `bot/handlers/__init__.py`,
> `requirements.txt`, `.gitignore`. Проверка: `py_compile` OK + сквозной импорт всех слоёв OK (venv).
> Барьер пройден → готово к Этапу 2.

## Этап 2 — Сервисы (🟩 параллельно, но с правилом единой точки статуса)
2.1 🟦 СНАЧАЛА `bot/services/vps_agent.py` (клиент агента) — от него зависят другие.
2.2 🟦 ЗАТЕМ `bot/services/subscriptions.py` — ЕДИНСТВЕННАЯ точка смены статуса.
2.3 🟩 ПОТОМ параллельно:
| Агент | Файл | Зависит от |
|---|---|---|
| B1 | `bot/services/payments.py` | subscriptions |
| B2 | `bot/services/referrals.py` | subscriptions |
| B3 | `bot/services/traffic.py` | vps_agent |
> На сервере параллельно (🟩, отдельный агент S1): добавить `POST /vps/keys/traffic`
> в `/opt/vps-agent/`, согласовать `VPS_AGENT_TOKEN`. Не ломать существующие эндпоинты.

## Этап 3 — Представление и входные точки (🟩 параллельно, 5 агентов)
| Агент | Файлы | Зависит от |
|---|---|---|
| C0 | `bot/keyboards.py` (reply/inline, callback_data формат) | texts, tariffs |
| C1 | `bot/handlers/start.py` | users, subscriptions, keyboards |
| C2 | `bot/handlers/menu.py` (поддержка/мои ключи/рефералка) | settings, subscriptions, referrals |
| C3 | `bot/handlers/payment.py` (FSM) | states, payments, keyboards |
| C4 | `bot/handlers/admin.py` (approve/reject + реф-проверка) | payments, subscriptions, referrals |
> C0 (keyboards) желательно первым — C1..C4 на него опираются. Затем C1..C4 параллельно.

## Этап 4 — Связки и фон (🟩 параллельно, затем сборка)
| Агент | Файл |
|---|---|
| D1 | `bot/webhook_server.py` (/agent/expire) |
| D2 | `bot/scheduler.py` (напоминания + трафик-джоб) |
> 🟦 ЗАТЕМ `bot/main.py` — собирает polling + webhook + scheduler (один агент, после D1/D2).

## Этап 5 — Деплой и проверка (🟦 последовательно)
> Полная схема деплоя, runtime-архитектура и команды — в `file-mapping.md` §Деплой.
5.1 Артефакты: `requirements.txt`, `.env.example`, `deploy/buklbot.service`, `deploy/deploy.sh`.
5.2 Код на сервер в `/opt/buklbot/` (rsync), venv + `pip install`, заполнить `/opt/buklbot/.env`.
5.3 Связать агент: `EXPIRE_CALLBACK_URL=http://127.0.0.1:8081/agent/expire` в `/opt/vps-agent/.env`,
    согласовать `VPS_AGENT_TOKEN`, `systemctl restart vps-agent`.
5.4 `systemctl enable --now buklbot`; проверить `journalctl -u buklbot -f`.
5.5 Прогон e2e из `docs/01-tech-spec.md` §Verification.

## Сводка распараллеливания
- 🟦 строго по порядку: Этап 0 → (vps_agent → subscriptions) → main.py → деплой.
- 🟩 можно параллелить: вся инфраструктура (Этап 1), payments/referrals/traffic (2.3),
  handlers C1..C4 (3), webhook+scheduler (4), серверный traffic-эндпоинт.
- Жёсткое правило: статус подписки меняет только `subscriptions.py`; контракт — только в `04`.

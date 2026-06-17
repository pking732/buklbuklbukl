# 03 — Взаимозависимые модули и возможные конфликты при разработке

> Цель: чтобы параллельные агенты не ломали друг друга. Перед правкой модуля сверяйся
> с разделом «Кто от него зависит» и контрактом `04-data-contract.md`.

## Карта модулей и зависимостей
```
config.py ──┐
texts.py ───┼──> keyboards.py ──> handlers/*
db.py ──────┼──> services/* ─────> handlers/*
states.py ──┘
services/vps_agent.py ──> services/{subscriptions,payments,referrals,traffic}.py
services/settings.py ──> (читают почти все)
handlers/{start,menu,payment,admin}.py ──> main.py
webhook_server.py ──> services/subscriptions.py
scheduler.py ──> services/{subscriptions,traffic}.py
main.py связывает: bot polling + webhook_server + scheduler
```

## Слои (стрелка = «зависит от», править снизу вверх осторожно)
1. **Контракт** (`04-data-contract.md`, `migrations/001_init.sql`) — фундамент. Менять = риск для ВСЕХ.
2. **Инфраструктура**: `config.py`, `db.py`, `texts.py`, `states.py`, `services/settings.py`.
3. **Сервисы**: `vps_agent.py`, `subscriptions.py`, `payments.py`, `referrals.py`, `traffic.py`.
4. **Представление/вход**: `keyboards.py`, `handlers/*`, `webhook_server.py`, `scheduler.py`, `main.py`.

## Таблица «кто от кого зависит»
| Модуль | Зависит от | Кто зависит от него | Конфликтная зона |
|---|---|---|---|
| `migrations/001_init.sql` | контракт | все services | имена таблиц/колонок/enum |
| `config.py` | .env | все | имена env-переменных |
| `texts.py` | — | keyboards, handlers | ключи кнопок (BTN_*) |
| `states.py` | — | payment.py | имена FSM-состояний |
| `services/settings.py` | db | handlers, scheduler | ключи settings |
| `services/vps_agent.py` | config | subscriptions, traffic, admin | формат deviceKeyId, поля ответа |
| `services/subscriptions.py` | db, vps_agent | menu, payment, admin, webhook, scheduler | enum status, expires_at |
| `services/payments.py` | db, subscriptions | payment, admin | enum kind/status, applied_optimistically |
| `services/referrals.py` | db, subscriptions | admin | threshold/bonus, referred_by |
| `handlers/payment.py` | states, keyboards, payments | main | FSM переходы |
| `handlers/admin.py` | payments, subscriptions, referrals | main | callback_data формат |
| `webhook_server.py` | subscriptions | main | путь /agent/expire, Bearer |
| `scheduler.py` | subscriptions, traffic | main | интервалы |

## Возможные конфликты и как их избежать
1. **Двойная запись `subscriptions.status`** из `payment.py`, `admin.py`, `webhook_server.py`,
   `scheduler.py`. → Только `services/subscriptions.py` меняет статус (единая точка). Хендлеры
   вызывают её методы, не пишут в БД напрямую.
2. **Формат `device_key_id`** — единственное место `device_key_id()` helper. Нигде не собирать строку руками.
3. **`callback_data` админских кнопок** — зафиксировать формат: `pay:approve:<payment_id>` /
   `pay:reject:<payment_id>`. Менять только согласованно с `admin.py`.
4. **Гонка approve/expire**: админ подтверждает уже истёкший ключ. → перед `create/extend`
   проверять `vps status`; если ключа нет и подписка `expired` — пересоздавать корректно.
5. **Реферал засчитан дважды** — защищает `UNIQUE(referred_id)` в `referral_events`; код
   делает `INSERT ... ON CONFLICT DO NOTHING` и инкремент только при успешной вставке.
6. **Откат продления** при reject — хранить `applied_optimistically` и `duration_days`
   в `payments`, откатывать ровно эту дельту (не «минус 30» хардкодом).
7. **Тексты vs динамика**: статичные тексты — `texts.py`; тарифы/реквизиты/поддержка — БД.
   Не хардкодить суммы/реквизиты в коде.
8. **Часовые пояса** — везде UTC `TIMESTAMPTZ`; форматирование в локаль только при показе юзеру.
9. **Изменение API агента** (`/vps/keys/traffic` нужно добавить на сервере) — затрагивает
   и сервер, и `vps_agent.py`. Согласовывать обе стороны + `VPS_AGENT_TOKEN`.

## Правила параллельной работы агентов
- Один агент = один слой/модуль из таблицы выше; не лезть в чужой модуль.
- Любая правка контракта (`04`/миграции) — STOP, согласование, потом остальное.
- Перед коммитом модуля прогнать чек из `../CLAUDE.md` (конфликт/логика/контракт).

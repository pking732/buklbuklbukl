# 00 — Исходный план (составлен в режиме Plan)

> Это первоначальный план, согласованный с пользователем в режиме планирования.
> Сохранён как историческая основа. Актуальные детали разнесены по `docs/` и `plan/`:
> ТЗ → `../docs/01-tech-spec.md`, бизнес-логика → `../docs/02-business-logic.md`,
> конфликты модулей → `../docs/03-modules-and-conflicts.md`,
> контракт данных → `../docs/04-data-contract.md`,
> архитектура/деплой → `../docs/05-architecture-and-deployment.md`,
> порядок работ → `implementation-plan.md`, навигация → `file-mapping.md`.
> При расхождении источником истины считать `docs/`, а не этот файл.

---

# ТЗ: Telegram-бот продажи VPN-подписок (buklproxy)

## Context

Есть рабочий VPN-сервер `87.121.47.233` (Ubuntu 24.04, Армения), который уже выдаёт
ключи. Цель — Telegram-бот, который автоматизирует весь цикл: приветствие/регистрация,
продажу и продление подписки (ручная оплата на карту + подтверждение админом),
выдачу ключей, поддержку, реферальную программу и контроль срока подписки.

### Что уже есть на сервере (проверено по SSH, read-only)
- `xray` (VLESS/REALITY, порт 443 + доп. инбаунды), `hysteria2` (UDP) — healthy.
- Кастомный **`buklproxy` VPS-agent** (Node/Express) `vps-agent.service`,
  слушает `0.0.0.0:3000`. Файлы: `/opt/vps-agent/src/index.js`, `/opt/vps-agent/.env`,
  `/opt/vps-agent/data/{keys,tokens}.json`.
- Подписочный URL отдаётся на `https://<HOST>:2096/sub/<subToken>`.

### API агента (всё с заголовком `Authorization: Bearer <VPS_AGENT_TOKEN>`)
| Метод | Тело | Ответ |
|---|---|---|
| `POST /vps/keys/create` | `{deviceKeyId, expiresAt(ISO\|null), maxDevices}` | `{ok, uuid, subToken, subUrl, countries[]}` — **идемпотентен** (вернёт существующий) |
| `POST /vps/keys/disable` | `{deviceKeyId}` | `{ok}` — удаляет клиента из xray |
| `POST /vps/keys/extend` | `{deviceKeyId, expiresAt}` | `{ok}` |
| `POST /vps/keys/status` | `{deviceKeyId}` | `{present, uuid, expiresAt, createdAt}` |
| `GET /vps/health` | — | `{ok, xray, activeKeys, timestamp}` |

- **Авто-экспирация:** агент раз в 6 ч удаляет ключи с истёкшим `expiresAt`, режет
  их в xray и **POST-ит `{deviceKeyId}` на `EXPIRE_CALLBACK_URL`** (Bearer-авторизация).
  → это и есть «вебхук, когда сервер отрубил подписку». Срок enforced server-side.

**Вывод:** боту НЕ нужно самому резать VPN — достаточно вызвать `disable`/`extend`/`create`
и принимать колбэк об экспирации. `deviceKeyId = "tg<telegram_id>"` связывает БД и сервер.

## Принятые решения
- **Стек:** Python 3.12 + **aiogram 3** (FSM, reply-клавиатуры, async).
- **БД:** **Supabase (Postgres)**, схема/миграции применяются через **Supabase MCP**.
  Доступ из бота — `asyncpg` по connection string (нужен BIGINT PK, индексы, транзакции).
- **Хостинг:** тот же VPS `87.121.47.233`. Бот = polling Telegram + локальный
  aiohttp-сервер на `127.0.0.1` для приёма колбэка экспирации.
  `EXPIRE_CALLBACK_URL = http://127.0.0.1:<PORT>/agent/expire`.
- **Оплата:** ручная (карта из БД) + подтверждение платёжным админом (MVP).
- **Тексты кнопок и статические сообщения** → в конфиг (`texts.py`).
  **Динамические значения** (тарифы, реквизиты, юзернейм поддержки, id платёжного
  админа, условия рефералки) → в БД.

---

## Схема БД (ключ пользователя везде — `telegram_id BIGINT`, без внутренних UUID)
> Полная актуальная версия — в `../docs/04-data-contract.md`.

### `users`
- `telegram_id BIGINT PRIMARY KEY`
- `username TEXT`, `first_name TEXT`
- `referred_by BIGINT NULL` → FK `users.telegram_id` (кто пригласил; ставится ТОЛЬКО
  при первом `/start` нового юзера, если параметр валиден и ≠ сам себя)
- `created_at TIMESTAMPTZ`, `last_start_at TIMESTAMPTZ`

### `subscriptions` (одна строка на пользователя)
- `telegram_id BIGINT PRIMARY KEY` → FK `users`
- `status TEXT` ∈ `none | active | waiting_for_acceptance | expired | blocked`
- `device_key_id TEXT` (= `tg<telegram_id>`), `sub_url TEXT`, `sub_token TEXT`
- `max_devices INT`, `expires_at TIMESTAMPTZ NULL`
- `notified_expiring BOOLEAN DEFAULT false` (анти-дубль уведомления «остался день»)
- `created_at`, `updated_at`

### `tariffs` (каталог, рендерится в кнопки)
- `id BIGSERIAL PK`, `code TEXT UNIQUE`
- `title TEXT` (текст кнопки), `price_rub NUMERIC`, `duration_days INT`,
  `max_devices INT`, `sort_order INT`, `is_active BOOLEAN`
- **Сид:** `990₽ / 1 мес / 2 устр (30 дн)`, `2490₽ / 3 мес / 2 устр (90 дн)`
  (в надиктовке звучало 2390 и 2490 — беру последнее, 2490; правится в БД).

### `payments` (заявки на оплату)
- `id BIGSERIAL PK`
- `telegram_id BIGINT` → FK `users` (кто платит)
- `tariff_code TEXT`, `amount_rub NUMERIC`, `duration_days INT` (снапшоты на момент заявки)
- `kind TEXT` ∈ `purchase | extension`
- `sender_name TEXT` (ФИО отправителя, введённое юзером)
- `status TEXT` ∈ `pending | approved | rejected`
- `applied_optimistically BOOLEAN` (для продления/доверенных — начислено ли заранее,
  что откатывать при reject)
- `admin_id BIGINT NULL`, `created_at`, `processed_at`

### `fraud_list` (недобросовестные — отдельной таблицей, как просили)
- `telegram_id BIGINT PRIMARY KEY` → FK `users`
- `reason TEXT`, `related_payment_id BIGINT`, `added_at TIMESTAMPTZ`
- Членство в таблице = клиент «в режиме ожидания» при новой покупке.

### `referral_progress`
- `telegram_id BIGINT PRIMARY KEY` (реферер)
- `confirmed_count INT DEFAULT 0` (текущий цикл, сбрасывается после подарка)
- `gifts_received INT DEFAULT 0`, `updated_at`

### `referral_events` (каждый засчитанный платный реферал)
- `id BIGSERIAL PK`, `referrer_id BIGINT`, `referred_id BIGINT UNIQUE`,
  `payment_id BIGINT`, `counted_at TIMESTAMPTZ`
- `UNIQUE(referred_id)` → один приглашённый засчитывается один раз навсегда.

### `settings` (key-value, гибкие значения)
- `key TEXT PK`, `value TEXT`, `description TEXT`
- Ключи: `support_username`, `payment_admin_id`, `payment_requisites` (реквизиты карты,
  multiline), `referral_threshold` (=2), `referral_bonus_days` (=30),
  `expiry_reminder_hours` (=24).

---

## Сценарии (бизнес-логика)
> Полная актуальная версия — в `../docs/02-business-logic.md`.

### /start и регистрация
- Парсим `start`-параметр (`?start=<referrer_telegram_id>`).
- Если юзера нет в `users`:
  - вставляем; если параметр валиден (реферер существует и ≠ сам) → `referred_by`.
  - шлём приветственный текст о сервисе + показываем **reply-клавиатуру** главного меню.
- Если есть: «рады снова видеть» + меню.
- Главное меню (reply-кнопки): **Купить / Продлить подписку**, **Поддержка**,
  **Хочу заработать**, **Мои ключи**.

### Поддержка
- Сообщение с `support_username` из `settings`.

### Мои ключи
- Если `subscription.status == active` → показываем `sub_url` (+ страны/ссылки).
- Иначе → «нет активной подписки».

### Купить / Продлить
- Рендерим кнопки из `tariffs` (is_active, sort_order) — **reply-клавиатура**, не инлайн.
- Выбор тарифа → экран оплаты: сумма + реквизиты (`payment_requisites`),
  кнопки **«Я оплатил»** и **«Отменить»**. «Отменить» доступна на всех шагах → главное меню.
- «Я оплатил» → FSM просит ввести **ФИО отправителя** → создаётся `payment` (`pending`).
- Определяем `kind`: `extension` если есть активная подписка, иначе `purchase`.

**Выдача доступа (момент создания заявки):**
- `purchase`, юзер НЕ в `fraud_list` (добросовестный) → сразу `create` ключа на сервере
  с `expiresAt = now + duration`, `subscription.status = active`, `applied_optimistically=true`.
  Сообщение: «спасибо, ключ уже в разделе Мои ключи».
- `purchase`, юзер В `fraud_list` → ключ НЕ создаём, `status = waiting_for_acceptance`,
  доступа к «Мои ключи» нет. Сообщение: «подписка будет доступна после проверки оплаты».
- `extension` (есть активная подписка) → всегда оптимистично: `extend` на сервере
  `+duration`, `applied_optimistically=true`. (Риск низкий — база уже оплачена.)

**Уведомление платёжному админу** (`payment_admin_id` из БД), инлайн-кнопки
**Подтвердить / Отклонить**: «Новая оплата от @username, тариф, сумма, ФИО».

**Решение админа:**
- *Подтвердить:* `payment.status=approved`. Если был `waiting_for_acceptance` → теперь
  `create` ключа + `status=active`, юзеру «подписка подтверждена, доступна в Мои ключи».
  Для уже активных — финализация (ничего не режем). → затем **реферальная проверка** (ниже).
- *Отклонить:* `payment.status=rejected`.
  - `purchase` добросовестного: `disable` ключа, `status=expired`, юзер → `fraud_list`,
    сообщение «платёж не прошёл, попробуйте ещё раз».
  - `purchase` недобросовестного (был в ожидании): `status` остаётся без доступа,
    «платёж не прошёл».
  - `extension`: откат начисленных дней (`extend` обратно к прежнему `expires_at`),
    «платёж не прошёл, дни сгорели».

### Реферальная программа («Хочу заработать»)
- Кнопка показывает: реф-ссылку `https://t.me/<bot>?start=<telegram_id>`, прогресс
  (`confirmed_count / referral_threshold`, бонус `referral_bonus_days`), и кнопку
  **«Условия реферальной программы»** (текст из конфига/настроек).
- Реферал засчитывается **только при approve админом НОВОЙ покупки** (`purchase`)
  приглашённого, который был новым юзером (`referred_by` задан) и ещё не в `referral_events`.
- На approve: `INSERT referral_events` (если нет), `confirmed_count += 1`.
  При достижении `threshold` (2): подарок — `extend` подписки реферера `+30 дн`,
  `confirmed_count = 0`, `gifts_received += 1`, уведомление «+30 дней, подписка до …».

### Контроль срока
- **Колбэк экспирации:** агент POST `{deviceKeyId}` → `/agent/expire` (Bearer = `VPS_AGENT_TOKEN`).
  Бот: `telegram_id` из `deviceKeyId`, `status=expired`, уведомление «подписка истекла».
- **Напоминания (APScheduler, раз в 12 ч):** найти подписки с `expires_at` в ближайшие
  24 ч и `notified_expiring=false` → уведомить, выставить флаг. Сбрасывать флаг при продлении.

---

## Учёт трафика по ключу (ТЕХНИЧЕСКИ ВОЗМОЖНО — подтверждено)

Особенность сервиса: ключ формально показывает ~13 стран, но фактически весь трафик
идёт через один реальный сервер; клиенты подключаются по подписочной ссылке в приложении
**Happ**. Один `device_key_id` на юзера → можно агрегировать трафик по нему.

Проверено: в xray включён `stats` + `policy.levels.0.statsUserUplink/Downlink:true`,
`StatsService` на `127.0.0.1:10085`. Агент заводит клиента с `deviceKeyId` как email,
поэтому доступны счётчики `user>>>tg<telegram_id>>>>traffic>>>uplink|downlink`.

- `user_traffic` (итог по юзеру, ключ `telegram_id`): `total_*`, `total_bytes` (lifetime),
  `period_bytes`, `updated_at`.
- `traffic_usage` (детализация по периодам, опционально).
- Сбор: добавить агенту `POST /vps/keys/traffic {deviceKeyId, reset}` → `{uplink, downlink}`;
  джоб бота опрашивает с `reset=true` и аккумулирует. Фича опциональна.

## Шаги внедрения (исходные)
1. Через **Supabase MCP**: применить `001_init.sql` + сиды `tariffs`, `settings`.
2. `vps_agent.py` + проверка против живого агента.
3. Хендлеры start/menu/payment/admin + FSM + клавиатуры + `texts.py`.
4. `webhook_server.py` + `scheduler.py`.
5. Связать агент (`EXPIRE_CALLBACK_URL`, `VPS_AGENT_TOKEN`), `buklbot.service`.
> Детализированный порядок с распараллеливанием — в `implementation-plan.md`.

## Открытые решения по умолчанию (правятся в БД)
- Продление = всегда оптимистично (не зависит от fraud_list) — риск низкий, база оплачена.
- Длительность продления = duration выбранного тарифа (30 дн — только реф-бонус).
- Один `device_key_id` на юзера, `maxDevices` из тарифа (тариф = «2 устройства»).
- Тариф 3 мес = 2490₽ (из надиктовки 2390/2490 — взято последнее).

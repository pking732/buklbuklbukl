# 04 — Контракт данных и переменных

> **Это единый источник истины (single source of truth).** Любой модуль/агент обязан
> соблюдать имена таблиц, колонок, enum-значений, ключей `settings` и переменных
> окружения именно так, как здесь написано. Менять контракт — только через правку
> этого файла + явное согласование. См. правила в `../CLAUDE.md`.

---

## 0. Железные правила
- Ключ пользователя ВЕЗДЕ — `telegram_id BIGINT`. Внутренних `UUID`/`user_id` нет.
- Сущности-события (`payments`, `referral_events`, `traffic_usage`) могут иметь
  технический `id BIGSERIAL`, но связь с юзером — всегда колонка `telegram_id BIGINT`.
- Связь БД ↔ VPN-сервер: `device_key_id = "tg" || telegram_id` (пример: `tg123456789`).
- Все денежные суммы — `NUMERIC(10,2)`, валюта — рубли. Все даты — `TIMESTAMPTZ` (UTC).

---

## 1. Таблицы (Supabase / Postgres)

### `users`
| колонка | тип | примечание |
|---|---|---|
| telegram_id | BIGINT PK | главный ключ |
| username | TEXT NULL | без `@` |
| first_name | TEXT NULL | |
| referred_by | BIGINT NULL | FK users.telegram_id; ставится 1 раз при первом /start |
| created_at | TIMESTAMPTZ | default now() |
| last_start_at | TIMESTAMPTZ | |

### `subscriptions` (1 строка на юзера)
| колонка | тип | примечание |
|---|---|---|
| telegram_id | BIGINT PK | FK users |
| status | TEXT | enum ниже |
| device_key_id | TEXT | `tg<telegram_id>` |
| sub_url | TEXT NULL | подписочная ссылка для Happ |
| sub_token | TEXT NULL | |
| max_devices | INT | из тарифа |
| expires_at | TIMESTAMPTZ NULL | |
| notified_expiring | BOOLEAN | default false; сброс при продлении |
| created_at / updated_at | TIMESTAMPTZ | |

**enum `subscriptions.status`:** `none | active | waiting_for_acceptance | expired | blocked`
- `active` — доступ к «Мои ключи» есть.
- `waiting_for_acceptance` — оплата создана недобросовестным, ждёт админа, доступа нет.
- `expired` — истекла/отклонена, доступа нет.
- `blocked` — заблокирована вручную, доступа нет.
- `none` — никогда не покупал.

### `tariffs` (каталог → кнопки)
| колонка | тип | примечание |
|---|---|---|
| id | BIGSERIAL PK | технический |
| code | TEXT UNIQUE | напр. `1m_2dev` |
| title | TEXT | текст кнопки, напр. `990₽ / 1 месяц` |
| price_rub | NUMERIC(10,2) | |
| duration_days | INT | 30, 90 |
| max_devices | INT | 2 |
| sort_order | INT | |
| is_active | BOOLEAN | |

Сид: `('1m_2dev','990₽ / 1 месяц / 2 устройства',990,30,2,1,true)`,
`('3m_2dev','2490₽ / 3 месяца / 2 устройства',2490,90,2,2,true)`.

### `payments` (заявки)
| колонка | тип | примечание |
|---|---|---|
| id | BIGSERIAL PK | |
| telegram_id | BIGINT | FK users |
| tariff_code | TEXT | снапшот |
| amount_rub | NUMERIC(10,2) | снапшот |
| duration_days | INT | снапшот |
| kind | TEXT | `purchase | extension` |
| sender_name | TEXT | ФИО отправителя |
| status | TEXT | `pending | approved | rejected` |
| applied_optimistically | BOOLEAN | начислено заранее → откатывать при reject |
| admin_id | BIGINT NULL | кто обработал |
| created_at / processed_at | TIMESTAMPTZ | |

### `fraud_list` (недобросовестные — отдельная таблица)
| колонка | тип | примечание |
|---|---|---|
| telegram_id | BIGINT PK | FK users |
| reason | TEXT | |
| related_payment_id | BIGINT NULL | |
| added_at | TIMESTAMPTZ | |

### `referral_progress`
| колонка | тип | примечание |
|---|---|---|
| telegram_id | BIGINT PK | реферер |
| confirmed_count | INT | текущий цикл, сброс после подарка |
| gifts_received | INT | |
| updated_at | TIMESTAMPTZ | |

### `referral_events`
| колонка | тип | примечание |
|---|---|---|
| id | BIGSERIAL PK | |
| referrer_id | BIGINT | FK users |
| referred_id | BIGINT UNIQUE | засчитывается 1 раз навсегда |
| payment_id | BIGINT | |
| counted_at | TIMESTAMPTZ | |

### `settings` (key-value)
| колонка | тип |
|---|---|
| key | TEXT PK |
| value | TEXT |
| description | TEXT |

**Обязательные ключи `settings`:**
| key | пример value | смысл |
|---|---|---|
| support_username | `@bukl_support` | юзернейм поддержки |
| payment_admin_id | `123456789` | telegram_id платёжного админа |
| payment_requisites | `Карта 2200 0000 0000 0000\nИванов И.И.` | реквизиты (multiline) |
| referral_threshold | `2` | сколько оплативших до подарка |
| referral_bonus_days | `30` | бонус в днях |
| expiry_reminder_hours | `24` | за сколько часов до конца напоминать |
| referral_terms | `<текст условий>` | текст для кнопки «Условия» |

### `user_traffic` (итог по юзеру)
| колонка | тип | примечание |
|---|---|---|
| telegram_id | BIGINT PK | FK users |
| total_uplink_bytes | BIGINT | lifetime |
| total_downlink_bytes | BIGINT | lifetime |
| total_bytes | BIGINT | lifetime сумма |
| period_bytes | BIGINT | текущий период |
| updated_at | TIMESTAMPTZ | |

### `traffic_usage` (детализация по периодам, опционально)
| колонка | тип |
|---|---|
| id | BIGSERIAL PK |
| telegram_id | BIGINT (FK users) |
| device_key_id | TEXT |
| period_start / period_end | TIMESTAMPTZ |
| uplink_bytes / downlink_bytes / total_bytes | BIGINT |
| collected_at | TIMESTAMPTZ |

индекс `(telegram_id, period_start)`.

---

## 2. Контракт VPS-агента (НЕ менять без правки сервера)

Base: `http://127.0.0.1:3000`. Заголовок: `Authorization: Bearer <VPS_AGENT_TOKEN>`.

| Метод | Тело | Ответ |
|---|---|---|
| `POST /vps/keys/create` | `{deviceKeyId, expiresAt(ISO\|null), maxDevices}` | `{ok, uuid, subToken, subUrl, countries[]}` идемпотентен |
| `POST /vps/keys/disable` | `{deviceKeyId}` | `{ok}` |
| `POST /vps/keys/extend` | `{deviceKeyId, expiresAt}` | `{ok}` |
| `POST /vps/keys/status` | `{deviceKeyId}` | `{present, uuid, expiresAt, createdAt}` |
| `GET /vps/health` | — | `{ok, xray, activeKeys, timestamp}` |
| (нужно добавить) `POST /vps/keys/traffic` | `{deviceKeyId, reset}` | `{uplink, downlink}` |

Колбэк агента → боту: `POST <EXPIRE_CALLBACK_URL>` body `{deviceKeyId}`, Bearer = `VPS_AGENT_TOKEN`.
`subUrl` формат: `https://<VPS_HOST>:2096/sub/<subToken>`.

---

## 3. Переменные окружения бота (`.env`)
| имя | пример | смысл |
|---|---|---|
| BOT_TOKEN | `123:ABC` | токен Telegram-бота |
| BOT_USERNAME | `bukl_vpn_bot` | для реф-ссылки |
| PG_DSN | `postgresql://...supabase...` | Supabase Postgres |
| VPS_AGENT_URL | `http://127.0.0.1:3000` | |
| VPS_AGENT_TOKEN | `<тот же, что в /opt/vps-agent/.env>` | общий секрет |
| WEBHOOK_HOST | `127.0.0.1` | приём колбэка экспирации |
| WEBHOOK_PORT | `8081` | → `EXPIRE_CALLBACK_URL=http://127.0.0.1:8081/agent/expire` |

---

## 4. Внутренний контракт (имена в коде)
- FSM states (модуль `states.py`): `BuyFlow.choosing_tariff`, `BuyFlow.payment_screen`,
  `BuyFlow.entering_sender_name`.
- Тексты кнопок/сообщений — только в `texts.py` (см. `01-tech-spec.md` §структура).
- Reply-кнопки главного меню (тексты в `texts.py`, ключи фиксируем):
  `BTN_BUY`, `BTN_SUPPORT`, `BTN_EARN`, `BTN_MY_KEYS`, `BTN_CANCEL`.
- Хелпер `device_key_id(telegram_id) -> f"tg{telegram_id}"` — единственное место формирования.

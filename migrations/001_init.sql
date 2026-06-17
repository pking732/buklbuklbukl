-- 001_init.sql — начальная схема buklproxy VPN bot
-- Контракт: docs/04-data-contract.md. Ключ пользователя везде telegram_id BIGINT.
-- Применяется через Supabase MCP (apply_migration).

-- ─────────────────────────── users ───────────────────────────
CREATE TABLE IF NOT EXISTS users (
    telegram_id   BIGINT PRIMARY KEY,
    username      TEXT,
    first_name    TEXT,
    referred_by   BIGINT REFERENCES users(telegram_id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_start_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_users_referred_by ON users(referred_by);

-- ─────────────────────────── subscriptions ───────────────────────────
CREATE TABLE IF NOT EXISTS subscriptions (
    telegram_id       BIGINT PRIMARY KEY REFERENCES users(telegram_id),
    status            TEXT NOT NULL DEFAULT 'none'
                      CHECK (status IN ('none','active','waiting_for_acceptance','expired','blocked')),
    device_key_id     TEXT NOT NULL,
    sub_url           TEXT,
    sub_token         TEXT,
    max_devices       INT NOT NULL DEFAULT 0,
    expires_at        TIMESTAMPTZ,
    notified_expiring BOOLEAN NOT NULL DEFAULT false,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status     ON subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_expires_at ON subscriptions(expires_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_subscriptions_device_key_id ON subscriptions(device_key_id);

-- ─────────────────────────── tariffs (каталог) ───────────────────────────
CREATE TABLE IF NOT EXISTS tariffs (
    id            BIGSERIAL PRIMARY KEY,
    code          TEXT UNIQUE NOT NULL,
    title         TEXT NOT NULL,
    price_rub     NUMERIC(10,2) NOT NULL,
    duration_days INT NOT NULL,
    max_devices   INT NOT NULL,
    sort_order    INT NOT NULL DEFAULT 0,
    is_active     BOOLEAN NOT NULL DEFAULT true
);

-- ─────────────────────────── payments (заявки) ───────────────────────────
CREATE TABLE IF NOT EXISTS payments (
    id                     BIGSERIAL PRIMARY KEY,
    telegram_id            BIGINT NOT NULL REFERENCES users(telegram_id),
    tariff_code            TEXT NOT NULL,
    amount_rub             NUMERIC(10,2) NOT NULL,
    duration_days          INT NOT NULL,
    kind                   TEXT NOT NULL CHECK (kind IN ('purchase','extension')),
    sender_name            TEXT,
    status                 TEXT NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending','approved','rejected')),
    applied_optimistically BOOLEAN NOT NULL DEFAULT false,
    admin_id               BIGINT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at           TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_payments_telegram_id ON payments(telegram_id);
CREATE INDEX IF NOT EXISTS idx_payments_status      ON payments(status);

-- ─────────────────────────── fraud_list (недобросовестные) ───────────────────────────
CREATE TABLE IF NOT EXISTS fraud_list (
    telegram_id        BIGINT PRIMARY KEY REFERENCES users(telegram_id),
    reason             TEXT,
    related_payment_id BIGINT,
    added_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────── referral_progress ───────────────────────────
CREATE TABLE IF NOT EXISTS referral_progress (
    telegram_id     BIGINT PRIMARY KEY REFERENCES users(telegram_id),
    confirmed_count INT NOT NULL DEFAULT 0,
    gifts_received  INT NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────── referral_events ───────────────────────────
CREATE TABLE IF NOT EXISTS referral_events (
    id          BIGSERIAL PRIMARY KEY,
    referrer_id BIGINT NOT NULL REFERENCES users(telegram_id),
    referred_id BIGINT NOT NULL UNIQUE REFERENCES users(telegram_id),
    payment_id  BIGINT,
    counted_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_referral_events_referrer ON referral_events(referrer_id);

-- ─────────────────────────── settings (key-value) ───────────────────────────
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    description TEXT
);

-- ─────────────────────────── user_traffic (итог по юзеру) ───────────────────────────
CREATE TABLE IF NOT EXISTS user_traffic (
    telegram_id          BIGINT PRIMARY KEY REFERENCES users(telegram_id),
    total_uplink_bytes   BIGINT NOT NULL DEFAULT 0,
    total_downlink_bytes BIGINT NOT NULL DEFAULT 0,
    total_bytes          BIGINT NOT NULL DEFAULT 0,
    period_bytes         BIGINT NOT NULL DEFAULT 0,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────── traffic_usage (детализация) ───────────────────────────
CREATE TABLE IF NOT EXISTS traffic_usage (
    id             BIGSERIAL PRIMARY KEY,
    telegram_id    BIGINT NOT NULL REFERENCES users(telegram_id),
    device_key_id  TEXT NOT NULL,
    period_start   TIMESTAMPTZ NOT NULL,
    period_end     TIMESTAMPTZ NOT NULL,
    uplink_bytes   BIGINT NOT NULL DEFAULT 0,
    downlink_bytes BIGINT NOT NULL DEFAULT 0,
    total_bytes    BIGINT NOT NULL DEFAULT 0,
    collected_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_traffic_usage_tg_period ON traffic_usage(telegram_id, period_start);

-- ─────────────────────────── RLS (deny-all для анонимного PostgREST) ───────────────────────────
-- Бот ходит через прямое Postgres-соединение (роль postgres, обходит RLS).
-- Включаем RLS без политик, чтобы закрыть anon/публичный доступ.
ALTER TABLE users             ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions     ENABLE ROW LEVEL SECURITY;
ALTER TABLE tariffs           ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments          ENABLE ROW LEVEL SECURITY;
ALTER TABLE fraud_list        ENABLE ROW LEVEL SECURITY;
ALTER TABLE referral_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE referral_events   ENABLE ROW LEVEL SECURITY;
ALTER TABLE settings          ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_traffic      ENABLE ROW LEVEL SECURITY;
ALTER TABLE traffic_usage     ENABLE ROW LEVEL SECURITY;

-- ─────────────────────────── Сиды ───────────────────────────
INSERT INTO tariffs (code, title, price_rub, duration_days, max_devices, sort_order, is_active) VALUES
    ('1m_2dev', '990₽ / 1 месяц / 2 устройства',  990,  30, 2, 1, true),
    ('3m_2dev', '2490₽ / 3 месяца / 2 устройства', 2490, 90, 2, 2, true)
ON CONFLICT (code) DO NOTHING;

INSERT INTO settings (key, value, description) VALUES
    ('support_username',     '@bukl_support',                 'Юзернейм поддержки (TODO: заменить)'),
    ('payment_admin_id',     '0',                             'telegram_id платёжного админа (TODO: заменить)'),
    ('payment_requisites',   'Карта: 0000 0000 0000 0000\nПолучатель: TODO', 'Реквизиты для оплаты (multiline, TODO)'),
    ('referral_threshold',   '2',                             'Сколько оплативших рефералов до подарка'),
    ('referral_bonus_days',  '30',                            'Бонус в днях за выполнение реф-условий'),
    ('expiry_reminder_hours','24',                            'За сколько часов до конца напоминать'),
    ('referral_terms',       'Пригласите 2 друзей, которые оплатят любой тариф — получите +30 дней бесплатно.', 'Текст условий реф-программы')
ON CONFLICT (key) DO NOTHING;

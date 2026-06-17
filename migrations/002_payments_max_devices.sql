-- 002_payments_max_devices.sql
-- Снапшот max_devices в payments: нужен на approve для confirm_waiting (создание ключа
-- ожидавшему недобросовестному клиенту), когда хендлер уже не участвует.
-- Консистентно с уже снапшоченными duration_days / amount_rub.

ALTER TABLE payments ADD COLUMN IF NOT EXISTS max_devices INT NOT NULL DEFAULT 0;

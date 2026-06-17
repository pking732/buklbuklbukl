# 02 — Бизнес-логика

> Источник истины по поведению. Состояния и имена — из `04-data-contract.md`.

## 1. /start и регистрация
```
вход /start [param]
param = аргумент после /start (потенциальный referrer telegram_id)
есть ли юзер в users?
├─ НЕТ (новый):
│   insert users(telegram_id, username, first_name, created_at, last_start_at)
│   если param валиден (есть такой users.telegram_id и param != self):
│       users.referred_by = param        # фиксируется ТОЛЬКО здесь, 1 раз
│   subscriptions: insert (status='none', device_key_id='tg'+id, max_devices=0)
│   referral_progress: insert (confirmed_count=0)
│   отправить ПРИВЕТСТВЕННЫЙ текст о сервисе + reply-меню
└─ ДА (повторный):
    update last_start_at
    отправить «рады снова видеть» + reply-меню
```
Реф-связь засчитывается ТОЛЬКО для нового юзера. Если по ссылке зашёл тот, кто уже был
в системе — связь не пишется.

## 2. Главное меню (reply-клавиатура)
Кнопки: **Купить/Продлить**, **Поддержка**, **Хочу заработать**, **Мои ключи**.
«Отменить» возвращает в главное меню из любого шага FSM.

## 3. Поддержка
Отправить сообщение с `settings.support_username`.

## 4. Мои ключи
```
subscriptions.status == 'active'?
├─ ДА  → показать sub_url (ссылка для Happ) + список стран/инфо
└─ НЕТ → «у вас нет активной подписки»
```

## 5. Покупка / Продление — создание заявки
```
нажатие Купить/Продлить → рендер тарифов из tariffs(is_active) в reply-кнопки
выбор тарифа → экран оплаты: amount + settings.payment_requisites
            кнопки: «Я оплатил», «Отменить»
«Я оплатил» → FSM: запросить ФИО отправителя
ввод ФИО → определить kind:
    kind = 'extension' если subscriptions.status=='active' иначе 'purchase'
    insert payments(telegram_id, tariff_code, amount, duration_days, kind,
                    sender_name, status='pending')
```
**Выдача доступа в момент заявки:**
```
kind == 'purchase':
    юзер в fraud_list?
    ├─ НЕТ (добросовестный):
    │     vps create(deviceKeyId, expiresAt=now+duration, maxDevices)
    │     subscriptions: status='active', expires_at=now+duration, sub_url=...
    │     payments.applied_optimistically=true
    │     юзеру: «спасибо, ключ в разделе Мои ключи»
    └─ ДА (недобросовестный):
          ключ НЕ создаём
          subscriptions.status='waiting_for_acceptance'
          юзеру: «подписка будет доступна после проверки оплаты»
kind == 'extension' (есть активная подписка) — ВСЕГДА оптимистично:
    vps extend(deviceKeyId, expiresAt = текущий expires_at + duration)
    subscriptions.expires_at += duration; notified_expiring=false
    payments.applied_optimistically=true
    юзеру: «оплата принята, срок продлён до <дата>»
```
Затем во всех случаях: уведомить `settings.payment_admin_id` инлайн-кнопками
**Подтвердить / Отклонить** + текст: «Новая оплата от @username, тариф, сумма, ФИО, kind».

## 6. Решение платёжного админа
```
ПОДТВЕРДИТЬ:
    payments.status='approved', admin_id, processed_at
    если subscriptions.status=='waiting_for_acceptance' (был недобросовестный purchase):
        vps create(...); status='active'; expires_at=now+duration
        юзеру: «подписка подтверждена, доступна в Мои ключи»
    иначе (активный purchase/extension): финализация, ничего не режем
    → затем РЕФЕРАЛЬНАЯ ПРОВЕРКА (§7)

ОТКЛОНИТЬ:
    payments.status='rejected', admin_id, processed_at
    kind=='purchase' и был добросовестный (applied_optimistically):
        vps disable(deviceKeyId); subscriptions.status='expired'
        fraud_list: insert(telegram_id, reason, related_payment_id)
        юзеру: «платёж не прошёл, попробуйте ещё раз»
    kind=='purchase' и был недобросовестный (waiting_for_acceptance):
        статус остаётся без доступа; юзеру: «платёж не прошёл»
    kind=='extension':
        откат: vps extend(expiresAt = expires_at - duration)
        subscriptions.expires_at -= duration
        юзеру: «платёж не прошёл, начисленные дни сгорели»
```

## 7. Реферальная проверка (ТОЛЬКО при approve НОВОЙ покупки)
```
триггер: админ подтвердил payment где kind=='purchase'
u = users[payments.telegram_id]
если u.referred_by IS NULL → стоп
если referred_id уже есть в referral_events → стоп (засчитан ранее)
insert referral_events(referrer_id=u.referred_by, referred_id=u.telegram_id, payment_id)
referral_progress[u.referred_by].confirmed_count += 1
если confirmed_count >= settings.referral_threshold (2):
    ПОДАРОК рефереру:
        base = referrer.subscriptions.expires_at или now (если нет активной)
        vps extend(referrer.deviceKeyId, base + referral_bonus_days)
        referrer.subscriptions.expires_at = base + bonus
        confirmed_count = 0; gifts_received += 1
        рефереру: «+30 дней, подписка до <дата>»
```
Продление (`extension`) рефералов НЕ засчитывает — только первая платная покупка приглашённого.

## 8. Контроль срока подписки
```
КОЛБЭК экспирации (агент → POST /agent/expire {deviceKeyId}):
    telegram_id = parse(deviceKeyId)
    subscriptions.status='expired'
    юзеру: «подписка истекла, продлите»

НАПОМИНАНИЯ (APScheduler, раз в 12ч):
    для подписок где status='active'
        и expires_at <= now + settings.expiry_reminder_hours
        и notified_expiring=false:
        юзеру напоминание; notified_expiring=true
    (флаг сбрасывается при продлении)
```

## 9. Реферальная программа (экран «Хочу заработать»)
Показать: реф-ссылку `https://t.me/<BOT_USERNAME>?start=<telegram_id>`,
прогресс `confirmed_count / referral_threshold` (бонус `referral_bonus_days`),
кнопку «Условия реферальной программы» (текст `settings.referral_terms`).

## 10. Учёт трафика
```
джоб (APScheduler, раз в N часов) для каждого активного device_key_id:
    {uplink, downlink} = vps traffic(deviceKeyId, reset=true)
    user_traffic: total_uplink += uplink; total_downlink += downlink
                  total_bytes += uplink+downlink; period_bytes += uplink+downlink
    (опц.) insert traffic_usage(period_start, period_end, ...)
```

## Спорные решения (зафиксированы, правятся в БД)
- Тариф 3 мес = **2490₽** (в надиктовке звучало 2390 и 2490 — взято последнее).
- Продление — **всегда оптимистично**, даже для недобросовестных (риск низкий, база оплачена).
- Длительность продления = `duration_days` выбранного тарифа (30 дней — только реф-бонус).
- Один `device_key_id` на юзера, `maxDevices` из тарифа (тариф = «2 устройства»).

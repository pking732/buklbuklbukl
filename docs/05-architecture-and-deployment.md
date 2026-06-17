# 05 — Архитектура папок и деплой

> Источник истины по структуре проекта и выкатке. `plan/file-mapping.md` ссылается сюда.

## 1. Структура проекта (целевая)
```
c:\bukl2\                         # репозиторий (локально на Windows)
├── CLAUDE.md                     # жёсткие правила + чек перед правками
├── README.md                     # (опц.) краткое описание для людей
├── .env.example                  # шаблон переменных (без секретов)
├── .gitignore                    # .env, __pycache__, *.bak
├── requirements.txt              # зависимости Python
├── docs/                         # ДОКУМЕНТАЦИЯ (источник истины)
│   ├── 01-tech-spec.md
│   ├── 02-business-logic.md
│   ├── 03-modules-and-conflicts.md
│   ├── 04-data-contract.md       # SSOT: данные/контракты
│   └── 05-architecture-and-deployment.md   # этот файл
├── plan/                         # ПЛАН РАБОТ
│   ├── 00-initial-plan.md        # исходный план из режима Plan
│   ├── implementation-plan.md    # этапы 🟦/🟩
│   └── file-mapping.md           # навигация
├── migrations/                   # СХЕМА БД (через Supabase MCP)
│   └── 001_init.sql
├── deploy/                       # ДЕПЛОЙ
│   ├── buklbot.service           # systemd unit
│   └── deploy.sh                 # скрипт выкатки на VPS
└── bot/                          # КОД (пишется позже)
    ├── main.py                   # точка входа: polling + webhook + scheduler
    ├── config.py                 # чтение .env
    ├── texts.py                  # все тексты/кнопки (BTN_*)
    ├── states.py                 # FSM
    ├── db.py                     # asyncpg pool
    ├── keyboards.py              # reply/inline
    ├── webhook_server.py         # aiohttp /agent/expire (127.0.0.1)
    ├── scheduler.py              # APScheduler (напоминания + трафик)
    ├── services/
    │   ├── settings.py
    │   ├── vps_agent.py
    │   ├── subscriptions.py      # ЕДИНСТВЕННАЯ точка смены статуса
    │   ├── payments.py
    │   ├── referrals.py
    │   └── traffic.py
    └── handlers/
        ├── start.py
        ├── menu.py
        ├── payment.py
        └── admin.py
```
На сервере код живёт в `/opt/buklbot/` (зеркало `bot/` + `.env` + venv).

## 2. Runtime-архитектура
```
┌─────────────────────── VPS 87.121.47.233 (Ubuntu 24.04) ───────────────────────┐
│                                                                                  │
│  systemd: buklbot.service ──► python /opt/buklbot/bot/main.py (venv)             │
│     ├─ aiogram polling ──────────────► Telegram API (long polling, исходящий)    │
│     ├─ aiohttp webhook  127.0.0.1:8081/agent/expire  ◄── колбэк от агента        │
│     └─ APScheduler (напоминания + сбор трафика)                                   │
│              │ asyncpg                                                            │
│              ▼                                                                    │
│        Supabase Postgres (облако)  ◄── миграции применяются через Supabase MCP   │
│                                                                                  │
│  systemd: vps-agent.service ──► node /opt/vps-agent (:3000)                       │
│     ├─ /vps/keys/* (Bearer VPS_AGENT_TOKEN)  ◄── вызывает бот (127.0.0.1:3000)    │
│     ├─ авто-экспирация (6ч) ──► POST 127.0.0.1:8081/agent/expire (Bearer)         │
│     └─ xray (:443, stats :10085) + hysteria2                                      │
└──────────────────────────────────────────────────────────────────────────────┘
```
- Бот ↔ агент — только по `127.0.0.1` (наружу порты не открываем).
- Telegram — исходящий polling, входящих портов для бота не нужно.
- БД — внешняя (Supabase), доступ по `PG_DSN`.

## 3. Связки портов/секретов (единые значения с обеих сторон)
| Что | Значение | Где задаётся |
|---|---|---|
| Агент API | `http://127.0.0.1:3000` | `bot/.env` → `VPS_AGENT_URL` |
| Общий токен | `VPS_AGENT_TOKEN` | одинаков в `/opt/vps-agent/.env` и `/opt/buklbot/.env` |
| Webhook бота | `127.0.0.1:8081/agent/expire` | `bot/.env` → `WEBHOOK_HOST/PORT` |
| Колбэк агента | тот же URL | `/opt/vps-agent/.env` → `EXPIRE_CALLBACK_URL` |
| БД | Supabase DSN | `bot/.env` → `PG_DSN` |

Полный список env — в `04-data-contract.md` §3.

## 4. Порядок деплоя (последовательно)
1. **БД:** применить `migrations/001_init.sql` через **Supabase MCP**; засидить `tariffs`, `settings`.
2. **Код на сервер:** `deploy/deploy.sh` (rsync `bot/` → `/opt/buklbot/`).
3. **Окружение:** на сервере venv + `pip install -r requirements.txt`; заполнить `/opt/buklbot/.env`.
4. **Связать агент:** `EXPIRE_CALLBACK_URL=http://127.0.0.1:8081/agent/expire` в `/opt/vps-agent/.env`,
   согласовать `VPS_AGENT_TOKEN`, `systemctl restart vps-agent`.
5. **Сервис бота:** `deploy/buklbot.service` → `/etc/systemd/system/`,
   `systemctl daemon-reload && systemctl enable --now buklbot`.
6. **Проверка:** `systemctl status buklbot`, `journalctl -u buklbot -f`, e2e из `01-tech-spec.md`.

## 5. Команды (шпаргалка)
```bash
# вход (Windows, plink); пароль/fingerprint — в memory server-access.md
plink -ssh -batch -hostkey "SHA256:CAXAAaz40ocz1Wpl+YpiBRxt+w/2DdlY2aUf1c54FWg" \
  -pw "<pwd>" root@87.121.47.233 "<cmd>"

# первичная настройка на сервере
apt install -y python3.12-venv
mkdir -p /opt/buklbot && cd /opt/buklbot
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt

# выкатка обновления
rsync -az --delete bot/ root@87.121.47.233:/opt/buklbot/bot/
ssh root@87.121.47.233 "systemctl restart buklbot"

# логи / статус
systemctl status buklbot vps-agent
journalctl -u buklbot -f
```

## 6. Update flow (что требует передеплоя)
- Только код (`bot/`): rsync + `systemctl restart buklbot`.
- Изменилась схема БД: сперва миграция через Supabase MCP, ПОТОМ деплой кода.
- Изменился контракт агента: сперва правка `/opt/vps-agent/` + рестарт, ПОТОМ бот.
- Тарифы/реквизиты/тексты-из-БД: правятся в Supabase без передеплоя.

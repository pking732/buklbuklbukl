"""
config.py — загрузка и валидация переменных окружения бота.

Единственное место, где читается .env. Все остальные модули импортируют
константы отсюда, не обращаясь к os.getenv напрямую.
Контракт переменных: docs/04-data-contract.md §3.
"""

import os

from dotenv import load_dotenv

# Загружаем .env из рабочей директории (или родительской, если запуск из bot/)
load_dotenv()

# ---------------------------------------------------------------------------
# Обязательные переменные (без дефолта)
# ---------------------------------------------------------------------------

# Токен Telegram-бота (выдаётся @BotFather)
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# Username бота без «@» — нужен для генерации реферальных ссылок
BOT_USERNAME: str = os.getenv("BOT_USERNAME", "")

# DSN Supabase Postgres для asyncpg (postgresql://user:pass@host/db)
PG_DSN: str = os.getenv("PG_DSN", "")

# Общий секретный токен для авторизации запросов к VPS-агенту и его колбэков
VPS_AGENT_TOKEN: str = os.getenv("VPS_AGENT_TOKEN", "")

# ---------------------------------------------------------------------------
# Переменные с дефолтными значениями
# ---------------------------------------------------------------------------

# Базовый URL VPS-агента (Node, :3000, только localhost)
VPS_AGENT_URL: str = os.getenv("VPS_AGENT_URL", "http://127.0.0.1:3000")

# Хост, на котором бот слушает входящий колбэк экспирации от агента
WEBHOOK_HOST: str = os.getenv("WEBHOOK_HOST", "127.0.0.1")

# Порт для aiohttp-сервера колбэка экспирации (/agent/expire)
WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8081"))


# ---------------------------------------------------------------------------
# Валидация
# ---------------------------------------------------------------------------

def validate() -> None:
    """Проверяет, что все обязательные переменные заданы и не пусты.

    Вызывается при импорте модуля. Если хотя бы одна переменная отсутствует —
    бот не запустится, сразу получим понятную ошибку вместо странных сбоев.
    """
    required = {
        "BOT_TOKEN": BOT_TOKEN,
        "BOT_USERNAME": BOT_USERNAME,
        "PG_DSN": PG_DSN,
        "VPS_AGENT_TOKEN": VPS_AGENT_TOKEN,
    }

    missing = [name for name, value in required.items() if not value]

    if missing:
        raise RuntimeError(
            f"Missing required env: {', '.join(missing)}\n"
            "Заполните .env-файл (см. .env.example)."
        )


validate()

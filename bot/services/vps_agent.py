"""
vps_agent.py — async HTTP-клиент к VPS-агенту (Node, :3000).

Реализует контракт из docs/04-data-contract.md §2.
Все методы используют httpx.AsyncClient с Bearer-авторизацией.

ВАЖНО: device_key_id формируется ТОЛЬКО через helper device_key_id() —
единственное место в проекте (см. CLAUDE.md «Железные инварианты»).
"""

import httpx
from datetime import datetime, timezone

import bot.config as config

# Таймаут по умолчанию для всех запросов к агенту (секунды)
_TIMEOUT = 15.0


# ---------------------------------------------------------------------------
# Хелперы device_key_id (единственное место формирования)
# ---------------------------------------------------------------------------

def device_key_id(telegram_id: int) -> str:
    """Формирует device_key_id из telegram_id.

    Единственное место в проекте, где собирается эта строка.
    Контракт: docs/04-data-contract.md §0 и §4.
    """
    return f"tg{telegram_id}"


def telegram_id_from_key(device_key_id: str) -> int:
    """Обратная операция: извлекает telegram_id из device_key_id.

    Срезает префикс «tg» и возвращает целое число.
    """
    return int(device_key_id.removeprefix("tg"))


# ---------------------------------------------------------------------------
# Вспомогательная функция: создать клиент с нужными заголовками
# ---------------------------------------------------------------------------

def _make_client() -> httpx.AsyncClient:
    """Создаёт httpx.AsyncClient с Bearer-заголовком и таймаутом."""
    return httpx.AsyncClient(
        base_url=config.VPS_AGENT_URL,
        headers={"Authorization": f"Bearer {config.VPS_AGENT_TOKEN}"},
        timeout=_TIMEOUT,
    )


def _to_iso(dt: datetime) -> str:
    """Конвертирует datetime в ISO-8601 строку (UTC).

    Если datetime naive — считаем UTC. Если aware — конвертируем в UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


# ---------------------------------------------------------------------------
# Методы API агента
# ---------------------------------------------------------------------------

async def create_key(
    device_key_id: str,
    expires_at: datetime | None,
    max_devices: int,
) -> dict:
    """Создаёт (или обновляет идемпотентно) VPN-ключ на агенте.

    POST /vps/keys/create
    Тело: {deviceKeyId, expiresAt (ISO-8601 | null), maxDevices}
    Ответ: {ok, uuid, subToken, subUrl, countries[]}

    Контракт: docs/04-data-contract.md §2.
    """
    payload: dict = {
        "deviceKeyId": device_key_id,
        "expiresAt": _to_iso(expires_at) if expires_at is not None else None,
        "maxDevices": max_devices,
    }
    async with _make_client() as client:
        response = await client.post("/vps/keys/create", json=payload)
        response.raise_for_status()
        return response.json()


async def disable_key(device_key_id: str) -> dict:
    """Отключает VPN-ключ на агенте.

    POST /vps/keys/disable
    Тело: {deviceKeyId}
    Ответ: {ok}
    """
    async with _make_client() as client:
        response = await client.post(
            "/vps/keys/disable",
            json={"deviceKeyId": device_key_id},
        )
        response.raise_for_status()
        return response.json()


async def extend_key(device_key_id: str, expires_at: datetime) -> dict:
    """Продлевает срок действия VPN-ключа.

    POST /vps/keys/extend
    Тело: {deviceKeyId, expiresAt (ISO-8601)}
    Ответ: {ok}
    """
    async with _make_client() as client:
        response = await client.post(
            "/vps/keys/extend",
            json={
                "deviceKeyId": device_key_id,
                "expiresAt": _to_iso(expires_at),
            },
        )
        response.raise_for_status()
        return response.json()


async def status_key(device_key_id: str) -> dict:
    """Возвращает статус VPN-ключа.

    POST /vps/keys/status
    Тело: {deviceKeyId}
    Ответ: {present, uuid, expiresAt, createdAt}
    """
    async with _make_client() as client:
        response = await client.post(
            "/vps/keys/status",
            json={"deviceKeyId": device_key_id},
        )
        response.raise_for_status()
        return response.json()


async def health() -> dict:
    """Проверяет состояние VPS-агента.

    GET /vps/health
    Ответ: {ok, xray, activeKeys, timestamp}
    """
    async with _make_client() as client:
        response = await client.get("/vps/health")
        response.raise_for_status()
        return response.json()


async def get_traffic(device_key_id: str, reset: bool = True) -> dict:
    """Возвращает статистику трафика по ключу.

    POST /vps/keys/traffic
    Тело: {deviceKeyId, reset}
    Ответ: {uplink, downlink}

    ВАЖНО: эндпоинт опциональный — если сервер вернул 404 или произошла
    ошибка соединения, возвращаем нули и НЕ кидаем исключение.
    Контракт: docs/04-data-contract.md §2.
    """
    try:
        async with _make_client() as client:
            response = await client.post(
                "/vps/keys/traffic",
                json={"deviceKeyId": device_key_id, "reset": reset},
            )
            # 404 — эндпоинт ещё не реализован на сервере: возвращаем нули
            if response.status_code == 404:
                return {"uplink": 0, "downlink": 0}
            response.raise_for_status()
            return response.json()
    except httpx.ConnectError:
        # Агент недоступен — трафик недоступен, не критично
        return {"uplink": 0, "downlink": 0}
    except httpx.HTTPStatusError:
        # Любая другая HTTP-ошибка тоже не должна ломать вызывающий код
        return {"uplink": 0, "downlink": 0}

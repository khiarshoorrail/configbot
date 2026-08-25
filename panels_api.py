import json
import logging
import random
import string
import time
import uuid

import httpx

import database

log = logging.getLogger(__name__)


class PanelError(Exception):
    pass


class AllPanelsFailedError(PanelError):
    pass


def gb_to_bytes(gb: int) -> int:
    return gb * 1024 * 1024 * 1024


def _random_sub_id(k: int = 12) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=k))


class XUIClient:
    """کلاینت پنل 3x-ui."""

    def __init__(self, panel: dict) -> None:
        self.panel = panel
        self._client = httpx.AsyncClient(
            base_url=panel["base_url"].rstrip("/"), timeout=15, verify=False
        )
        self._cookie: str | None = None

    async def close(self) -> None:
        await self._client.aclose()

    async def _login(self) -> None:
        try:
            resp = await self._client.post(
                "/login",
                data={"username": self.panel.get("username"), "password": self.panel.get("password")},
            )
            data = resp.json()
        except Exception as e:
            raise PanelError(f"3x-ui login unreachable: {e}") from e
        if not data.get("success"):
            raise PanelError(f"3x-ui login failed: {data.get('msg')}")
        cookie_header = resp.headers.get("set-cookie", "")
        self._cookie = cookie_header.split(";")[0] if cookie_header else None

    async def _post(self, path: str, json_body: dict) -> dict:
        for _ in (1, 2):
            headers = {"Cookie": self._cookie} if self._cookie else {}
            resp = await self._client.post(path, json=json_body, headers=headers)
            try:
                data = resp.json()
            except Exception:
                raise PanelError(f"non-JSON from {path}: HTTP {resp.status_code}: {resp.text[:200]}")
            if data.get("msg") == "login required" or resp.status_code == 401:
                await self._login()
                continue
            return data
        raise PanelError(f"request failed after retry: {path}")

    async def test_connection(self) -> str:
        await self._login()
        return "✅ لاگین موفق"

    async def create_config(self, total_gb_bytes: int, days: int, limit_ip: int = 0) -> str:
        sub_id = _random_sub_id()
        client = {
            "id": uuid.uuid4().hex,
            "flow": "",
            "email": f"bot-{sub_id}",
            "limitIp": limit_ip,
            "totalGB": total_gb_bytes,
            "expiryTime": int(time.time() * 1000) + days * 86400 * 1000,
            "enable": True,
            "tgId": "",
            "subId": sub_id,
            "reset": 0,
        }
        inbound = self.panel["inbound_id"]
        data = await self._post(
            f"/panel/api/inbounds/addClient/{inbound}",
            {"id": inbound, "settings": json.dumps({"clients": [client]})},
        )
        if not data.get("success"):
            raise PanelError(f"addClient failed: {data.get('msg')}")
        log.info("xui client created on panel %s: %s", self.panel["name"], client["email"])
        return f"{self.panel['sub_base_url'].rstrip('/')}/{sub_id}"


class MarzbanClient:
    """کلاینت پنل Marzban."""

    def __init__(self, panel: dict) -> None:
        self.panel = panel
        self._client = httpx.AsyncClient(
            base_url=panel["base_url"].rstrip("/"), timeout=15, verify=False
        )
        self._token: str | None = panel.get("token") or None

    async def close(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict:
        h = {}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    async def _login(self) -> None:
        try:
            resp = await self._client.post(
                "/api/admin/token",
                data={"username": self.panel.get("username"), "password": self.panel.get("password")},
            )
            data = resp.json()
        except Exception as e:
            raise PanelError(f"marzban login unreachable: {e}") from e
        token = data.get("access_token")
        if not token:
            raise PanelError(f"marzban login failed: {data.get('detail', data)}")
        self._token = token

    async def _ensure_auth(self) -> None:
        if not self._token:
            await self._login()

    async def test_connection(self) -> str:
        await self._login()
        return "✅ لاگین موفق"

    async def create_config(self, total_gb_bytes: int, days: int, limit_ip: int = 0) -> str:
        await self._ensure_auth()
        username = "bot-" + _random_sub_id(10)
        body = {
            "username": username,
            "proxies": {"vless": {"flow": ""}},
            "data_limit": total_gb_bytes or None,
            "expire": int(time.time()) + days * 86400,
            "data_limit_reset_strategy": "no_reset",
            "status": "active",
        }
        resp = await self._client.post("/api/users", json=body, headers=self._headers())
        if resp.status_code == 401:
            await self._login()
            resp = await self._client.post("/api/users", json=body, headers=self._headers())
        if resp.status_code not in (200, 201):
            raise PanelError(f"marzban create user failed: HTTP {resp.status_code}: {resp.text[:200]}")
        log.info("marzban user created on panel %s: %s", self.panel["name"], username)
        return f"{self.panel['sub_base_url'].rstrip('/')}/sub/{username}/"


CLIENTS = {"xui": XUIClient, "marzban": MarzbanClient}

_rr_index = 0


def make_client(panel: dict):
    cls = CLIENTS.get(panel["type"])
    if not cls:
        raise PanelError(f"نوع پنل ناشناخته: {panel['type']}")
    return cls(panel)


async def create_config_on_any_panel(total_gb_bytes: int, days: int, limit_ip: int = 0) -> tuple[str, str]:
    """روی پنل‌های فعال به‌صورت چرخشی تلاش می‌کند؛ (لینک، نام پنل) برمی‌گرداند."""
    global _rr_index
    panels = await database.list_panels(only_enabled=True)
    if not panels:
        raise AllPanelsFailedError("هیچ پنل فعالی ثبت نشده. از /panels یک پنل اضافه کن.")

    errors: list[str] = []
    n = len(panels)
    for offset in range(n):
        panel = panels[(_rr_index + offset) % n]
        client = make_client(panel)
        try:
            sub_url = await client.create_config(total_gb_bytes, days, limit_ip)
            _rr_index = (_rr_index + offset + 1) % n
            return sub_url, panel["name"]
        except Exception as e:  # noqa: BLE001 — خطای هر پنل نباید بقیه را متوقف کند
            msg = f"{panel['name']}: {e}"
            log.error("create_config failed on %s", msg)
            errors.append(msg)
        finally:
            await client.close()

    raise AllPanelsFailedError(" | ".join(errors))


async def test_panel(panel: dict) -> str:
    client = make_client(panel)
    try:
        return await client.test_connection()
    finally:
        await client.close()

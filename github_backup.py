import base64
import logging
import os
import time

import httpx

import config

log = logging.getLogger(__name__)

API = "https://api.github.com"


class BackupError(Exception):
    pass


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def backup_enabled() -> bool:
    return bool(_env("GITHUB_BACKUP_REPO") and (_env("GITHUB_TOKEN") or _get_gh_token()))


def _get_gh_token() -> str:
    """توکن gh CLI (فقط روی لپ‌تاپ موجود است)."""
    try:
        import subprocess
        out = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=10,
            shell=os.name == "nt",
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _token() -> str:
    return _env("GITHUB_TOKEN") or _get_gh_token()


async def upload_backup() -> str:
    """دیتابیس را در ریپوی بکاپ گیت‌هاب ذخیره می‌کند؛ URL کامیت را برمی‌گرداند."""
    repo = _env("GITHUB_BACKUP_REPO")
    token = _token()
    if not repo or not token:
        raise BackupError("GITHUB_BACKUP_REPO یا GITHUB_TOKEN تنظیم نشده.")

    try:
        with open(config.DATABASE_PATH, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode()
    except OSError as e:
        raise BackupError(f"خواندن دیتابیس ناموفق: {e}") from e

    stamp = time.strftime("%Y-%m-%d")
    path = f"bot-{stamp}.db"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        # sha فایل موجود در امروز (برای به‌روزرسانی به‌جای خطا)
        sha = None
        r = await client.get(f"{API}/repos/{repo}/contents/{path}", headers=headers)
        if r.status_code == 200:
            sha = r.json().get("sha")

        body = {
            "message": f"backup {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "content": content_b64,
        }
        if sha:
            body["sha"] = sha
        r = await client.put(f"{API}/repos/{repo}/contents/{path}", headers=headers, json=body)
        if r.status_code not in (200, 201):
            raise BackupError(f"GitHub API: HTTP {r.status_code}: {r.text[:300]}")

        commit_sha = r.json().get("commit", {}).get("sha", "")
        html_url = f"https://github.com/{repo}/blob/main/{path}"
        log.info("backup uploaded: %s", path)

    await _cleanup_old(client=None, headers=headers, repo=repo, keep=_keep_count())

    return html_url


def _keep_count() -> int:
    try:
        return max(int(_env("GITHUB_BACKUP_KEEP") or "14"), 3)
    except ValueError:
        return 14


async def _cleanup_old(client, headers: dict, repo: str, keep: int) -> None:
    """نسخه‌های قدیمی‌تر از keep تا روز را حذف می‌کند."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30)
    try:
        r = await client.get(f"{API}/repos/{repo}/contents/", headers=headers)
        if r.status_code != 200:
            return
        files = [f for f in r.json() if f["name"].startswith("bot-") and f["name"].endswith(".db")]
        files.sort(key=lambda f: f["name"], reverse=True)
        for old in files[keep:]:
            d = await client.delete(
                f"{API}/repos/{repo}/contents/{old['path']}",
                headers={**headers, "X-GitHub-Api-Version": "2022-11-28"},
                json={"message": "backup cleanup", "sha": old["sha"]},
            )
            if d.status_code == 200:
                log.info("backup cleanup removed %s", old["name"])
    finally:
        if own_client:
            await client.aclose()

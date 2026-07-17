import asyncio
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import urlparse

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from checker import check_site
from database import (
    add_site,
    delete_site,
    get_recent_checks,
    get_site,
    get_site_statuses,
    get_sites,
    init_db,
    save_check,
)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
MAX_SITE_NAME_LENGTH = 120
MAX_SITE_URL_LENGTH = 2048
DEFAULT_CHECK_CONCURRENCY = 5


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="网站状态监控",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
basic_auth = HTTPBasic(auto_error=False)


class SiteInput(BaseModel):
    name: str = Field(max_length=MAX_SITE_NAME_LENGTH)
    url: str = Field(max_length=MAX_SITE_URL_LENGTH)


def normalize_site_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("请输入网站名称")
    if len(cleaned) > MAX_SITE_NAME_LENGTH:
        raise ValueError(f"网站名称不能超过 {MAX_SITE_NAME_LENGTH} 个字符")
    return cleaned


def normalize_url(url: str) -> str:
    cleaned = url.strip()
    if not cleaned:
        raise ValueError("请输入网站地址")
    if len(cleaned) > MAX_SITE_URL_LENGTH:
        raise ValueError(f"网站地址不能超过 {MAX_SITE_URL_LENGTH} 个字符")
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        raise ValueError("请输入有效的网站地址")

    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"

    try:
        parsed = urlparse(cleaned)
    except ValueError as error:
        raise ValueError("请输入有效的 http 或 https 地址") from error

    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise ValueError("请输入有效的 http 或 https 地址")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("网站地址不能包含账号信息")
    if any(character.isspace() for character in parsed.netloc):
        raise ValueError("请输入有效的网站地址")

    try:
        parsed.port
    except ValueError as error:
        raise ValueError("网站地址端口无效") from error

    return cleaned


def require_admin(
    credentials: Optional[HTTPBasicCredentials] = Depends(basic_auth),
):
    """配置 ADMIN_PASSWORD 后，为后台页面和管理接口启用 Basic Auth。"""
    expected_password = os.getenv("ADMIN_PASSWORD", "")
    if not expected_password:
        return None

    expected_username = os.getenv("ADMIN_USERNAME", "admin")
    username_matches = credentials is not None and secrets.compare_digest(
        credentials.username.encode("utf-8"),
        expected_username.encode("utf-8"),
    )
    password_matches = credentials is not None and secrets.compare_digest(
        credentials.password.encode("utf-8"),
        expected_password.encode("utf-8"),
    )
    if not (username_matches and password_matches):
        raise HTTPException(
            status_code=401,
            detail="需要管理员认证",
            headers={"WWW-Authenticate": "Basic"},
        )
    return None


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=()",
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    )
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    if request.url.scheme == "https":
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000",
        )
    return response


def render_template(filename: str):
    html_path = os.path.join(TEMPLATE_DIR, filename)
    with open(html_path, "r", encoding="utf-8") as template_file:
        return HTMLResponse(content=template_file.read())


def run_site_check(site):
    result = check_site(site["url"])
    save_check(
        site["id"],
        result["status"],
        result.get("status_code"),
        result.get("response_time"),
        result.get("ssl_days_left"),
        result.get("error_msg"),
    )
    return result


async def run_site_check_async(site):
    return await run_in_threadpool(run_site_check, site)


def get_check_concurrency():
    try:
        configured = int(
            os.getenv("CHECK_CONCURRENCY", str(DEFAULT_CHECK_CONCURRENCY))
        )
    except ValueError:
        return DEFAULT_CHECK_CONCURRENCY
    return max(1, min(configured, 20))


@app.get("/")
async def root():
    """返回公开展示页面。"""
    return render_template("display.html")


@app.get("/admin", dependencies=[Depends(require_admin)])
async def admin():
    """返回后台管理页面。"""
    return render_template("admin.html")


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get("/api/sites")
async def list_sites():
    """获取所有站点状态。"""
    return get_site_statuses()


@app.post("/api/sites", dependencies=[Depends(require_admin)])
async def create_site(site: SiteInput):
    """添加新站点。"""
    try:
        name = normalize_site_name(site.name)
        url = normalize_url(site.url)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    try:
        site_id = add_site(name, url)
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail="这个网站已经在监控列表里了",
        ) from error

    result = await run_site_check_async({"id": site_id, "url": url})
    return {"success": True, "id": site_id, "check": result}


@app.get(
    "/api/sites/{site_id}/checks",
    dependencies=[Depends(require_admin)],
)
async def get_site_checks(site_id: int):
    """获取站点检查历史。"""
    if not get_site(site_id):
        raise HTTPException(status_code=404, detail="Site not found")
    return get_recent_checks(site_id, 100)


@app.post(
    "/api/sites/{site_id}/check",
    dependencies=[Depends(require_admin)],
)
async def manual_check(site_id: int):
    """手动触发单站检查。"""
    site = get_site(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return await run_site_check_async(site)


@app.get(
    "/api/check/{site_id}",
    dependencies=[Depends(require_admin)],
    deprecated=True,
)
async def legacy_manual_check(site_id: int):
    """兼容旧版 GET 检测入口。"""
    return await manual_check(site_id)


@app.post("/api/check-all", dependencies=[Depends(require_admin)])
async def check_all():
    """有限并发地检测全部站点。"""
    sites = get_sites()
    semaphore = asyncio.Semaphore(get_check_concurrency())

    async def check_one(site):
        async with semaphore:
            result = await run_site_check_async(site)
            return {"id": site["id"], "name": site["name"], **result}

    results = await asyncio.gather(*(check_one(site) for site in sites))
    return {"success": True, "count": len(results), "results": results}


@app.delete("/api/sites/{site_id}", dependencies=[Depends(require_admin)])
async def remove_site(site_id: int):
    """删除站点及其检测记录。"""
    if not delete_site(site_id):
        raise HTTPException(status_code=404, detail="Site not found")
    return {"success": True}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

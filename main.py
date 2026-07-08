from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel
import uvicorn
import os
import sqlite3
from urllib.parse import urlparse

from database import (
    init_db,
    add_site,
    delete_site,
    get_sites,
    get_latest_check,
    get_outages,
    get_recent_checks,
    get_recent_uptime,
    save_check,
)
from checker import check_site

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="网站状态监控", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

class SiteInput(BaseModel):
    name: str
    url: str

def normalize_url(url: str) -> str:
    cleaned = url.strip()
    if not cleaned:
        raise ValueError("请输入网站地址")

    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"

    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("请输入有效的 http 或 https 地址")

    return cleaned

def render_template(filename: str):
    html_path = os.path.join(TEMPLATE_DIR, filename)
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

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

def get_status_data(site):
    """获取站点的完整状态数据"""
    check = get_latest_check(site["id"])
    outages = get_outages(site["id"])
    uptime = get_recent_uptime(site["id"])
    
    return {
        "id": site["id"],
        "name": site["name"],
        "url": site["url"],
        "created_at": site["created_at"],
        "status": check["status"] if check else "unknown",
        "status_code": check["status_code"] if check else None,
        "response_time": check["response_time"] if check else None,
        "ssl_days_left": check["ssl_days_left"] if check else None,
        "error_msg": check["error_msg"] if check else None,
        "checked_at": check["checked_at"] if check else None,
        "uptime": uptime,
        "outages": outages
    }

@app.get("/")
async def root():
    """返回公开展示页面"""
    return render_template("display.html")

@app.get("/admin")
async def admin():
    """返回后台管理页面"""
    return render_template("admin.html")

@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)

@app.get("/api/sites")
async def list_sites():
    """获取所有站点状态"""
    sites = get_sites()
    return [get_status_data(site) for site in sites]

@app.post("/api/sites")
async def create_site(site: SiteInput):
    """添加新站点"""
    try:
        name = site.name.strip()
        if not name:
            raise ValueError("请输入网站名称")

        url = normalize_url(site.url)
        site_id = add_site(name, url)

        # 添加后立即检查一次
        result = await run_site_check_async({"id": site_id, "url": url})
        return {"success": True, "id": site_id, "check": result}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="这个网站已经在监控列表里了")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/sites/{site_id}/checks")
async def get_site_checks(site_id: int):
    """获取站点检查历史"""
    if not any(site["id"] == site_id for site in get_sites()):
        raise HTTPException(status_code=404, detail="Site not found")
    return get_recent_checks(site_id, 100)

@app.post("/api/sites/{site_id}/check")
async def manual_check(site_id: int):
    """手动触发单站检查"""
    sites = get_sites()
    site = next((s for s in sites if s["id"] == site_id), None)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    
    return await run_site_check_async(site)

@app.get("/api/check/{site_id}")
async def legacy_manual_check(site_id: int):
    """兼容旧版 GET 检测入口"""
    return await manual_check(site_id)

@app.post("/api/check-all")
async def check_all():
    """手动触发全部站点检测"""
    results = []
    for site in get_sites():
        result = await run_site_check_async(site)
        results.append({"id": site["id"], "name": site["name"], **result})
    return {"success": True, "count": len(results), "results": results}

@app.delete("/api/sites/{site_id}")
async def remove_site(site_id: int):
    """删除站点及其检测记录"""
    if not delete_site(site_id):
        raise HTTPException(status_code=404, detail="Site not found")
    return {"success": True}

@app.get("/api/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    # 确保模板目录存在
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    os.makedirs(STATIC_DIR, exist_ok=True)
    uvicorn.run(app, host="0.0.0.0", port=8000)

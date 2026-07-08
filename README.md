# Website Status Monitor

一个轻量的网站状态监控面板，使用 FastAPI、SQLite 和原生 HTML/CSS/JavaScript 构建。

## 功能

- 公开展示页 `/`：展示监控站点、在线数量、异常数量、SSL 预警、平均响应时间和站点状态卡片。
- 后台管理页 `/admin`：添加站点、删除站点、手动检测、批量检测、查看检测历史、设置自动刷新间隔。
- HTTP 状态检测：响应码小于 400 视为在线，否则视为异常。
- SSL 有效期检测：HTTPS 站点会显示证书剩余天数。
- 宕机记录：自动记录异常开始和恢复时间。
- 最近可用率：基于最近检测记录计算站点可用率。

## 本地运行

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

访问：

- 展示页：http://127.0.0.1:8000/
- 后台页：http://127.0.0.1:8000/admin

## 定时检测

项目提供了 `scheduler.py`，可配合 cron 或 systemd timer 定时执行。

示例 cron：

```cron
*/10 * * * * cd /path/to/website-status-monitor && .venv/bin/python scheduler.py
```

## 数据库

默认使用项目目录下的 `monitor.db`。也可以通过环境变量指定路径：

```bash
MONITOR_DB_PATH=/var/lib/site-monitor/monitor.db .venv/bin/python main.py
```

## 部署建议

- 使用 nginx 或其他反向代理转发到 `uvicorn`。
- 生产环境建议为 `/admin` 增加鉴权或放在内网访问。
- 不要提交运行时数据库、虚拟环境和 Python 缓存文件。

## 开源协议

MIT License

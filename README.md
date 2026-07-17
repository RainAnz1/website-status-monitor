# Website Status Monitor

一个轻量的网站状态监控面板，使用 FastAPI、SQLite 和原生 HTML/CSS/JavaScript 构建。

## 功能

- 公开展示页 `/`：展示监控站点、在线数量、异常数量、SSL 预警、响应时间和最近可用率。
- 后台管理页 `/admin`：添加、删除、手动检测、批量检测、查看历史并设置浏览器自动刷新间隔。
- HTTP 与 SSL 检测：响应码小于 400 视为在线，HTTPS 站点同时显示证书剩余天数。
- 宕机记录：记录异常开始、恢复时间和持续时长。
- 安全边界：后台支持可选密码保护，默认拒绝服务器访问本机、私网和保留网络目标。
- 批量状态查询与有限并发检测，适合直接部署到小型服务器。

## 运行要求

- Python 3.10 或更高版本

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

访问地址：

- 展示页：http://127.0.0.1:8000/
- 后台页：http://127.0.0.1:8000/admin

## 后台保护

本地未设置 `ADMIN_PASSWORD` 时，后台保持直接访问。部署到公网时必须配置后台账号密码：

```bash
ADMIN_USERNAME=admin \
ADMIN_PASSWORD='使用你自己的高强度密码' \
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --proxy-headers
```

浏览器访问 `/admin` 时会显示账号密码验证窗口。添加、删除、检测和历史记录接口使用同一组凭据保护。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ADMIN_USERNAME` | `admin` | 后台用户名，仅在设置密码后生效 |
| `ADMIN_PASSWORD` | 空 | 后台密码；为空时不启用鉴权，仅适合本地测试 |
| `MONITOR_DB_PATH` | 项目目录下的 `monitor.db` | SQLite 数据库路径 |
| `CHECK_CONCURRENCY` | `5` | “检测全部”的并发数，允许 1 至 20 |
| `ALLOW_PRIVATE_TARGETS` | `false` | 设为 `true` 后允许监控本机和私网地址 |

开启 `ALLOW_PRIVATE_TARGETS` 会扩大服务端请求伪造风险，只应在后台已保护且确实需要监控内网服务时使用。

## 定时检测

`scheduler.py` 每次运行会初始化数据库并执行一轮检测，适合由 cron 或 systemd timer 定时调用。

```cron
*/10 * * * * cd /path/to/website-status-monitor && .venv/bin/python scheduler.py
```

脚本检测失败时会返回非零退出码，便于服务器任务系统记录失败。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -v
node --check static/app.js
```

## 部署建议

- 使用 nginx、Caddy 或其他反向代理提供 HTTPS，并只把 Uvicorn 监听在 `127.0.0.1`。
- 生产环境配置 `ADMIN_PASSWORD`，不要把密码、`.env`、数据库或私钥提交到 Git。
- 为数据库目录配置持久化存储和定期备份。
- 定时检测使用 cron 或 systemd timer，不依赖浏览器页面保持打开。

## 开源协议

MIT License

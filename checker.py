import requests
import urllib3
import ssl
import socket
import time
from datetime import datetime
from urllib.parse import urlparse

urllib3.disable_warnings()

def check_site(url: str) -> dict:
    """检查网站健康状态"""
    if "://" not in url:
        url = f"https://{url}"

    result = {
        "status": "down",
        "status_code": None,
        "response_time": None,
        "ssl_days_left": None,
        "error_msg": None
    }
    
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    
    start_time = time.perf_counter()
    
    try:
        # 设置超时
        timeout = 10
        
        # 发起请求。监控服务应直连目标站点，避免被服务器环境里的代理变量影响。
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(
                url,
                verify=True,
                timeout=timeout,
                headers={"User-Agent": "SiteMonitor/1.0"},
            )
        
        delta = (time.perf_counter() - start_time) * 1000  # 毫秒
        
        result["status_code"] = response.status_code
        result["response_time"] = round(delta, 2)
        result["status"] = "up" if response.status_code < 400 else "down"
        if result["status"] == "down":
            result["error_msg"] = f"HTTP状态异常: {response.status_code}"
        
        # 如果是HTTPS，检查SSL
        if parsed.scheme == "https" and host:
            result["ssl_days_left"] = get_ssl_days_left(host, port)
        
    except requests.exceptions.SSLError as e:
        result["error_msg"] = f"SSL错误: {str(e)[:100]}"
        # 仍然尝试获取SSL信息
        if host:
            result["ssl_days_left"] = get_ssl_days_left(host, 443)
    except requests.exceptions.ConnectionError as e:
        result["error_msg"] = f"连接失败: {str(e)[:100]}"
    except requests.exceptions.Timeout as e:
        result["error_msg"] = f"超时: {str(e)[:100]}"
    except Exception as e:
        result["error_msg"] = f"错误: {str(e)[:100]}"
    
    return result

def get_ssl_days_left(host: str, port: int) -> int:
    """检查SSL证书到期时间，返回剩余天数"""
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                # cert 字典的 key 是 'notAfter' (驼峰)
                not_after = cert.get("notAfter") or cert.get("not_after", "")
                # 解析日期格式: "Jun 22 00:00:00 2026 GMT"
                expire_date = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
                remaining = (expire_date - datetime.now()).days
                return remaining
    except Exception as e:
        # 记录错误但不崩溃
        print(f"SSL检查失败 {host}:{port} - {e}")
        return None

def check_all_sites():
    """检查所有已添加的网站"""
    from database import get_sites, save_check
    
    sites = get_sites()
    for site in sites:
        result = check_site(site["url"])
        save_check(site["id"], result["status"], result.get("status_code"),
                   result.get("response_time"), result.get("ssl_days_left"),
                   result.get("error_msg"))
        print(f"[{site['name']}] {result['status']} - {result.get('response_time', 'N/A')}ms")

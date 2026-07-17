import ipaddress
import logging
import os
import socket
import ssl
import time
from urllib.parse import urljoin, urlparse

import requests


LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT = (5, 10)
MAX_REDIRECTS = 5
USER_AGENT = "WebsiteStatusMonitor/1.0"
TRUE_VALUES = {"1", "true", "yes", "on"}


class TargetNotAllowedError(ValueError):
    pass


def private_targets_allowed():
    return os.getenv("ALLOW_PRIVATE_TARGETS", "").strip().lower() in TRUE_VALUES


def validate_target_url(url: str):
    """阻止监控请求访问服务器本机、私网和保留地址。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise TargetNotAllowedError("仅允许监控有效的 http 或 https 地址")
    if parsed.username is not None or parsed.password is not None:
        raise TargetNotAllowedError("目标地址不能包含账号信息")

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as error:
        raise TargetNotAllowedError("目标地址端口无效") from error

    if private_targets_allowed():
        return parsed

    try:
        address_info = socket.getaddrinfo(
            parsed.hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as error:
        raise requests.exceptions.ConnectionError(
            f"域名解析失败: {parsed.hostname}"
        ) from error

    if not address_info:
        raise requests.exceptions.ConnectionError(
            f"域名解析失败: {parsed.hostname}"
        )

    for info in address_info:
        address = info[4][0].split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as error:
            raise TargetNotAllowedError("目标地址解析结果无效") from error
        if not ip.is_global:
            raise TargetNotAllowedError(
                "目标地址指向本机、私网或保留网络，已拒绝访问"
            )

    return parsed


def request_with_safe_redirects(session, url: str):
    """逐跳校验重定向目标，最终响应由调用方负责关闭。"""
    current_url = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        validate_target_url(current_url)
        response = session.get(
            current_url,
            allow_redirects=False,
            stream=True,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )

        if not (response.is_redirect or response.is_permanent_redirect):
            return response, current_url

        location = response.headers.get("location")
        if not location:
            return response, current_url

        next_url = urljoin(current_url, location)
        response.close()
        if redirect_count >= MAX_REDIRECTS:
            raise requests.exceptions.TooManyRedirects(
                f"重定向超过 {MAX_REDIRECTS} 次"
            )
        current_url = next_url

    raise requests.exceptions.TooManyRedirects(
        f"重定向超过 {MAX_REDIRECTS} 次"
    )


def check_site(url: str) -> dict:
    """检查网站健康状态。"""
    if "://" not in url:
        url = f"https://{url}"

    result = {
        "status": "down",
        "status_code": None,
        "response_time": None,
        "ssl_days_left": None,
        "error_msg": None,
    }

    start_time = time.perf_counter()
    try:
        with requests.Session() as session:
            # 监控服务应直连目标，避免服务器环境中的代理和 .netrc 影响请求。
            session.trust_env = False
            response, final_url = request_with_safe_redirects(session, url)
            try:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                result["status_code"] = response.status_code
                result["response_time"] = round(elapsed_ms, 2)
                result["status"] = "up" if response.status_code < 400 else "down"
                if result["status"] == "down":
                    result["error_msg"] = f"HTTP 状态异常: {response.status_code}"
            finally:
                response.close()

        parsed = urlparse(final_url)
        if parsed.scheme == "https" and parsed.hostname:
            result["ssl_days_left"] = get_ssl_days_left(
                parsed.hostname,
                parsed.port or 443,
            )
    except TargetNotAllowedError as error:
        result["error_msg"] = f"目标地址不允许: {error}"
    except requests.exceptions.SSLError as error:
        result["error_msg"] = f"SSL 错误: {str(error)[:100]}"
    except requests.exceptions.ConnectionError as error:
        result["error_msg"] = f"连接失败: {str(error)[:100]}"
    except requests.exceptions.Timeout as error:
        result["error_msg"] = f"请求超时: {str(error)[:100]}"
    except requests.exceptions.TooManyRedirects as error:
        result["error_msg"] = str(error)
    except requests.exceptions.RequestException as error:
        result["error_msg"] = f"请求失败: {str(error)[:100]}"
    except Exception as error:
        LOGGER.exception("站点检测出现未预期错误")
        result["error_msg"] = f"检测失败: {str(error)[:100]}"

    return result


def get_ssl_days_left(host: str, port: int):
    """检查 SSL 证书到期时间，返回剩余整天数。"""
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=host) as ssl_socket:
                certificate = ssl_socket.getpeercert()
                not_after = certificate.get("notAfter")
                if not not_after:
                    raise ValueError("证书缺少到期时间")
                expires_at = ssl.cert_time_to_seconds(not_after)
                return int((expires_at - time.time()) // 86400)
    except Exception as error:
        LOGGER.warning("SSL 检查失败 %s:%s - %s", host, port, error)
        return None


def check_all_sites():
    """检查所有已添加的网站。"""
    from database import get_sites, save_check

    for site in get_sites():
        result = check_site(site["url"])
        save_check(
            site["id"],
            result["status"],
            result.get("status_code"),
            result.get("response_time"),
            result.get("ssl_days_left"),
            result.get("error_msg"),
        )
        print(
            f"[{site['name']}] {result['status']} - "
            f"{result.get('response_time', 'N/A')}ms"
        )

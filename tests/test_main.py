import asyncio
import base64
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials

import main


def request_app(path, headers=None):
    response_messages = []
    request_sent = False

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        response_messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": headers or [],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }
    asyncio.run(main.app(scope, receive, send))

    start = next(
        message for message in response_messages if message["type"] == "http.response.start"
    )
    return {
        "status": start["status"],
        "headers": {
            key.decode("latin-1"): value.decode("latin-1")
            for key, value in start["headers"]
        },
    }


class SiteInputValidationTests(unittest.TestCase):
    def test_normalize_url_adds_https_for_bare_domain(self):
        self.assertEqual(
            main.normalize_url("  example.com/status  "),
            "https://example.com/status",
        )

    def test_normalize_url_rejects_credentials(self):
        with self.assertRaisesRegex(ValueError, "账号信息"):
            main.normalize_url("https://user:secret@example.com")

    def test_normalize_url_rejects_invalid_port(self):
        with self.assertRaisesRegex(ValueError, "端口"):
            main.normalize_url("https://example.com:not-a-port")

    def test_normalize_url_rejects_control_characters(self):
        with self.assertRaisesRegex(ValueError, "有效"):
            main.normalize_url("https://example.com/\nadmin")

    def test_normalize_site_name_trims_and_limits_input(self):
        self.assertEqual(main.normalize_site_name("  公司官网  "), "公司官网")

        with self.assertRaisesRegex(ValueError, "不能超过"):
            main.normalize_site_name("x" * 121)


class AdminAuthenticationTests(unittest.TestCase):
    def test_admin_auth_is_disabled_without_password(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(main.require_admin(None))

    def test_admin_auth_rejects_missing_credentials_when_configured(self):
        with patch.dict(
            os.environ,
            {"ADMIN_USERNAME": "owner", "ADMIN_PASSWORD": "correct-password"},
            clear=True,
        ):
            with self.assertRaises(HTTPException) as raised:
                main.require_admin(None)

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(
            raised.exception.headers,
            {"WWW-Authenticate": "Basic"},
        )

    def test_admin_auth_accepts_matching_credentials(self):
        credentials = HTTPBasicCredentials(
            username="owner",
            password="correct-password",
        )
        with patch.dict(
            os.environ,
            {"ADMIN_USERNAME": "owner", "ADMIN_PASSWORD": "correct-password"},
            clear=True,
        ):
            self.assertIsNone(main.require_admin(credentials))


class RouteSecurityTests(unittest.TestCase):
    def test_public_page_has_strict_security_headers(self):
        with patch.dict(os.environ, {}, clear=True):
            response = request_app("/")

        self.assertEqual(response["status"], 200)
        self.assertEqual(response["headers"]["x-frame-options"], "DENY")
        self.assertIn("script-src 'self'", response["headers"]["content-security-policy"])
        self.assertNotIn("unsafe-inline", response["headers"]["content-security-policy"])

    def test_admin_route_requires_configured_credentials(self):
        token = base64.b64encode(b"owner:correct-password")
        authorization = [(b"authorization", b"Basic " + token)]
        environment = {
            "ADMIN_USERNAME": "owner",
            "ADMIN_PASSWORD": "correct-password",
        }

        with patch.dict(os.environ, environment, clear=True):
            denied = request_app("/admin")
            allowed = request_app("/admin", authorization)

        self.assertEqual(denied["status"], 401)
        self.assertEqual(allowed["status"], 200)

    def test_api_documentation_is_not_public(self):
        response = request_app("/docs")
        self.assertEqual(response["status"], 404)


if __name__ == "__main__":
    unittest.main()

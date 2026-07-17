import os
import socket
import unittest
from unittest.mock import patch

import checker


class FakeRedirectResponse:
    status_code = 302
    headers = {"location": "http://127.0.0.1:8000/private"}
    is_redirect = True
    is_permanent_redirect = False

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class TargetValidationTests(unittest.TestCase):
    def test_rejects_credentials_in_redirect_targets(self):
        with self.assertRaisesRegex(checker.TargetNotAllowedError, "账号信息"):
            checker.validate_target_url("https://user:secret@example.com")

    def test_rejects_loopback_address_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(checker.TargetNotAllowedError, "私网"):
                checker.validate_target_url("http://127.0.0.1:8000")

    def test_rejects_domain_resolving_to_private_address(self):
        private_result = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443)),
        ]
        with patch.dict(os.environ, {}, clear=True), patch(
            "checker.socket.getaddrinfo",
            return_value=private_result,
        ):
            with self.assertRaisesRegex(checker.TargetNotAllowedError, "私网"):
                checker.validate_target_url("https://internal.example.com")

    def test_accepts_domain_resolving_only_to_public_addresses(self):
        public_result = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ]
        with patch.dict(os.environ, {}, clear=True), patch(
            "checker.socket.getaddrinfo",
            return_value=public_result,
        ):
            checker.validate_target_url("https://example.com")

    def test_private_targets_can_be_enabled_explicitly(self):
        with patch.dict(
            os.environ,
            {"ALLOW_PRIVATE_TARGETS": "true"},
            clear=True,
        ):
            checker.validate_target_url("http://127.0.0.1:8000")

    def test_redirect_to_private_address_is_rejected_before_second_request(self):
        response = FakeRedirectResponse()
        session = FakeSession(response)

        def resolve(host, port, type):
            address = "93.184.216.34" if host == "example.com" else "127.0.0.1"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

        with patch.dict(os.environ, {}, clear=True), patch(
            "checker.socket.getaddrinfo",
            side_effect=resolve,
        ):
            with self.assertRaises(checker.TargetNotAllowedError):
                checker.request_with_safe_redirects(
                    session,
                    "http://example.com",
                )

        self.assertTrue(response.closed)
        self.assertEqual(len(session.calls), 1)
        self.assertTrue(session.calls[0][1]["stream"])
        self.assertFalse(session.calls[0][1]["allow_redirects"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import socket
from unittest.mock import patch

import url_validation


def test_is_safe_url_rejects_blocked_hostname_without_dns_lookup() -> None:
    with patch.object(url_validation, "_resolve_hostname") as resolve:
        assert url_validation.is_safe_url("http://localhost/private") is False
    resolve.assert_not_called()


def test_is_safe_url_rejects_non_http_scheme() -> None:
    assert url_validation.is_safe_url("file:///etc/passwd") is False


def test_is_safe_url_rejects_dns_failure() -> None:
    with patch.object(
        url_validation.socket,
        "getaddrinfo",
        side_effect=socket.gaierror("not found"),
    ):
        assert url_validation.is_safe_url("https://missing.example.invalid/doc.pdf") is False


def test_is_safe_url_rejects_public_hostname_resolving_to_private_ip() -> None:
    with patch.object(
        url_validation.socket,
        "getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", 443))],
    ):
        assert url_validation.is_safe_url("https://example.com/doc.pdf") is False


def test_is_safe_url_accepts_public_hostname() -> None:
    with patch.object(
        url_validation.socket,
        "getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    ):
        assert url_validation.is_safe_url("https://example.com/doc.pdf") is True

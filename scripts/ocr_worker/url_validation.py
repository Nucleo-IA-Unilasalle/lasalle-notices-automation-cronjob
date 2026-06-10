"""URL validation utilities to prevent SSRF attacks.

This module provides functions to validate URLs before making HTTP requests,
blocking requests to internal/private networks that could be exploited
via Server-Side Request Forgery (SSRF) attacks.
"""

import ipaddress
import logging
import socket
from typing import List
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

BLOCKED_IP_NETWORKS: List[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
    ipaddress.ip_network("::/128"),
]

BLOCKED_HOSTNAMES = frozenset([
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
])

ALLOWED_SCHEMES = frozenset(["http", "https"])


def _is_ip_blocked(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    for network in BLOCKED_IP_NETWORKS:
        if ip in network:
            return True
    return False


def _is_valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _normalize_hostname(hostname: str) -> str:
    if hostname.endswith("."):
        hostname = hostname[:-1]
    return hostname


def _normalize_ip_address(ip_str: str) -> str:
    try:
        ip = ipaddress.ip_address(ip_str)
        if isinstance(ip, ipaddress.IPv6Address):
            ipv4_mapped = ip.ipv4_mapped
            if ipv4_mapped is not None:
                return str(ipv4_mapped)
        return ip_str
    except ValueError:
        return ip_str


def _resolve_hostname(hostname: str) -> List[str]:
    addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
    ips = set()
    for family, _, _, _, sockaddr in addr_info:
        ip = sockaddr[0]
        ips.add(ip)
    return list(ips)


def _validate_url_components(url: str) -> tuple[bool, str, str]:
    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, "", f"Failed to parse URL: {e}"

    if not parsed.scheme:
        return False, "", "URL has no scheme"

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return False, "", f"Scheme '{parsed.scheme}' not allowed, must be http or https"

    if not parsed.hostname:
        return False, "", "URL has no hostname"

    hostname = parsed.hostname.lower()
    hostname = _normalize_hostname(hostname)

    if hostname in BLOCKED_HOSTNAMES:
        return False, "", f"Hostname '{hostname}' is blocked"

    if hostname.rstrip(".") in BLOCKED_HOSTNAMES:
        return False, "", f"Hostname '{hostname}' is blocked"

    if hostname.endswith(".local") or hostname.endswith(".internal"):
        return False, "", f"Hostname '{hostname}' has blocked suffix"

    return True, hostname, ""


def is_safe_url(url: str) -> bool:
    """Validate that a URL is safe to fetch (not targeting internal resources)."""
    is_valid, hostname, error = _validate_url_components(url)
    if not is_valid:
        logger.warning("URL validation failed for %s: %s", url, error)
        return False

    normalized_hostname = _normalize_ip_address(hostname)

    if _is_valid_ip(normalized_hostname):
        if _is_ip_blocked(normalized_hostname):
            logger.warning("URL validation failed for %s: IP address is in blocked range", url)
            return False
        return True

    try:
        resolved_ips = _resolve_hostname(hostname)
    except socket.gaierror as e:
        logger.warning("URL validation failed for %s: DNS resolution failed: %s", url, e)
        return False
    except Exception as e:
        logger.warning("URL validation failed for %s: Unexpected error during DNS resolution: %s", url, e)
        return False

    if not resolved_ips:
        logger.warning("URL validation failed for %s: No IP addresses resolved", url)
        return False

    for ip in resolved_ips:
        normalized_ip = _normalize_ip_address(ip)
        if _is_ip_blocked(normalized_ip):
            logger.warning(
                "URL validation failed for %s: Resolved IP %s is in blocked range",
                url, ip
            )
            return False

    return True

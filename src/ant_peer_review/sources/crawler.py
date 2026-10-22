"""Safe HTTP fetcher for review targets.

- Only http/https, no credentials in the URL.
- Every hop (first request and each redirect) resolves the host and refuses
  any non-global address (private, loopback, link-local, metadata, multicast…).
- The connection goes to the IP that was checked (pinned), so DNS rebinding
  between check and connect cannot reach an internal host.
- Byte cap, timeout, content-type allowlist, robots.txt, per-site profiles.
"""
from __future__ import annotations

import http.client
import time
import ipaddress
import socket
import ssl
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urljoin, urlsplit

DEFAULT_UA = "ant-peer-review/0.1 (+article review; respects robots.txt)"
ALLOWED_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "text/markdown",
                 "application/pdf", "application/rss+xml", "application/atom+xml",
                 "application/xml", "text/xml", "application/rdf+xml")
MAX_REDIRECTS = 5
DEFAULT_MIN_INTERVAL = 1.0   # seconds between requests to one host (politeness)
_V6_EMBEDDED_V4 = [ipaddress.ip_network(n) for n in ("64:ff9b::/96", "64:ff9b:1::/48", "::/96")]


class FetchError(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    hops: list[str] = field(default_factory=list)


Resolver = Callable[[str, int], list[str]]


def system_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise FetchError("dns", str(e))
    return sorted({i[4][0] for i in infos})


def address_allowed(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        elif any(addr in net for net in _V6_EMBEDDED_V4):
            return False  # NAT64 / IPv4-compatible forms can reach internal IPv4
    return addr.is_global and not addr.is_multicast


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, ip, **kw):
        super().__init__(host, **kw)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, ip, **kw):
        super().__init__(host, context=ssl.create_default_context(), **kw)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class Crawler:
    def __init__(self, *, resolver: Resolver = system_resolver, max_bytes: int = 10_000_000,
                 timeout: float = 20.0, site_profiles: dict | None = None,
                 respect_robots: bool = True, deadline: float = 120.0,
                 min_interval: float | None = None,
                 allowed_types: tuple[str, ...] = ALLOWED_TYPES,
                 host_intervals: dict[str, float] | None = None,
                 _allow_hosts_for_tests: frozenset[str] = frozenset()):
        self.resolver = resolver
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.profiles = site_profiles or {}
        self.respect_robots = respect_robots
        self.deadline = deadline
        self.min_interval = DEFAULT_MIN_INTERVAL if min_interval is None else min_interval
        self.allowed_types = allowed_types
        self.host_intervals = host_intervals or {}
        self._last_hit: dict[str, float] = {}
        self._test_hosts = _allow_hosts_for_tests
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    # -- public -------------------------------------------------------------
    def fetch(self, url: str) -> FetchResult:
        profile = self.profile_for(url)
        if profile.get("blocked"):
            raise FetchError("site_profile_blocked", profile.get("note", ""))
        ua = profile.get("user_agent") or DEFAULT_UA
        if self.respect_robots and not self._robots_ok(url, ua):
            raise FetchError("robots", url)
        hops: list[str] = []
        current = url
        until = time.monotonic() + self.deadline
        for _ in range(MAX_REDIRECTS + 1):
            if hops and self.respect_robots and _origin(current) != _origin(url) \
                    and not self._robots_ok(current, ua):
                raise FetchError("robots", current)
            status, headers, body = self._request(current, ua, until)
            hops.append(current)
            if status in (301, 302, 303, 307, 308):
                loc = headers.get("location")
                if not loc:
                    raise FetchError("bad_redirect", current)
                current = urljoin(current, loc)
                continue
            if status >= 400:
                raise FetchError("http_status", str(status))
            ctype = headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype not in self.allowed_types:
                raise FetchError("content_type", ctype or "missing")
            return FetchResult(url, current, status, ctype, body, hops)
        raise FetchError("too_many_redirects", url)

    def profile_for(self, url: str) -> dict:
        host = (urlsplit(url).hostname or "").lower()
        while host:
            if host in self.profiles:
                return self.profiles[host]
            host = host.partition(".")[2]
        return {}

    # -- internals ----------------------------------------------------------
    def _target(self, url: str) -> tuple[str, str, int, str, str]:
        try:
            parts = urlsplit(url)
            port_ = parts.port
        except ValueError as e:
            raise FetchError("bad_url", str(e))
        if parts.scheme not in ("http", "https"):
            raise FetchError("scheme", parts.scheme)
        if parts.username or parts.password:
            raise FetchError("credentials_in_url")
        host = parts.hostname
        if not host:
            raise FetchError("no_host")
        port = port_ or (443 if parts.scheme == "https" else 80)
        ips = self.resolver(host, port)
        if host in self._test_hosts:
            allowed = ips
        else:
            if not ips or not all(address_allowed(ip) for ip in ips):
                raise FetchError("blocked_address", host)
            allowed = ips
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        return parts.scheme, host, port, allowed[0], path

    def _request(self, url: str, ua: str, until: float | None = None) -> tuple[int, dict, bytes]:
        until = until or time.monotonic() + self.deadline
        scheme, host, port, ip, path = self._target(url)
        interval = max(self.min_interval, self.host_intervals.get(host, 0.0))
        wait = self._last_hit.get(host, -1e9) + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.monotonic()
        cls = _PinnedHTTPS if scheme == "https" else _PinnedHTTP
        conn = cls(host, ip, port=port, timeout=self.timeout)
        try:
            conn.request("GET", path, headers={"User-Agent": ua, "Accept": ", ".join(self.allowed_types),
                                               "Accept-Encoding": "identity"})
            resp = conn.getresponse()
            headers = {k.lower(): v for k, v in resp.getheaders()}
            length = headers.get("content-length")
            if length and length.isdigit() and int(length) > self.max_bytes:
                raise FetchError("too_large", length)
            chunks, size = [], 0
            while resp.status < 300:
                if time.monotonic() > until:
                    raise FetchError("timeout", "total deadline exceeded")
                chunk = resp.read1(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > self.max_bytes:
                    raise FetchError("too_large", f">{self.max_bytes}")
                chunks.append(chunk)
            body = b"".join(chunks)
            return resp.status, headers, body
        except socket.timeout:
            raise FetchError("timeout", url)
        except (OSError, http.client.HTTPException) as e:
            if isinstance(e, FetchError):
                raise
            raise FetchError("network", str(e)[:200])
        finally:
            conn.close()

    def _robots_ok(self, url: str, ua: str) -> bool:
        origin = _origin(url)
        if origin not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                status, _, body = self._request(origin + "/robots.txt", ua)
                if status == 200:
                    rp.parse(body.decode("utf-8", "replace").splitlines())
                    self._robots[origin] = rp
                else:
                    self._robots[origin] = None
            except FetchError as e:
                if e.reason == "blocked_address":
                    raise
                self._robots[origin] = None
        rp = self._robots[origin]
        return True if rp is None else rp.can_fetch(ua, url)


def _origin(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError as e:
        raise FetchError("bad_url", str(e))
    return f"{parts.scheme}://{parts.netloc}"

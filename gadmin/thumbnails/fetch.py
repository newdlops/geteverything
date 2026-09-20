"""Small public HTTP downloads with validated, pinned DNS and redirect limits."""
from dataclasses import dataclass
from html import unescape
import ipaddress
import re
import socket
import time
from urllib.parse import parse_qs, quote, urljoin, urlsplit, urlunsplit

import certifi
import urllib3


class ThumbnailError(Exception):
    pass


def normalize_url(value, base=""):
    if not isinstance(value, str) or len(value) > 4096:
        return ""
    value = unescape(value).strip()
    if not value or any(ord(char) < 32 for char in value):
        return ""
    try:
        parsed = urlsplit(urljoin(base, value))
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.port not in (None, 80, 443)):
            return ""
        host = parsed.hostname.encode('idna').decode('ascii')
        if len(host) > 253 or any(char.isspace() for char in host):
            return ""
        if ':' not in host and not re.fullmatch(r'[a-zA-Z0-9.-]+', host):
            return ""
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))
    except ValueError:
        return ""


def product_url(value):
    value = normalize_url(value)
    for _ in range(3):
        query = parse_qs(urlsplit(value).query)
        target = next((normalize_url(query[key][0]) for key in
                       ("url", "target", "redirect", "redirect_url", "landingUrl", "u")
                       if key in query and normalize_url(query[key][0])), "")
        if not target or target == value:
            break
        value = target
    return value


def public_address(host, port):
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(record[4][0] for record in records))
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise ThumbnailError("non_public_address")
        return min(addresses, key=lambda address: ipaddress.ip_address(address).version)
    except (socket.gaierror, ValueError) as exc:
        raise ThumbnailError("dns_failed") from exc


@dataclass
class Download:
    url: str
    body: bytes
    content_type: str


def fetch(url, *, limit, deadline, referer="", stop_at=None):
    for redirect in range(4):
        url = normalize_url(url)
        remaining = deadline - time.monotonic()
        if not url:
            raise ThumbnailError("invalid_url")
        if remaining <= 0:
            raise ThumbnailError("deadline")
        if stop_at is not None and stop_at(url):
            return Download(url, b'', '')
        parsed = urlsplit(url)
        host = parsed.hostname.encode("idna").decode("ascii")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        address = public_address(host, port)
        options = {"timeout": urllib3.Timeout(connect=min(3, remaining), read=min(5, remaining)),
                   "maxsize": 1, "retries": False}
        if parsed.scheme == "https":
            pool = urllib3.HTTPSConnectionPool(address, port, server_hostname=host,
                                               assert_hostname=host, cert_reqs="CERT_REQUIRED",
                                               ca_certs=certifi.where(), **options)
        else:
            pool = urllib3.HTTPConnectionPool(address, port, **options)
        headers = {"Host": parsed.netloc, "Accept-Encoding": "identity",
                   "User-Agent": "Mozilla/5.0 (compatible; GetEverythingThumbnail/1.0)",
                   "Accept": "text/html,application/xhtml+xml,image/avif,image/webp,image/*;q=0.9,*/*;q=0.5",
                   "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5"}
        if normalize_url(referer):
            ref = urlsplit(referer)
            headers["Referer"] = urlunsplit((ref.scheme, ref.netloc, ref.path, "", ""))
        response = None
        try:
            target = quote(urlunsplit(("", "", parsed.path, parsed.query, "")), safe="/%?=&:+,;@!$'()*~[]")
            response = pool.request("GET", target, headers=headers, redirect=False,
                                    retries=False, preload_content=False, decode_content=True)
            if response.status in (301, 302, 303, 307, 308):
                url = normalize_url(response.headers.get("Location", ""), url)
                continue
            if response.status != 200:
                raise ThumbnailError(f"http_{response.status}")
            size = response.headers.get("Content-Length", "")
            if size.isdigit() and int(size) > limit:
                raise ThumbnailError("download_too_large")
            data = bytearray()
            while True:
                if time.monotonic() >= deadline:
                    raise ThumbnailError("deadline")
                chunk = response.read(min(65536, limit + 1 - len(data)), decode_content=True)
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > limit:
                    raise ThumbnailError("download_too_large")
            return Download(url, bytes(data), response.headers.get("Content-Type", ""))
        except (urllib3.exceptions.HTTPError, OSError) as exc:
            raise ThumbnailError("network_failed") from exc
        finally:
            if response is not None:
                response.close()
            pool.close()
    raise ThumbnailError("too_many_redirects")


def html_text(download):
    charset = re.search(r"charset=[\"']?([\w-]+)", download.content_type, re.I)
    encoding = charset.group(1) if charset else "utf-8"
    try:
        return download.body.decode(encoding, "replace")
    except LookupError:
        return download.body.decode("utf-8", "replace")

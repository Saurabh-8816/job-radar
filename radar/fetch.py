"""Polite HTTP client: retries, timeouts, size limits, bounded concurrency.

Some Indian government sites serve broken certificate chains, or still need TLS
legacy renegotiation (e.g. MPESB). These are public, read-only notice pages, so
on an SSL error we retry once without verification (and with legacy TLS allowed)
and flag the response as `insecure` instead of losing the source.

Several sites (UPSC, NIC, SECL) answer 403 to any user-agent that looks like a
bot, so requests carry ordinary browser headers. Politeness comes from volume
instead: one request per page every few hours.
"""

import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests
import urllib3
from requests.adapters import HTTPAdapter

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
}

_local = threading.local()


class _LegacyTLSAdapter(HTTPAdapter):
    """Allows legacy renegotiation and skips verification: last resort for old servers."""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        try:
            ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        except ssl.SSLError:
            pass
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


class TooLarge(Exception):
    pass


@dataclass
class Response:
    url: str
    ok: bool
    status: int | None = None
    text: str = ""
    content: bytes = b""
    content_type: str = ""
    error: str | None = None
    insecure: bool = False
    elapsed: float = 0.0


def _session(legacy: bool = False) -> requests.Session:
    attr = "legacy_session" if legacy else "session"
    s = getattr(_local, attr, None)
    if s is None:
        s = requests.Session()
        s.headers.update(HEADERS)
        if legacy:
            s.mount("https://", _LegacyTLSAdapter())
        setattr(_local, attr, s)
    return s


class TooSlow(Exception):
    pass


def _read(resp: requests.Response, max_bytes: int | None, deadline: float) -> bytes:
    """requests' timeout only bounds the gap between chunks, so a server that drip-feeds
    a page can hold a connection for minutes. `deadline` caps the whole download."""
    chunks, total = [], 0
    for chunk in resp.iter_content(64 * 1024):
        total += len(chunk)
        if max_bytes and total > max_bytes:
            raise TooLarge(f"larger than {max_bytes // 1_000_000} MB")
        if time.monotonic() > deadline:
            raise TooSlow("download too slow")
        chunks.append(chunk)
    return b"".join(chunks)


def _decode(data: bytes, resp: requests.Response) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode(resp.encoding or "latin-1", errors="replace")


def get(url: str, *, timeout: float = 20, retries: int = 1,
        binary: bool = False, max_bytes: int | None = 8_000_000,
        total_timeout: float = 60) -> Response:
    """`timeout` bounds connecting and each read; `total_timeout` bounds the whole call,
    retries included, so one dead site can't stall a run."""
    start = time.monotonic()
    give_up = start + total_timeout
    verify, insecure = True, False
    attempt, last_error = 0, None
    while attempt <= retries and time.monotonic() < give_up:
        try:
            remaining = max(5.0, give_up - time.monotonic())
            per_try = (min(10, timeout), min(timeout, remaining))   # (connect, read)
            with _session(legacy=insecure).get(url, timeout=per_try, verify=verify, stream=True) as r:
                data = _read(r, max_bytes, give_up)
                ctype = r.headers.get("Content-Type", "")
                if r.status_code >= 400:
                    last_error = f"HTTP {r.status_code}"
                    if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                        attempt += 1
                        time.sleep(2 * attempt)
                        continue
                    return Response(url, False, r.status_code, error=last_error,
                                    insecure=insecure, elapsed=time.monotonic() - start)
                return Response(
                    url, True, r.status_code,
                    text="" if binary else _decode(data, r),
                    content=data if binary else b"",
                    content_type=ctype, insecure=insecure,
                    elapsed=time.monotonic() - start,
                )
        except requests.exceptions.SSLError as e:
            if verify:  # one free retry without verification; doesn't use up a retry
                verify, insecure = False, True
                last_error = f"SSL: {e.__class__.__name__}"
                continue
            last_error = f"SSL: {e}"
        except (TooLarge, TooSlow) as e:
            return Response(url, False, error=str(e), elapsed=time.monotonic() - start)
        except (requests.ConnectionError, requests.Timeout) as e:
            last_error = e.__class__.__name__
        except requests.RequestException as e:
            last_error = f"{e.__class__.__name__}: {e}"
        attempt += 1
        if attempt <= retries:
            time.sleep(1.5 * attempt)
    return Response(url, False, error=last_error, insecure=insecure,
                    elapsed=time.monotonic() - start)


def fetch_many(urls, workers: int = 16, **kwargs) -> dict[str, Response]:
    urls = list(dict.fromkeys(urls))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(lambda u: get(u, **kwargs), urls)
        return dict(zip(urls, results))

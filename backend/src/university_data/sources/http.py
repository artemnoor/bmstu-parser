"""Provider-neutral resilient HTTP client.

The client owns the shared transport policy: one limiter for the process,
thread-local sessions, retries for transient responses and atomic downloads.
University adapters only provide URLs and parsing rules.
"""

import threading
import time
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class FetchError(RuntimeError):
    """An external request or response parsing failure."""


class RateLimiter:
    def __init__(self, interval: float) -> None:
        self.interval = max(0.0, interval)
        self._lock = threading.Lock()
        self._last_request = 0.0

    def wait(self) -> None:
        if self.interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            pause = self.interval - (now - self._last_request)
            if pause > 0:
                time.sleep(pause)
            self._last_request = time.monotonic()


class ApiClient:
    """Resilient GET/JSON/download client shared by all source plugins."""

    def __init__(
        self,
        timeout: float = 30.0,
        delay: float = 0.15,
        *,
        user_agent: str = "university-data-platform/1.0",
    ) -> None:
        self.timeout = timeout
        self.rate_limiter = RateLimiter(delay)
        self.user_agent = user_agent
        self._local = threading.local()

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            retry = Retry(
                total=4,
                connect=4,
                read=4,
                status=4,
                backoff_factor=0.6,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET"}),
                respect_retry_after_header=True,
            )
            session.mount("https://", HTTPAdapter(max_retries=retry))
            session.mount("http://", HTTPAdapter(max_retries=retry))
            session.headers.update(
                {
                    "User-Agent": self.user_agent,
                    "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
                }
            )
            self._local.session = session
        return session

    def request(self, url: str, **kwargs: Any) -> requests.Response:
        self.rate_limiter.wait()
        try:
            response = self._session().get(url, timeout=self.timeout, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            raise FetchError(f"GET {url}: {exc}") from exc

    def get_json(self, url: str, **kwargs: Any) -> dict[str, Any]:
        response = self.request(url, **kwargs)
        try:
            payload = response.json()
        except ValueError as exc:
            raise FetchError(f"GET {url}: response is not JSON") from exc
        if not isinstance(payload, dict):
            raise FetchError(f"GET {url}: expected a JSON object")
        return payload

    def download(self, url: str, destination: Path) -> int:
        self.rate_limiter.wait()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.part")
        try:
            with self._session().get(
                url, timeout=self.timeout, stream=True
            ) as response:
                response.raise_for_status()
                with temporary.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=1024 * 128):
                        if chunk:
                            output.write(chunk)
            temporary.replace(destination)
            return destination.stat().st_size
        except requests.RequestException as exc:
            temporary.unlink(missing_ok=True)
            raise FetchError(f"DOWNLOAD {url}: {exc}") from exc
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise FetchError(f"Saving {destination}: {exc}") from exc


__all__ = ["ApiClient", "FetchError", "RateLimiter"]

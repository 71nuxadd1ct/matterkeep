import logging
import time
from collections.abc import Iterator
from typing import Any, cast

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from matterkeep.exceptions import APIError, AuthError

logger = logging.getLogger(__name__)

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 5
_BACKOFF_BASE = 1.0
_BACKOFF_MAX = 60.0
_RATELIMIT_REMAINING_THRESHOLD = 5


class _TokenScrubFilter(logging.Filter):
    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    def filter(self, record: logging.LogRecord) -> bool:
        if self._token:
            record.msg = str(record.msg).replace(self._token, "***")
            record.args = tuple(
                str(a).replace(self._token, "***") if isinstance(a, str) else a
                for a in (record.args or ())
            )
        return True


class MMClient:
    def __init__(self, server_url: str, token: str, verify_ssl: bool = True) -> None:
        self._base = server_url.rstrip("/")
        self._token = token
        self._verify = verify_ssl
        self._session = self._build_session()

        scrub = _TokenScrubFilter(token)
        logging.getLogger().addFilter(scrub)

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers["Authorization"] = f"Bearer {self._token}"
        session.headers["Content-Type"] = "application/json"

        retry = Retry(
            total=_MAX_RETRIES,
            backoff_factor=_BACKOFF_BASE,
            status_forcelist=_RETRY_STATUSES,
            allowed_methods={"GET"},
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _url(self, path: str) -> str:
        return f"{self._base}/api/v4/{path.lstrip('/')}"

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = self._url(path)
        logger.debug("%s %s", method, url)

        for attempt in range(_MAX_RETRIES + 1):
            resp = self._session.request(method, url, verify=self._verify, **kwargs)

            remaining = resp.headers.get("X-Ratelimit-Remaining")
            reset = resp.headers.get("X-Ratelimit-Reset")
            if remaining is not None:
                try:
                    if int(remaining) <= _RATELIMIT_REMAINING_THRESHOLD and reset:
                        sleep_for = max(0, int(reset) - int(time.time())) + 1
                        logger.debug("Rate limit low, sleeping %ds", sleep_for)
                        time.sleep(sleep_for)
                except ValueError:
                    pass

            if resp.status_code == 429:
                if attempt >= _MAX_RETRIES:
                    raise APIError("Rate limited after max retries.", status_code=429)
                delay = min(_BACKOFF_BASE * (2**attempt), _BACKOFF_MAX)
                logger.warning("429 received, retrying in %.1fs", delay)
                time.sleep(delay)
                continue

            if resp.status_code == 401:
                raise AuthError("Session token rejected. Re-run to authenticate.")

            if resp.status_code >= 500:
                if attempt >= _MAX_RETRIES:
                    raise APIError(
                        f"Server error {resp.status_code} after max retries.",
                        status_code=resp.status_code,
                    )
                delay = min(_BACKOFF_BASE * (2**attempt), _BACKOFF_MAX)
                logger.warning("Server error %d, retrying in %.1fs", resp.status_code, delay)
                time.sleep(delay)
                continue

            return resp

        raise APIError("Exhausted retries.")  # unreachable, but satisfies type checker

    def get(self, path: str, **kwargs: Any) -> Any:
        resp = self._request("GET", path, **kwargs)
        if not resp.ok:
            raise APIError(
                f"GET {path} returned {resp.status_code}: {resp.text[:200]}",
                status_code=resp.status_code,
            )
        return resp.json()

    def get_raw(self, path: str, **kwargs: Any) -> bytes:
        resp = self._request("GET", path, **kwargs)
        if resp.status_code == 403:
            raise APIError(f"Access denied: {path}", status_code=403)
        if not resp.ok:
            raise APIError(
                f"GET {path} returned {resp.status_code}",
                status_code=resp.status_code,
            )
        return resp.content

    def get_stream(self, path: str, **kwargs: Any) -> Iterator[bytes]:
        resp = self._request("GET", path, stream=True, **kwargs)
        if resp.status_code == 403:
            raise APIError(f"Access denied: {path}", status_code=403)
        if not resp.ok:
            raise APIError(
                f"GET {path} returned {resp.status_code}",
                status_code=resp.status_code,
            )
        return cast(Iterator[bytes], resp.iter_content(chunk_size=65536))

    def paginate(self, path: str, per_page: int = 200, **kwargs: Any) -> Iterator[Any]:
        page = 0
        while True:
            params = kwargs.pop("params", {})
            params.update({"page": page, "per_page": per_page})
            items = self.get(path, params=params, **kwargs)
            if not items:
                break
            yield from items
            if len(items) < per_page:
                break
            page += 1

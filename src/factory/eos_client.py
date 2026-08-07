"""HTTP client for the EOS External API (test-logs).

Mirrors the four endpoints in ``docs/api-usage.md``:

    /levels -> /runs -> /artifacts -> /artifact-content

Stdlib only (urllib). Adds three things the raw doc example does not have and
that a batch collector needs: retry with backoff, a timeout, and an on-disk
response cache so re-running a collection does not re-download artifacts.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from . import __version__, config

log = logging.getLogger(__name__)

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class EOSError(RuntimeError):
    """An EOS API call failed in a way retrying will not fix."""


class EOSClient:
    """Thin, retrying, caching wrapper around the EOS test-logs API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        timeout: float = 60.0,
        max_retries: int = 4,
        use_cache: bool = True,
    ) -> None:
        self.api_key = api_key or config.api_key()
        self.base_url = (base_url or config.base_url()).rstrip("/")
        self.cache_dir = cache_dir or (config.RAW_DIR / "http-cache")
        self.timeout = timeout
        self.max_retries = max_retries
        self.use_cache = use_cache
        if self.use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- transport

    def _url(self, path: str, params: Dict[str, Any]) -> str:
        clean = {k: v for k, v in params.items() if v is not None and v != ""}
        query = urllib.parse.urlencode(clean, safe=":/")
        return "{}/{}?{}".format(self.base_url, path.lstrip("/"), query)

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        return self.cache_dir / "{}.bin.gz".format(digest)

    def get_bytes(self, path: str, params: Optional[Dict[str, Any]] = None) -> bytes:
        """GET a path and return the raw body, using the on-disk cache if present."""
        url = self._url(path, params or {})
        cached = self._cache_path(url)
        if self.use_cache and cached.exists():
            log.debug("cache hit %s", url)
            with gzip.open(cached, "rb") as handle:
                return handle.read()

        body = self._fetch(url)

        if self.use_cache:
            with gzip.open(cached, "wb") as handle:
                handle.write(body)
        return body

    def _fetch(self, url: str) -> bytes:
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": "Bearer {}".format(self.api_key),
                "Accept": "*/*",
                "User-Agent": "factory-data-analysis/{}".format(__version__),
            },
        )

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:500]
                if exc.code in RETRY_STATUS and attempt < self.max_retries:
                    delay = self._backoff(attempt, exc.headers.get("Retry-After"))
                    log.warning(
                        "HTTP %s on %s — retry %s/%s in %.1fs",
                        exc.code,
                        url,
                        attempt + 1,
                        self.max_retries,
                        delay,
                    )
                    time.sleep(delay)
                    last_error = exc
                    continue
                raise EOSError("HTTP {} for {}: {}".format(exc.code, url, detail)) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < self.max_retries:
                    delay = self._backoff(attempt, None)
                    log.warning("network error on %s (%s) — retry in %.1fs", url, exc, delay)
                    time.sleep(delay)
                    last_error = exc
                    continue
                raise EOSError("network failure for {}: {}".format(url, exc)) from exc

        raise EOSError("exhausted retries for {}: {}".format(url, last_error))

    @staticmethod
    def _backoff(attempt: int, retry_after: Optional[str]) -> float:
        if retry_after:
            try:
                return min(float(retry_after), 60.0)
            except ValueError:
                pass
        return min(2.0 ** attempt, 30.0)

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        raw = self.get_bytes(path, params)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EOSError("non-JSON body from {}: {}".format(path, exc)) from exc

    # ---------------------------------------------------------------- endpoints

    def levels(self) -> list:
        """GET /levels -> ``["l6", "l10", ...]``."""
        payload = self.get_json("/levels")
        if isinstance(payload, dict):
            return list(payload.get("levels", []))
        return list(payload or [])

    def runs(
        self,
        level: str,
        frm: Optional[str] = None,
        to: Optional[str] = None,
        dut_serial: Optional[str] = None,
        suite: Optional[str] = None,
        version: Optional[str] = None,
        station: Optional[str] = None,
    ) -> list:
        """GET /runs -> a list of run descriptors for a level and time window.

        ``frm``/``to`` accept ``YYYY-MM-DD`` or ISO-8601 instants, and both bounds
        are inclusive (see ``docs/api-usage.md``).
        """
        payload = self.get_json(
            "/runs",
            {
                "level": level,
                "from": frm,
                "to": to,
                "dutSerial": dut_serial,
                "suite": suite,
                "version": version,
                "station": station,
            },
        )
        if isinstance(payload, dict):
            return list(payload.get("runs", []))
        return list(payload or [])

    def artifacts(
        self,
        level: str,
        dut_serial: str,
        run_id: str,
        role: Optional[str] = None,
    ) -> list:
        """GET /artifacts -> the files belonging to one run, optionally by role."""
        payload = self.get_json(
            "/artifacts",
            {"level": level, "dutSerial": dut_serial, "runId": run_id, "role": role},
        )
        if isinstance(payload, dict):
            return list(payload.get("artifacts", []))
        return list(payload or [])

    def artifact_content(
        self, level: str, dut_serial: str, run_id: str, rel_path: str
    ) -> bytes:
        """GET /artifact-content -> the bytes of one artifact."""
        return self.get_bytes(
            "/artifact-content",
            {
                "level": level,
                "dutSerial": dut_serial,
                "runId": run_id,
                "relPath": rel_path,
            },
        )

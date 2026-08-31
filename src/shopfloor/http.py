"""One HTTP helper, stdlib only, that never raises at the caller.

WHY NOT requests
----------------
``Analysis`` is stdlib-only and runs unattended on a factory host that nobody
wants to pip-install onto at 2am. This repo keeps that property.

WHY EVERY FAILURE IS A VALUE, NOT AN EXCEPTION
----------------------------------------------
This tool exists for the case where a source is broken. If a broken source
raised, the tool would die exactly when it is most needed. So every call returns
``Response`` — ``ok`` plus either ``data`` or ``error`` — and callers record the
failure into the snapshot manifest instead of stopping. A graph that says
"EOS: unreachable" is a usable graph. A traceback is not.
"""

from __future__ import annotations

import base64
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from . import config


@dataclass
class Response:
    ok: bool
    status: int = 0
    data: Any = None
    text: str = ""
    error: str = ""
    url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)


def _unverified_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def get(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    token: str = "",
    basic: Optional[tuple] = None,
    ca_bundle: str = "",
    verify: bool = True,
    timeout: Optional[float] = None,
    as_json: bool = True,
    retries: int = 0,
) -> Response:
    """GET a URL. Returns a ``Response``; never raises for a network fault.

    ``retries`` re-attempts only *transient* faults — a timeout, a DNS blip, a
    5xx. A 401 or a 404 is retried never: the answer will not change and a retry
    only doubles the time to find out. This mattered in practice: a single
    30-second timeout on the EOS ``slt`` sweep silently dropped every MLT record
    from a snapshot, and the rendered file lost 8 of 22 tested parts while
    looking entirely healthy apart from one line in its manifest.
    """
    attempt = 0
    while True:
        response = _get_once(
            url, params=params, token=token, basic=basic, ca_bundle=ca_bundle,
            verify=verify, timeout=timeout, as_json=as_json,
        )
        if response.ok or attempt >= retries or not _transient(response):
            return response
        attempt += 1


#: Faults worth a second attempt. Everything else is an answer, not a hiccup.
_TRANSIENT_STATUS = frozenset({408, 429, 500, 502, 503, 504})
_TRANSIENT_ERRORS = ("timeout", "URLError", "TimeoutError", "ConnectionError",
                     "RemoteDisconnected", "IncompleteRead", "SSLError")


def _transient(response: "Response") -> bool:
    if response.status in _TRANSIENT_STATUS:
        return True
    return any(marker in response.error for marker in _TRANSIENT_ERRORS)


def _get_once(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    token: str = "",
    basic: Optional[tuple] = None,
    ca_bundle: str = "",
    verify: bool = True,
    timeout: Optional[float] = None,
    as_json: bool = True,
) -> Response:
    if params:
        clean = {k: v for k, v in params.items() if v not in (None, "")}
        if clean:
            url = f"{url}?{urllib.parse.urlencode(clean)}"

    request = urllib.request.Request(url, method="GET")
    request.add_header("Accept", "application/json, text/plain, */*")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    elif basic and basic[0]:
        raw = f"{basic[0]}:{basic[1]}".encode()
        request.add_header("Authorization", "Basic " + base64.b64encode(raw).decode())

    context: Optional[ssl.SSLContext] = None
    if url.lower().startswith("https"):
        if ca_bundle:
            context = ssl.create_default_context(cafile=ca_bundle)
        elif not verify:
            context = _unverified_context()

    try:
        with urllib.request.urlopen(
            request, timeout=timeout or config.TIMEOUT, context=context
        ) as handle:
            body = handle.read()
            status = handle.status
            headers = dict(handle.headers.items())
    except urllib.error.HTTPError as exc:  # 4xx/5xx still carry a useful body
        body = exc.read() if hasattr(exc, "read") else b""
        text = body.decode("utf-8", "replace")
        return Response(
            ok=False, status=exc.code, text=text, error=f"HTTP {exc.code}", url=url
        )
    except Exception as exc:  # DNS, TLS, timeout, refused — all the same to us
        return Response(ok=False, error=f"{type(exc).__name__}: {exc}", url=url)

    text = body.decode("utf-8", "replace")
    if not as_json:
        return Response(ok=True, status=status, text=text, url=url, headers=headers)
    try:
        return Response(
            ok=True, status=status, data=json.loads(text), text=text, url=url,
            headers=headers,
        )
    except json.JSONDecodeError as exc:
        # A login redirect body lands here. Say so plainly: "not JSON" plus the
        # first line is enough to recognise an auth problem without a debugger.
        return Response(
            ok=False, status=status, text=text, url=url,
            error=f"not JSON ({exc}); body starts: {text[:120]!r}",
        )

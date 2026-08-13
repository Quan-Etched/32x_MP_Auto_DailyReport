"""The local control endpoint behind the dashboard's Update button.

WHY THIS EXISTS
---------------
The dashboard is a static bundle. On the published GitHub Pages copy there is no
server, so a button there cannot fetch from EOS, cannot rebuild, and cannot
publish — the API key, the internal CA and the git credential all live on the
machine that runs the ETL. Pages can only ever show the last snapshot someone
pushed to it.

So the button is served by ``factory.cli serve``: the same dashboard files, plus
three routes on 127.0.0.1 that run the real pipeline and stream its progress
back. The published copy detects that those routes are absent and shows how old
its snapshot is instead of a button that would lie.

ONE UPDATE PATH
---------------
The job shells out to ``tools/hourly_refresh.sh`` — the same script the hourly
launchd agent runs. The button is therefore not a second implementation of
"update everything" that can drift from the scheduled one; it is the scheduled
one, triggered by hand. That script also holds the lock, so a click during an
hourly tick backs off instead of running two collections at once.

EXPOSURE
--------
The listener is bound to 127.0.0.1, but any page in the browser can still post
to a loopback port. Two cheap guards close that: the Host header must be
loopback (defeats DNS rebinding, where evil.com resolves to 127.0.0.1 and the
browser happily sends the request), and POST must carry ``X-Factory-Update``,
which is not a CORS-safelisted header and so forces a preflight that this server
never answers. The worst a bypass could do is trigger a refresh, but a button
that publishes real factory data deserves the seatbelt.
"""

from __future__ import annotations

import http.server
import json
import os
import subprocess
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from . import config

UPDATE_SCRIPT = config.REPO_ROOT / "tools" / "hourly_refresh.sh"

#: The stages a full update moves through, in order. ``collect``, ``items`` and
#: ``build`` are announced by ``cli._step``; ``publish`` by the shell script.
#: Keeping the list here means the browser can render the whole plan up front,
#: greyed out, rather than growing it one surprise at a time.
STEPS: List[Dict[str, str]] = [
    {"key": "collect", "label": "Fetch runs from EOS"},
    {"key": "items", "label": "Flatten new runs to test items"},
    {"key": "build", "label": "Rebuild the dashboard bundles"},
    {"key": "publish", "label": "Publish the dashboard"},
]

#: Enough log to diagnose a failure, bounded so a stuck job cannot grow without
#: limit. The full output always goes to data/logs/refresh.log regardless.
MAX_LOG_LINES = 500

#: A collection that has not finished in this long is wedged, not slow: the
#: 30-day collect takes a couple of minutes. Kill it so the button recovers
#: instead of staying "running" until the server restarts.
JOB_TIMEOUT_SEC = 45 * 60

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1", "[::1]")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class UpdateJob:
    """One full update, run in a background thread, observable over HTTP.

    A single instance per server: the pipeline writes runs.json, the item store
    and the dashboard bundles, so two concurrent jobs would race on all three.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self.state = "idle"          # idle | running | ok | failed | busy
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.message = ""
        self.exit_code: Optional[int] = None
        self.steps: List[Dict[str, Any]] = self._fresh_steps()
        self.log: Deque[str] = deque(maxlen=MAX_LOG_LINES)

    @staticmethod
    def _fresh_steps() -> List[Dict[str, Any]]:
        return [dict(step, state="pending") for step in STEPS]

    # -------------------------------------------------------------- lifecycle

    def start(self, days: Optional[int] = None) -> bool:
        """Begin an update. False if one is already running."""
        with self._lock:
            if self.state == "running":
                return False
            self.state = "running"
            self.started_at = _now()
            self.finished_at = None
            self.exit_code = None
            self.message = "Starting"
            self.steps = self._fresh_steps()
            self.log.clear()

        thread = threading.Thread(target=self._run, args=(days,), daemon=True)
        thread.start()
        return True

    def _run(self, days: Optional[int]) -> None:
        env = dict(os.environ)
        env["FACTORY_PROGRESS"] = "1"        # ask the CLI for ::step markers
        env["FACTORY_PUBLISH"] = "1"         # the whole point of the button
        env["FACTORY_REFRESH_ITEMS"] = "1"
        env["PYTHONUNBUFFERED"] = "1"        # or progress arrives in one lump
        if days:
            env["FACTORY_REFRESH_DAYS"] = str(days)

        try:
            proc = subprocess.Popen(
                ["bash", str(UPDATE_SCRIPT)],
                cwd=str(config.REPO_ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            self._finish("failed", "Could not start {}: {}".format(
                UPDATE_SCRIPT.name, exc), exit_code=None)
            return

        self._proc = proc
        watchdog = threading.Timer(JOB_TIMEOUT_SEC, self._kill_stuck)
        watchdog.daemon = True
        watchdog.start()
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                self._consume(line.rstrip("\n"))
            code = proc.wait()
        finally:
            watchdog.cancel()
            self._proc = None

        if self.state == "busy":             # the script deferred to a live tick
            self._finish("busy", self.message or "Another update is already running",
                         exit_code=code)
            return
        if code == 0:
            for step in self.steps:
                if step["state"] in ("pending", "running"):
                    step["state"] = "done"
            self._finish("ok", self.message or "Updated and published", exit_code=0)
        else:
            for step in self.steps:
                if step["state"] == "running":
                    step["state"] = "failed"
            self._finish("failed", self.message or
                         "Update failed (exit {}) — see the log below".format(code),
                         exit_code=code)

    def _kill_stuck(self) -> None:
        proc = self._proc
        if proc and proc.poll() is None:
            self._consume("!! update exceeded {} minutes — terminating".format(
                JOB_TIMEOUT_SEC // 60))
            proc.terminate()

    def _finish(self, state: str, message: str, exit_code: Optional[int]) -> None:
        with self._lock:
            self.state = state
            self.message = message
            self.exit_code = exit_code
            self.finished_at = _now()

    # ---------------------------------------------------------------- parsing

    def _consume(self, line: str) -> None:
        """Fold one line of pipeline output into the observable state."""
        if line.startswith("::step "):
            parts = line[len("::step "):].split(" ", 1)
            self._enter_step(parts[0], parts[1] if len(parts) > 1 else "")
            return

        self.log.append(line)

        # The lock is held by an hourly tick: report that honestly rather than
        # as a success, or the reader concludes the data is fresh when the tick
        # that is actually running may still fail.
        if "SKIP another refresh is already running" in line:
            self.state = "busy"
            self.message = "An hourly update is already running — try again shortly"
        elif line.startswith("Fetch FAILED"):
            self.message = line[:200]
        elif line.startswith("Published "):
            self.message = "Updated and published"

    def _enter_step(self, key: str, label: str) -> None:
        seen = False
        for step in self.steps:
            if step["key"] == key:
                step["state"] = "running"
                if label:
                    step["label"] = label
                seen = True
            elif not seen:
                if step["state"] in ("pending", "running"):
                    step["state"] = "done"   # markers are ordered: earlier ones are past
        self.message = label or key

    # --------------------------------------------------------------- readout

    def snapshot(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "message": self.message,
            "exitCode": self.exit_code,
            "steps": [dict(step) for step in self.steps],
            "log": list(self.log),
        }


class ControlHandler(http.server.SimpleHTTPRequestHandler):
    """Static dashboard + the /api routes the Update button drives."""

    job: UpdateJob = UpdateJob()

    # ------------------------------------------------------------------ routes

    def do_GET(self) -> None:                       # noqa: N802 (stdlib casing)
        route = self.path.split("?", 1)[0]
        if route == "/api/ping":
            self._json({"ok": True, "canUpdate": True, "repo": config.REPO_ROOT.name})
        elif route == "/api/update":
            self._json(self._update_state())
        elif route.startswith("/api/"):
            self._json({"error": "no such route"}, status=404)
        else:
            super().do_GET()

    def do_POST(self) -> None:                      # noqa: N802
        route = self.path.split("?", 1)[0]
        if route != "/api/update":
            self._json({"error": "no such route"}, status=404)
            return
        if not self._guard_ok():
            self._json({"error": "refused: not a local dashboard request"}, status=403)
            return

        if not self.job.start(days=self._days_param()):
            self._json(dict(self._update_state(),
                            error="an update is already running"), status=409)
            return
        self._json(self._update_state(), status=202)

    # ----------------------------------------------------------------- guards

    def _guard_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ("127.0.0.1", "localhost", "::1"):
            return False
        return self.headers.get("X-Factory-Update") is not None

    def _days_param(self) -> Optional[int]:
        _, _, query = self.path.partition("?")
        for pair in query.split("&"):
            key, _, value = pair.partition("=")
            if key == "days" and value.isdigit():
                return max(1, min(int(value), 365))
        return None

    # ---------------------------------------------------------------- helpers

    def _update_state(self) -> Dict[str, Any]:
        from . import fetchstate

        state = self.job.snapshot()
        try:
            fetch = fetchstate.load()
        except (OSError, ValueError):
            fetch = {}
        state["fetch"] = {
            "lastFetchAttemptAt": fetch.get("lastFetchAttemptAt") or fetch.get("lastFetchAt"),
            "lastFetchStatus": fetch.get("lastFetchStatus"),
            "lastUpdateAt": fetch.get("lastUpdateAt"),
            "runCount": fetch.get("runCount"),
        }
        return state

    def _json(self, payload: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self) -> None:
        # The bundles are rewritten under the browser's feet by an update; a
        # cached metrics.js would show yesterday's numbers after the reload.
        if self.path.startswith("/data/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        # Polling the job state once a second would otherwise bury the one line
        # that matters ("Dashboard: http://...") in request noise.
        if self.path.startswith("/api/update") and self.command == "GET":
            return
        super().log_message(fmt, *args)

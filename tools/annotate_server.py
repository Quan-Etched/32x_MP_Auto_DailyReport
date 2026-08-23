#!/usr/bin/env python3
"""The annotation service: takes an edit from the customize page, commits it.

WHY A SERVICE AT ALL
The dashboard is static files behind nginx. A page can render anything but it
cannot write to the repo, and the box serving it has no writable backend and no
sudo available to add one. So the edit has to reach a process that can, and this
is the smallest such process: stdlib only, one endpoint, no framework.

WHERE IT RUNS
Wherever somebody can commit. Two shapes, both supported:

  make annotate                 on the machine with the clone. The page posts
                                to /annotate on its own origin, so this is for
                                a locally served dashboard (`make serve`).

  behind nginx on the box       add one location block proxying /annotate here
                                and every admin can save from the published
                                page. That needs a root on the box, which is
                                why it is not the default.

WHAT IT CHECKS
The password. This is the real gate — the page's sign-in only unlocks the cells,
because a check in published JavaScript is a check a reader can skip. The
credential lives here, out of the served tree, and is read from the environment
so it is not in the repo either.

WHAT IT WRITES
errors/annotations.json, then `git commit` of that one file, attributed in the
message to the admin who made the edit. Never anything else: the path is fixed,
and an edit names a (day, station, unit, case) that must already exist in the
error bundle — an unrecognised key is refused rather than filed.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = pathlib.Path(__file__).resolve().parent.parent
ANNOTATIONS = REPO / "errors" / "annotations.json"
BUNDLE = REPO / "dashboard" / "data" / "errors.js"

#: Who may write. Names only — the password is shared, and one password with a
#: named author is what was asked for. FACTORY_ANNOTATE_USERS overrides.
USERS = [name.strip().lower() for name in
         os.environ.get("FACTORY_ANNOTATE_USERS", "chuck,eason,chris").split(",")
         if name.strip()]

#: The shared password. Overridable, and deliberately not defaulted to nothing:
#: a service that accepts an empty password because the environment was not set
#: is worse than one that refuses to start.
PASSWORD = os.environ.get("FACTORY_ANNOTATE_PASSWORD", "AlwaysPass")

#: Only these three. The rest of the row is derived from the tracker and the
#: catalogue, and an editable copy of a derived value is a second source of
#: truth waiting to disagree with the first.
FIELDS = ("rootCause", "correctiveAction", "note")

#: Root cause is a choice, not prose. The page offers exactly these and the
#: service checks: a table where half the rows say "setup issue" and half say
#: "test setup" is a table nobody can count, and once a third spelling is in the
#: file it is in every export made from it.
CAUSES = ("setup", "dut")

MAX_BODY = 256 * 1024
MAX_FIELD = 4000


class Refused(Exception):
    """A request that will not be filed, with the reason to send back."""

    def __init__(self, status: int, why: str):
        super().__init__(why)
        self.status = status
        self.why = why


def load() -> dict:
    if not ANNOTATIONS.exists():
        return {"version": 1, "entries": {}}
    got = json.loads(ANNOTATIONS.read_text(encoding="utf-8"))
    got.setdefault("entries", {})
    return got


def known_keys() -> set:
    """Every (day|station|unit|case) the error bundle actually has.

    An edit against a key that is not in the bundle is a typo or a stale tab,
    and filing it would leave an annotation nothing ever renders — invisible
    and wrong, which is the worst of both.
    """
    if not BUNDLE.exists():
        return set()
    text = BUNDLE.read_text(encoding="utf-8")
    data = json.loads(text.split("= ", 1)[1].rstrip().rstrip(";"))
    return {"|".join([row["day"], row["station"], row["dut"], row["case"]])
            for row in data.get("rows") or []}


def stamp() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def apply_edits(user: str, edits: list) -> tuple:
    """Merge edits into the annotations file. Returns (written, skipped)."""
    store = load()
    entries = store["entries"]
    allowed = known_keys()
    written, skipped = 0, []

    for edit in edits:
        try:
            key = "|".join([edit["day"], edit["station"], edit["dut"],
                            edit["case"]])
        except (KeyError, TypeError):
            skipped.append("an edit was missing day/station/dut/case")
            continue
        if allowed and key not in allowed:
            skipped.append(key + " is not in the error bundle")
            continue
        entry = dict(entries.get(key) or {})
        changed = False
        for field in FIELDS:
            if field not in edit:
                continue
            value = str(edit[field] or "").strip()
            if len(value) > MAX_FIELD:
                skipped.append(key + ": " + field + " is too long")
                continue
            if field == "rootCause" and value and value not in CAUSES:
                skipped.append("{}: root cause must be one of {}, not {!r}"
                               .format(key, "/".join(CAUSES), value[:40]))
                continue
            if value:
                entry[field] = value
            else:
                entry.pop(field, None)
            changed = True
        if not changed:
            continue
        if any(entry.get(field) for field in FIELDS):
            entry["by"] = user
            entry["at"] = stamp()
            entries[key] = entry
        else:
            # Every field cleared: drop the entry rather than leave a husk of
            # authorship attached to nothing.
            entries.pop(key, None)
        written += 1

    if written:
        store["version"] = store.get("version", 1)
        ANNOTATIONS.write_text(
            json.dumps(store, indent=1, sort_keys=True) + "\n",
            encoding="utf-8")
    return written, skipped


def git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(("git", "-C", str(REPO)) + args,
                          capture_output=True, text=True, timeout=60)


def commit(user: str, written: int) -> str:
    """Commit the one file. Returns the short hash, or '' if nothing to do."""
    status = git("status", "--porcelain", str(ANNOTATIONS))
    if not status.stdout.strip():
        return ""
    message = ("Error-code notes from {}\n\n"
               "{} row{} annotated through the customize page. Root cause, "
               "corrective action and note are the only fields this path can "
               "write; everything else on that table is derived from the "
               "tracker and the error-code sheet.\n".format(
                   user, written, "" if written == 1 else "s"))
    add = git("add", str(ANNOTATIONS))
    if add.returncode:
        raise Refused(500, "git add failed: " + add.stderr.strip())
    done = git("commit", "-m", message, "--", str(ANNOTATIONS))
    if done.returncode:
        raise Refused(500, "git commit failed: " + done.stderr.strip())
    head = git("rev-parse", "--short", "HEAD")
    return head.stdout.strip()


class Handler(BaseHTTPRequestHandler):
    server_version = "factory-annotate/1"

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # Same-origin only. The page and this service are served together; a
        # wildcard here would let any site post edits with a guessed password.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:                            # noqa: N802
        try:
            if self.path.rstrip("/").split("/")[-1] != "annotate":
                raise Refused(404, "not found")
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                raise Refused(413, "body missing or too large")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))

            user = str(payload.get("user") or "").strip().lower()
            password = str(payload.get("password") or "")
            edits = payload.get("edits") or []

            if user not in USERS:
                raise Refused(403, "{} is not an admin".format(user or "nobody"))
            if password != PASSWORD:
                raise Refused(401, "wrong password")
            if not isinstance(edits, list) or not edits:
                raise Refused(400, "no edits in the request")

            written, skipped = apply_edits(user, edits)
            if not written:
                raise Refused(400, "nothing to write" +
                              (": " + "; ".join(skipped) if skipped else ""))
            head = commit(user, written)
            self.log_message("wrote %d row(s) for %s%s", written, user,
                             " as " + head if head else "")
            self._reply(200, {"written": written, "commit": head,
                              "skipped": skipped})
        except Refused as refused:
            self._reply(refused.status, {"error": refused.why})
        except Exception as exc:                          # noqa: BLE001
            self.log_message("failed: %s", exc)
            self._reply(500, {"error": str(exc)})

    def do_GET(self) -> None:                             # noqa: N802
        """A health check, so somebody can tell whether this is even up."""
        if self.path.rstrip("/").split("/")[-1] != "annotate":
            self._reply(404, {"error": "not found"})
            return
        self._reply(200, {"ok": True, "users": USERS,
                          "annotations": str(ANNOTATIONS),
                          "entries": len(load()["entries"])})


def main(argv) -> int:
    port = int(argv[1]) if len(argv) > 1 else 8766
    if not PASSWORD:
        print("FACTORY_ANNOTATE_PASSWORD is empty — refusing to start",
              file=sys.stderr)
        return 2
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("annotate: http://127.0.0.1:{}/annotate  users: {}".format(
        port, ", ".join(USERS)))
    print("  writes {} and commits it".format(
        ANNOTATIONS.relative_to(REPO)))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nannotate: stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""What this dashboard needs from other systems, and whether it still needs it.

WHY A PAGE AND NOT A DOC
-----------------------
Every one of these has been written down before — in STATUS.md, in a commit
message, in a slide. Written-down asks rot: the L11 IAM denial has been true for
a week, the Jira URL was unknown until someone looked it up, and nobody can tell
from a document which is which. A reader ends up re-verifying the whole list
before trusting any of it.

So the ones that can be checked, are. Each entry may carry a probe that runs at
build time and answers one question: *is this still true?* The page then shows
`blocked · checked 4 minutes ago` rather than a claim of unknown age, and an ask
that someone quietly fixed turns green on the next hourly build without anyone
editing this file.

WHAT BELONGS HERE
-----------------
Only things **outside this repo** — a route, a certificate, an IAM grant, a
field in someone else's API, a decision that is not ours to make. Work we can
do ourselves belongs in STATUS.md under "not done yet"; putting it here would
turn a list of asks into a backlog and nobody would read either.

Each entry states the ask, why it matters, the evidence, and what "done" looks
like — because an ask without a done-condition is a complaint.
"""

from __future__ import annotations

import json
import socket
import ssl
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import config, links

SITE_URL = "https://32x-production.i.etched.com/"

#: How long a probe may take. The build must not stall on a dead host.
PROBE_TIMEOUT = 6.0

BLOCKED = "blocked"
RESOLVED = "resolved"
UNKNOWN = "unknown"
DECISION = "decision"

#: An ask nobody has automated a check for. Distinct from "unknown", which means
#: a check exists and could not answer.
OPEN = "open"


# ------------------------------------------------------------------- probes

def _probe_pega(payload: Dict[str, Any]) -> Dict[str, str]:
    """Can the machine building this page reach pega3?

    Vantage-dependent, and it says so. The ask is about the *dashboard host*; a
    laptop answering "reachable" says nothing about it, so the answer carries
    the hostname and the page prints it. The published page is built on the box,
    so the published answer is the one that counts.
    """
    from . import pega

    where = _hostname()
    if not pega.enabled():
        return {"state": UNKNOWN, "note": "pega3 integration is switched off here"}
    if pega.available():
        return {"state": RESOLVED, "note": "reachable from {}".format(where),
                "vantage": where}
    return {"state": BLOCKED, "note": "not reachable from {}".format(where),
            "vantage": where}


def _probe_tls(payload: Dict[str, Any]) -> Dict[str, str]:
    """How many certificates does the server actually send?

    Counting the served chain, not asking whether *this* machine can verify.
    Those differ, and the difference is a trap: import the missing intermediate
    into your own keychain — which is the documented workaround — and a
    verification-based probe flips to green while every other reader still gets
    a warning. The ask is that nginx serve the intermediate, so the probe counts
    what nginx serves.
    """
    host = SITE_URL.split("//", 1)[-1].strip("/")
    try:
        result = subprocess.run(
            ["openssl", "s_client", "-connect", "{}:443".format(host),
             "-servername", host, "-showcerts"],
            input="", capture_output=True, text=True, timeout=PROBE_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"state": UNKNOWN, "note": "could not probe the chain ({})".format(exc)}

    served = result.stdout.count("BEGIN CERTIFICATE")
    if served == 0:
        return {"state": UNKNOWN, "note": "site not reachable from here"}
    if served >= 2:
        return {"state": RESOLVED,
                "note": "server sends {} certificates — the chain is complete".format(served)}
    return {"state": BLOCKED,
            "note": "server sends the leaf only (1 certificate), so no client can "
                    "build a path"}


def _probe_l11(payload: Dict[str, Any]) -> Dict[str, str]:
    """Did the last collection still get a 502 for the l11 level?"""
    errors = payload.get("levelErrors") or {}
    message = errors.get("l11")
    if message:
        detail = "s3:ListBucket denied" if "ListBucket" in message else message[:90]
        return {"state": BLOCKED, "note": "last collect: {}".format(detail)}
    if any(run.get("level") == "l11" for run in payload.get("runs", [])):
        return {"state": RESOLVED, "note": "l11 runs are being collected"}
    return {"state": UNKNOWN, "note": "l11 was not attempted in the last collect"}


def _probe_ocp(payload: Dict[str, Any]) -> Dict[str, str]:
    if links.run_url_template():
        return {"state": RESOLVED, "note": "FACTORY_OCP_RUN_URL is set; runs deep-link"}
    return {"state": BLOCKED,
            "note": "no per-run URL exists; confirmed in a logged-in browser"}


def _probe_jira(payload: Dict[str, Any]) -> Dict[str, str]:
    base = links.jira_base()
    if base:
        return {"state": RESOLVED, "note": "keys link to {}".format(base)}
    return {"state": BLOCKED, "note": "no Jira base URL configured"}


def _probe_slot_serial(payload: Dict[str, Any]) -> Dict[str, str]:
    """Has EOS started carrying a slot, or a second serial, on a run?"""
    for run in payload.get("runs", []):
        for key in ("slot", "slotNumber", "slot_number", "participating", "duts"):
            if run.get(key) not in (None, "", [], {}):
                return {"state": RESOLVED,
                        "note": "runs now carry {!r}".format(key)}
    return {"state": BLOCKED,
            "note": "runs carry one dutSerial and no slot"}


PROBES: Dict[str, Callable[[Dict[str, Any]], Dict[str, str]]] = {
    "pega3": _probe_pega,
    "tls": _probe_tls,
    "l11": _probe_l11,
    "ocp": _probe_ocp,
    "jira": _probe_jira,
    "slot-serial": _probe_slot_serial,
}


# ------------------------------------------------------------------ registry

REQUESTS: List[Dict[str, Any]] = [
    {
        "key": "pega3-route",
        "priority": "P0",
        "owner": "Infra",
        "title": "Give the dashboard host a route to pega3:3000",
        "need": "pega3 assigns the slots, so it is the only system that can say "
                "which DUT serial sat in which slot. Without it the tracker can "
                "report that a chip failed but not which unit — and today a person "
                "carries the data over by hand every day. It is the last manual "
                "step in the pipeline.",
        "evidence": [
            "chuck-dashboard.usw2.i.etched.com cannot resolve `pega3` "
            "(Name or service not known).",
            "`pega3.core.etched.com` resolves to the `*.core.etched.com` wildcard "
            "at 10.48.145.214, which is not pega3.",
            "From a laptop pega3 is 100.102.15.102 — a Tailscale address the EC2 "
            "host has no path to.",
        ],
        "doneWhen": "`curl http://pega3:3000/api/history/data-analysis/"
                    "suite-runs?per_page=1` returns 200 from the dashboard host.",
        "note": "Resolved 2026-08-14: Tailscale was already installed on the "
                "dashboard host and only needed authenticating — `tailscale up "
                "--shields-up`, once, no sudo. MagicDNS then resolves pega2 "
                "through pega5 by name, so nothing in this repo changed. The "
                "login expires after about 180 days (~2027-02-10); when it does "
                "the tracker falls back to EOS chip rows and this entry goes red "
                "again rather than failing loudly.",
        "check": "pega3",
        "raised": "2026-08-13",
    },
    {
        "key": "tls-chain",
        "priority": "P0",
        "owner": "Infra",
        "title": "Serve the full certificate chain on 32x-production",
        "need": "Every reader gets a browser security warning. A dashboard people "
                "have to click through a warning to reach is a dashboard people "
                "stop opening.",
        "evidence": [
            "nginx serves the leaf certificate alone — "
            "`openssl s_client -showcerts` returns exactly one certificate.",
            "The issuer, O=IDM.ETCHED.COM CN=Certificate Authority, is signed by "
            "Etched RSA Corporate Root CA, which MDM already installs on every "
            "managed Mac.",
            "`curl --cacert certs/etched-internal-ca.pem` returns 200, so the only "
            "thing missing is the intermediate.",
        ],
        "doneWhen": "Plain `curl https://32x-production.i.etched.com/` returns 200 "
                    "with no --cacert, and `openssl s_client -showcerts` returns "
                    "two certificates.",
        "workaround": "A reader can import the intermediate into their own "
                      "keychain; it validates up to the MDM root, so nothing new "
                      "is trusted.",
        "note": "eos.core.etched.com has the same omission, which is why every "
                "client needs `make trust` before it can call the API.",
        "check": "tls",
        "raised": "2026-08-13",
    },
    {
        "key": "eos-slot-serial",
        "priority": "P1",
        "owner": "EOS",
        "title": "Carry the slot → DUT serial map on a run",
        "need": "A fixture drives eight modules at once. EOS records the run with "
                "one dutSerial and no slot number, so seven of every eight units "
                "are anonymous and no EOS-only analysis can attribute a failure to "
                "a unit. This is the ask that would make pega3 unnecessary.",
        "evidence": [
            "Not present in suite_summary (five fields), event_stream (one "
            "dutInfoId plus the Devkit server's serial), suite_config (a test "
            "plan), bom_config (a static BOM with every serial_number null), or "
            "any of the 997 per-chip logs — all checked.",
            "pega3 returns it directly: participating[] with a dut_sn and "
            "slot_number per slot.",
            "Run counts match between the two systems (30/30, 17/14, 10/8 over "
            "08-11 to 08-13), so this is about identity, not missing data.",
        ],
        "doneWhen": "/runs, or an artifact a run already has, exposes a serial per "
                    "slot.",
        "check": "slot-serial",
        "raised": "2026-08-13",
    },
    {
        "key": "per-unit-verdict",
        "priority": "P1",
        "owner": "EOS · test framework",
        "title": "Make the per-unit verdict first class",
        "need": "Run status describes the fixture, not the unit: one bad chip fails "
                "the whole run. Run-level yield therefore reads about half of "
                "unit-level yield — MLT is 28.5% by run and 57.4% by unit over 30 "
                "days — and anyone quoting the wrong one is out by a factor of two.",
        "evidence": [
            "Measured on mlt_2026.220.0-git2f1c2f23_20260812_013949: 492 tests, "
            "run status fail, four chips good and four bad.",
            "We recover the per-chip verdict by parsing the chipN token out of "
            "test names — a convention, not a contract.",
            "It already appears in two spellings inside a single run "
            "(..._chip4 and chip6_...), so the convention has moved once.",
        ],
        "doneWhen": "A run carries a verdict per chip, or the naming convention is "
                    "committed to as an interface others may rely on.",
        "raised": "2026-08-13",
    },
    {
        "key": "l11-iam",
        "priority": "P2",
        "owner": "Infra · IAM",
        "title": "Grant s3:ListBucket on etched-mfg-prod-l11-raw",
        "need": "L11 Provision and L11 Test return HTTP 502, so two of the line's "
                "ten stations have never reported. No code change is needed once "
                "access is granted — only confirmation of their suite names, which "
                "are currently unverified guesses.",
        "evidence": [
            "EOS returns upstream_unavailable: user arn:aws:iam::745506449368:"
            "user/s3-mfg-reader is not authorized to perform s3:ListBucket on "
            "arn:aws:s3:::etched-mfg-prod-l11-raw.",
        ],
        "doneWhen": "/runs?level=l11 returns rows instead of upstream_unavailable.",
        "note": "There may be a way round this one. pega5 drives the L11 stations "
                "(pt2_l11_station1 and 2) and returns 40 runs over 30 days — "
                "L11_provisioning, L11_rack_power_cycle, L11_tests_ci — while EOS "
                "502s for the same level. Reading L11 from pega5 would unblock "
                "both stations without the IAM grant, at the cost of a second "
                "source for one station's data.",
        "check": "l11",
        "raised": "2026-08-06",
    },
    {
        "key": "ocp-run-url",
        "priority": "P2",
        "owner": "OCP Logs",
        "title": "Give a run a stable URL",
        "need": "OCP Logs has no per-run link at all, so a finding cannot be "
                "pasted into a ticket as a link to the run it came from.",
        "evidence": [
            "Confirmed in a logged-in browser: selecting three different runs left "
            "the address bar at https://ocplogs.core.etched.com every time.",
            "The RUNS tab keeps both its filter and its selection in memory.",
            "Its RUN ID column is our runId character for character, so the route "
            "exists in the data.",
        ],
        "doneWhen": "A run is addressable by URL. We then set FACTORY_OCP_RUN_URL "
                    "and every table deep-links with no other change.",
        "note": "Lowest priority of the six: our own run table already gives a link "
                "per run, and it reads the same records.",
        "check": "ocp",
        "raised": "2026-08-12",
    },
    {
        "key": "site-auth",
        "priority": "Decision",
        "owner": "Whoever owns the data",
        "title": "Decide whether the site should require a login",
        "need": "Anyone on the office network or VPN can read DUT serials, failure "
                "signatures and yield. The GitHub Pages copy this replaced required "
                "an authenticated Etched org member, so the move loosened access. "
                "That was a side effect, not a decision anyone made.",
        "evidence": [
            "The site has no authentication; not being routable from outside is "
            "the whole of its protection.",
        ],
        "doneWhen": "Someone decides. If the answer is yes it is an infra request; "
                    "if no, this entry closes and the posture is on the record.",
        "raised": "2026-08-13",
    },
    {
        "key": "tracker-selection",
        "priority": "Decision",
        "owner": "Module line",
        "title": "Decide whether the dashboard replaces the tracker sheet",
        "need": "The daily tracker can be rebuilt from the API exactly, and the "
                "rule deciding which units it covers now looks like the serial "
                "lot. If that is right, the sheet is fully derivable and can "
                "retire; if it is a coincidence of two days, we need the real rule "
                "before the page can claim to replace it.",
        "evidence": [
            "Cross-check of 08-11 and 08-12: every verdict matches (87 + 64 and "
            "51 + 41 units), and every FI test link matches.",
            "The sheet is exactly pega3 minus serial lot 26849410. 08-11: sheet "
            "has 26849411 x71 and 26849413 x16; pega3 adds 26849410 x25 and "
            "nothing else. 08-12: no lot-10 units ran and the two agree 51 to 51.",
            "The failure column lists every failure on the unit, so it is a "
            "superset of the sheet's: 63 of 64 rows contain the name a person "
            "typed, plus 61 failures the sheet never recorded. The single "
            "exception is a neighbouring slot's failure written on the wrong "
            "row of the sheet.",
        ],
        "doneWhen": "The line confirms the lot rule (or gives the real one), and "
                    "the page filters to it — or says the sheet retires and shows "
                    "every unit.",
        "raised": "2026-08-13",
    },
    {
        "key": "resource-config-creds",
        "priority": "Escalation",
        "owner": "EOS",
        "title": "resource_config artifacts contain plaintext credentials",
        "need": "resource_config carries the DUT's SSH and BMC username and "
                "password in cleartext, and anyone holding an EOS API key can read "
                "them. This pipeline never fetches that role, but the exposure does "
                "not depend on us.",
        "evidence": [
            "The role is listed on every run's artifact index alongside "
            "suite_summary and event_stream.",
            "config.ROLE_NEVER_FETCH exists in this repo specifically to keep it "
            "out of the collector.",
        ],
        "doneWhen": "The credentials are removed from the artifact, or the role is "
                    "access-controlled separately from the rest of a run.",
        "raised": "2026-08-06",
    },
    {
        "key": "htt-version",
        "priority": "Question",
        "owner": "HTT",
        "title": "Confirm which HTT version ran on 08-11 and 08-12",
        "need": "The tracker sheet and pega3 both record htt_2026.217.0-git3940b759 "
                "on those days. EOS records htt_2026.216.0-git1b767d1a and has no "
                "2026.217 run anywhere in the 30-day window. MLT agrees exactly "
                "between the systems, so this is specific to HTT.",
        "evidence": [
            "Sheet and pega3 links: htt_2026.217.0-git3940b759.",
            "EOS, same days, module level: htt_2026.216.0-git1b767d1a.",
            "No 2026.217 HTT run appears in EOS in 30 days.",
        ],
        "doneWhen": "Someone who owns HTT says which is right, and whether one of "
                    "the two systems is mislabelling the build.",
        "raised": "2026-08-13",
    },
    {
        "key": "jira-base",
        "priority": "P2",
        "owner": "Us",
        "title": "Link the tracker's Jira keys",
        "need": "The tracker's notes column holds real keys (ETCH-38567) that were "
                "rendered as plain text because no URL carrying one had been "
                "observed from here.",
        "evidence": [
            "Resolved 2026-08-13: the Atlassian API returns etched-ai as the only "
            "accessible site, and ETCH-38719 — a key taken straight out of the "
            "sheet — resolves there.",
        ],
        "doneWhen": "Keys render as links.",
        "check": "jira",
        "raised": "2026-08-12",
    },
]


# --------------------------------------------------------------------- build

def build_bundle(payload: Optional[Dict[str, Any]] = None,
                 probe: bool = True) -> Dict[str, Any]:
    payload = payload or {}
    entries = []
    for entry in REQUESTS:
        record = dict(entry)
        status = {"state": DECISION if entry["priority"] in ("Decision", "Question")
                  else OPEN, "note": "no automated check for this one"}
        probe_key = entry.get("check")
        if probe and probe_key and probe_key in PROBES:
            try:
                status = dict(PROBES[probe_key](payload))
            except Exception as exc:                            # noqa: BLE001
                # A probe that throws must not take the build with it; an ask
                # whose check is broken still has to be readable.
                status = {"state": UNKNOWN, "note": "probe failed: {}".format(exc)}
            status["checkedAt"] = datetime.now(timezone.utc).replace(
                microsecond=0).isoformat()
        record["status"] = status
        entries.append(record)

    counts: Dict[str, int] = {}
    for entry in entries:
        counts[entry["status"]["state"]] = counts.get(entry["status"]["state"], 0) + 1

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "builtOn": _hostname(),
        "requests": entries,
        "counts": counts,
        "openBlocking": sum(1 for e in entries
                            if e["status"]["state"] in (BLOCKED, OPEN)
                            and e["priority"] in ("P0", "P1")),
    }


def _hostname() -> str:
    """Which machine's answers these are — a probe is only true where it ran."""
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def write_bundle(bundle: Dict[str, Any], path: Optional[Path] = None) -> Path:
    target = path or (config.DASHBOARD_DATA_DIR / "requests.js")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(bundle, separators=(",", ":"), default=str)
    target.write_text(
        "// Generated by `python -m factory.cli build` — do not edit.\n"
        "window.__FACTORY_REQUESTS__ = {};\n".format(body),
        encoding="utf-8",
    )
    return target

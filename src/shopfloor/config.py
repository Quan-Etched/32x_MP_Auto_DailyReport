"""Where everything lives, and nothing else.

Every host, path and credential this tool touches is named here once, so a
reader can answer "what does it talk to" without grepping, and a station box
with a different layout is configured rather than patched.

THE ONE RULE
------------
Nothing in this module reaches the network. Import it to find out *where* the
data is; import ``sfis`` or ``eos`` to go get it.
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    """Read ``.env`` beside the repo into the environment, without overriding it.

    Same convention as ``Analysis``, for the same reason: the credentials this
    tool needs belong in a chmod-600 file on the host that runs it, not in a
    shell profile and not in git. Real environment variables always win, so a
    systemd unit or a one-off ``SFIS_BASE=... python3 -m shopfloor`` overrides
    the file rather than fighting it.
    """
    here = Path(__file__).resolve().parents[2] / ".env"
    if not here.is_file():
        return
    for line in here.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# --- the two upstreams -------------------------------------------------------

#: The TY2 receiver (github.com/etched-ai/ty2-receiver), reachable on the
#: Tailnet as ``pega-sfis`` / 100.73.44.61. It holds Pega's linking + process
#: payloads: the parent<->component graph and the route/station events.
#: HTTPS uses a self-signed cert, hence SFIS_VERIFY defaulting to off — the
#: transport is already the Tailnet, which is what is actually authenticating
#: the host. Point at ``http://pega-sfis:42891`` to skip TLS entirely.
SFIS_BASE = os.environ.get("SFIS_BASE", "https://pega-sfis").rstrip("/")
SFIS_VERIFY = os.environ.get("SFIS_VERIFY", "0") not in {"0", "false", "no", ""}

#: Read auth. The receiver accepts a bearer read token, basic auth, or a session
#: cookie; a token is preferred for scripts and is the only one of the three
#: that cannot also write. Basic auth is the fallback because it is what the
#: team already has.
SFIS_TOKEN = os.environ.get("SFIS_TOKEN", "").strip()
SFIS_USER = os.environ.get("SFIS_USER", "etched").strip()
SFIS_PASSWORD = os.environ.get("SFIS_PASSWORD", "").strip()

#: EOS external test-log API — the source of Etched's own test records. Private
#: address (corporate network or VPN) behind Etched's internal PKI, so it needs
#: a CA bundle; ``Analysis/certs`` already holds one and ``make trust`` in that
#: repo installs it. See Analysis/docs/api-usage.md for the call flow.
EOS_BASE = os.environ.get(
    "EOS_BASE", "https://eos.core.etched.com/api/external/v1/test-logs"
).rstrip("/")
EOS_API_KEY = os.environ.get("EOS_API_KEY", "").strip()
EOS_CA_BUNDLE = os.environ.get("EOS_CA_BUNDLE", "").strip()

#: ESVM station controllers. pega2 provisions VBB, pega3 drives the module
#: stations, pega4 L10, pega5 L11, pega6 TIM. They are the only source of the
#: slot -> unit-serial mapping inside a fixture run, which is why EOS alone
#: cannot say which of eight modules failed. Optional: a graph built without
#: them is correct, just coarser.
PEGA_HOSTS = tuple(
    h for h in os.environ.get("PEGA_HOSTS", "pega3,pega4,pega5").split(",") if h.strip()
)
PEGA_PORT = int(os.environ.get("PEGA_PORT", "3000"))

# --- local state -------------------------------------------------------------

ROOT = Path(os.environ.get("SHOPFLOOR_ROOT", Path(__file__).resolve().parents[2]))

#: Immutable, timestamped copies of what the upstreams said. This directory is
#: the whole point of the tool: it is what still answers when pega-sfis is down.
SNAPSHOT_DIR = Path(os.environ.get("SHOPFLOOR_SNAPSHOTS", ROOT / "snapshots"))

#: Rendered YAML. Derived, disposable, regenerable from any snapshot.
OUT_DIR = Path(os.environ.get("SHOPFLOOR_OUT", ROOT / "out"))

#: ``Analysis``'s station registry is imported rather than copied — it is the
#: verified mapping from (EOS level, suite) onto the line's station names, and a
#: second copy would drift the first time the line renames a suite. A built-in
#: fallback in ``stations.py`` keeps this tool runnable on a box without it.
ANALYSIS_SRC = Path(
    os.environ.get("ANALYSIS_SRC", Path.home() / "project" / "Analysis" / "src")
)

#: Network timeouts. Short on purpose: every caller degrades to "source
#: unavailable" rather than hanging, because a partial graph that says which
#: part is missing beats no graph at all.
TIMEOUT = float(os.environ.get("SHOPFLOOR_TIMEOUT", "30"))

#: How far back to ask EOS for runs. Test records older than this are simply not
#: collected, and the manifest records the window so a reader can tell "no test"
#: from "outside the window".
EOS_DAYS = int(os.environ.get("SHOPFLOOR_EOS_DAYS", "120"))

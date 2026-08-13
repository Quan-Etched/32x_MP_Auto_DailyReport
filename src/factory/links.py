"""Where a run came from — the "Source" column of the drill-down table.

ONE PLACE, DELIBERATELY EMPTY BY DEFAULT
----------------------------------------
The templates below are unset, and the Source column degrades to a link to OCP
Logs plus the identifier to copy. That is not laziness: it is the difference
between one honest click and a column of dead links.

``ocplogs.core.etched.com`` is behind Okta SSO, so its routes cannot be read
from here — they had to be observed in a browser by someone logged in. They
have been, and the answer is no.

**CONFIRMED 2026-08-13: there is no per-run OCP URL.** Someone logged in
selected three different runs — two MLT, one HTT — and the address bar stayed
``https://ocplogs.core.etched.com`` for all of them while the detail pane
changed completely. The RUNS tab holds both its filter and its selection in
memory, so neither a run link nor a pre-filtered search link can be
constructed. Both templates below stay empty, and this is settled rather than
open: do not spend another afternoon looking for the route.

Two things that investigation did establish, and that are worth more than the
link would have been:

* **OCP's RUN ID column is our ``runId``**, character for character
  (``mlt_2026.220.0-git2f1c2f23_20260812_013949``). OCP Logs is a second reader
  of the same records this ETL collects — which is why ``runs.html`` is already
  the per-run permalink that OCP itself cannot offer.
* **OCP's only run-identifying filter is DUT SERIAL** (with LEVEL, FROM/TO,
  FAMILY, SUITE, VERSION and STATION). There is no run-id box, so the thing to
  hand a reader who needs to open OCP by hand is the serial and the date, not
  the run id.

**pega4 cannot be linked at all.** Its suite-run pages use IDs it mints itself
(``/suite_run/L10_RIN_run_a868a9eb``); that identifier appears nowhere in the EOS
payload, so there is no way to derive the URL from a run we collected. Do not add
a pega4 column without first finding a field that carries that ID.

TO TURN THE COLUMN INTO DEEP LINKS
----------------------------------
Fill in a template — here, or via the environment without touching code::

    FACTORY_OCP_RUN_URL='https://ocplogs.core.etched.com/run/{runId}?level={level}'

Available placeholders: ``{base}``, ``{runId}``, ``{level}``, ``{dut}``,
``{suite}``, ``{version}``, ``{release}``, ``{day}``. Substitution happens in the
browser (``runtable.js``), so the bundle carries the template once instead of
~1200 expanded URLs.
"""

from __future__ import annotations

import os
from typing import Any, Dict

#: The OCP Logs web UI. Valid on its own — the RUNS tab is its landing page.
DEFAULT_OCP_BASE = "https://ocplogs.core.etched.com"

#: Per-run permalink. Empty because OCP has none — confirmed by observation,
#: not assumed. Kept as an override so a future OCP that grows real routes needs
#: an environment variable rather than a patch.
DEFAULT_RUN_URL_TEMPLATE = ""

#: Pre-filtered search — a day, a release or a DUT. Empty for the same reason:
#: the RUNS tab keeps its filter in memory, so there is no URL to point at.
DEFAULT_SEARCH_URL_TEMPLATE = ""


#: Jira browse root, for the ticket keys the daily tracker records in its notes
#: column. Empty by default and for the same reason as the OCP templates above:
#: the keys are real (``ETCH-38567``), but no URL carrying one has been observed
#: from here, and a column of plausible-looking dead links is worse than plain
#: text. Set FACTORY_JIRA_BASE once someone confirms the site, e.g.
#: ``https://<site>.atlassian.net/browse``.
DEFAULT_JIRA_BASE = ""


def ocp_base() -> str:
    return os.environ.get("FACTORY_OCP_BASE", DEFAULT_OCP_BASE).rstrip("/")


def jira_base() -> str:
    return os.environ.get("FACTORY_JIRA_BASE", DEFAULT_JIRA_BASE).strip().rstrip("/")


def run_url_template() -> str:
    return os.environ.get("FACTORY_OCP_RUN_URL", DEFAULT_RUN_URL_TEMPLATE).strip()


def search_url_template() -> str:
    return os.environ.get("FACTORY_OCP_SEARCH_URL", DEFAULT_SEARCH_URL_TEMPLATE).strip()


def describe() -> Dict[str, Any]:
    """What the dashboard needs to render the Source column."""
    run_template = run_url_template()
    search_template = search_url_template()
    return {
        "base": ocp_base(),
        "runTemplate": run_template or None,
        "searchTemplate": search_template or None,
        # The page says "OCP ↗" when it can link the run itself and "search ↗"
        # when all it can do is open the tool — the reader should be able to tell
        # those apart before clicking.
        "runLinksResolve": bool(run_template),
        "hint": "Set FACTORY_OCP_RUN_URL to link runs directly; see src/factory/links.py",
    }


def expand(template: str, run: Dict[str, Any]) -> str:
    """Fill a template from a bundle run row. Mirrors ``runtable.js``'s expand().

    Kept here so the substitution has a testable Python implementation even
    though the browser is what normally does it.
    """
    if not template:
        return ""
    mapping = {
        "base": ocp_base(),
        "runId": run.get("i") or "",
        "level": run.get("l") or "",
        "dut": run.get("d") or "",
        "suite": run.get("su") or "",
        "version": run.get("v") or "",
        "release": run.get("r") or "",
        "day": run.get("day") or "",
    }
    out = template
    for key, value in mapping.items():
        out = out.replace("{" + key + "}", str(value))
    return out

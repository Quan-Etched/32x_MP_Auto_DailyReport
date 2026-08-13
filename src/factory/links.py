"""Where a run came from — the "Source" column of the drill-down table.

ONE PLACE, DELIBERATELY EMPTY BY DEFAULT
----------------------------------------
The templates below are unset, and the Source column degrades to a link to the
OCP Logs search page plus a copy-the-run-ID button. That is not laziness: it is
the difference between one honest click and a column of dead links.

What is known:

* Our ``runId`` (``L10_RIN_2026.220.0-git13b172eb_20260810_234450``) is the same
  string OCP Logs shows in its RUN ID column, so a per-run OCP route almost
  certainly keys on it.
* ``ocplogs.core.etched.com`` is behind Okta SSO. Fetching it with the internal
  CA returns the sign-in page, so its routes cannot be read from here — they
  have to be observed in a browser by someone logged in.
* A screenshot of the RUNS tab with FROM, TO, SUITE and FAMILY all set showed a
  bare ``https://ocplogs.core.etched.com`` in the address bar, which suggests
  that page keeps its filter state in memory rather than in the URL. If that
  holds, ``SEARCH_URL_TEMPLATE`` has nothing to point at and should stay empty.

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

#: Per-run permalink. Empty until someone logged into OCP confirms the route.
DEFAULT_RUN_URL_TEMPLATE = ""

#: Pre-filtered search — a day, a release or a DUT. Empty for the same reason,
#: and possibly not expressible as a URL at all (see above).
DEFAULT_SEARCH_URL_TEMPLATE = ""


def ocp_base() -> str:
    return os.environ.get("FACTORY_OCP_BASE", DEFAULT_OCP_BASE).rstrip("/")


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

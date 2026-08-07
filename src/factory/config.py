"""Configuration: paths, environment, and the factory-local timezone.

Everything the ETL needs to know about *where* things live is here. The API key
is read from the environment only — it is never persisted and never reaches the
dashboard bundle.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
DASHBOARD_DIR = REPO_ROOT / "dashboard"
DASHBOARD_DATA_DIR = DASHBOARD_DIR / "data"

#: Normalized run table produced by ``collect`` and consumed by ``build``.
RUNS_JSON = PROCESSED_DIR / "runs.json"

#: Browser bundle: ``window.__FACTORY_METRICS__ = {...}``. Written as JS rather
#: than JSON so the dashboard also opens over ``file://`` (fetch() of a local
#: .json is blocked by CORS in Chrome).
DASHBOARD_BUNDLE = DASHBOARD_DATA_DIR / "metrics.js"

DEFAULT_BASE_URL = "https://eos.core.etched.com/api/external/v1/test-logs"

#: Hour buckets are cut in this zone, so "the 09:00 hour" means what the floor
#: means by it. Stored timestamps stay UTC epoch seconds.
DEFAULT_TZ = "America/Los_Angeles"

DEFAULT_LEVEL = "l10"

#: Artifact roles named in the API doc.
ROLE_SUITE_SUMMARY = "suite_summary"
ROLE_SUITE_CONFIG = "suite_config"


def load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    """Populate ``os.environ`` from a .env file, without overriding real env vars.

    Deliberately minimal (KEY=VALUE, ``#`` comments) so the project keeps a
    zero-dependency install.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def base_url() -> str:
    return os.environ.get("EOS_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def timezone_name() -> str:
    return os.environ.get("FACTORY_TZ", DEFAULT_TZ)


def default_level() -> str:
    return os.environ.get("FACTORY_LEVEL", DEFAULT_LEVEL)


def api_key() -> str:
    """Return the EOS API key, or raise with an actionable message."""
    load_dotenv()
    key = os.environ.get("EOS_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "EOS_API_KEY is not set. Copy .env.example to .env and fill it in, "
            "or export EOS_API_KEY in your shell."
        )
    return key


def ensure_dirs() -> None:
    for directory in (RAW_DIR, PROCESSED_DIR, DASHBOARD_DATA_DIR):
        directory.mkdir(parents=True, exist_ok=True)

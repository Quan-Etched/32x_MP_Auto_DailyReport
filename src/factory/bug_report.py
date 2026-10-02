"""File one Jira bug per failing test case, with every serial in the body.

The morning note (``daily_report``) counts failures and links a ticket when
the sheet already has one. It does not open tickets. This module does that
job for a named set of cases — by default ``SohuLaneRepairTestCase`` and
``SohuVminTestCase`` — and parents each bug under one epic.

One bug per case, not per serial. The serial list stays in the ticket.
Each occurrence — day, station, release, run link — goes in a CSV under
``daily/bug-drafts``. The ticket names that file instead of pasting the
rows. When the file moves to the server, set ``occurrencesUrl`` and the
ticket carries that link instead.
A unit that failed the same case on two days is one serial and two CSV rows.

Nothing is filed unless ``--create`` is passed. A draft that looks right
and a ticket that was opened by a dry run are not the same thing.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import ssl
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import build_dailyexcel, build_errors, config, daily_report, links, stations

DEFAULT_CASES = ("SohuLaneRepairTestCase", "SohuVminTestCase")
DEFAULT_EPIC = "ETCH-44407"
DEFAULT_ISSUE_TYPE = "Bug"

#: Where occurrence CSVs are uploaded. The ticket links the file; it does not
#: paste the rows. Override with DRIVE_OCCURRENCES_FOLDER.
DEFAULT_DRIVE_FOLDER = "1ZTzz3FzoNXw-UVmDhqw5xu_cqH78Gs0g"
DRIVE_FOLDER_URL = (
    "https://drive.google.com/drive/folders/" + DEFAULT_DRIVE_FOLDER)

OCCURRENCE_COLUMNS = ("sn", "day", "station", "release", "run", "url")

_EXTRAS = ("l10", "l11")

_URL_RE = re.compile(r"https?://[^\s<>]+")
_JIRA_SUMMARY_MAX = 255


class NoHits(Exception):
    """None of the requested cases failed in the tracker window."""


class JiraError(Exception):
    """The Jira API refused the call, or the credentials are missing."""

    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------- collect

def _blocks(tab: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The day tab plus the L10/L11 blocks hung off it, when those exist."""
    found = [tab]
    for key in _EXTRAS:
        block = tab.get(key)
        if isinstance(block, dict) and block.get("columns"):
            found.append(block)
    return found


def _release(row: Sequence[Any], slot: Optional[Dict[str, Any]]) -> Optional[str]:
    if not slot:
        return None
    token = daily_report._release_token(
        daily_report._cell(row, slot.get("version")).get("v"))
    return token or daily_report._release_token(slot.get("sub"))


def _link(row: Sequence[Any], at: Optional[int]) -> Dict[str, str]:
    cell = daily_report._cell(row, at)
    href = str(cell.get("h") or "").strip()
    text = str(cell.get("v") or "").strip()
    if href:
        return {"url": href, "run": text}
    if text.startswith("http://") or text.startswith("https://"):
        return {"url": text, "run": ""}
    return {"url": "", "run": text}


def collect_hits(
    bundle: Dict[str, Any],
    cases: Sequence[str],
    day_from: Optional[str] = None,
    day_to: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """One row per (serial, day, station, case) the tracker marked failed.

    A pass is never a hit, even if a stale failure name is still in the
    cell. The failure column is what names the case; the result column is
    what says the unit actually failed.
    """
    wanted = {case.strip() for case in cases if case and case.strip()}
    hits: List[Dict[str, Any]] = []
    seen = set()
    for tab in bundle.get("tabs") or []:
        for block in _blocks(tab):
            day = block.get("day") or tab.get("day") or ""
            if day_from and day < day_from:
                continue
            if day_to and day > day_to:
                continue
            slots = daily_report._station_slots(block)
            jira_at = daily_report._jira_at(block)
            sn_at = daily_report._sn_at(block)
            pairs = build_errors._pairs(block.get("columns") or [])
            for row in block.get("rows") or []:
                serial = (daily_report._cell(row, sn_at).get("v") or "").strip()
                if not serial:
                    continue
                keys, _prose = daily_report._notes(row, jira_at)
                for fail_at, link_at, station in pairs:
                    slot = slots.get(station or "")
                    tone = daily_report._tone(
                        row, slot.get("result") if slot else None)
                    if tone == "pass":
                        continue
                    for case in build_errors._cases(daily_report._cell(row, fail_at)):
                        if case not in wanted:
                            continue
                        link = _link(row, link_at)
                        identity = (serial, day, station or "", case,
                                    link["run"], link["url"])
                        if identity in seen:
                            continue
                        seen.add(identity)
                        label = ""
                        if station:
                            label = stations.label_of(station) or station
                        hits.append({
                            "sn": serial,
                            "day": day,
                            "station": station or "",
                            "stationLabel": label or (station or ""),
                            "release": _release(row, slot),
                            "case": case,
                            "run": link["run"],
                            "url": link["url"],
                            "jira": list(keys),
                        })
    hits.sort(key=lambda hit: (
        hit["case"], hit["day"], hit["station"], hit["sn"], hit["run"]))
    return hits


def _catalogue_lines(case: str, by_case: Dict[str, List[Dict[str, Any]]]
                     ) -> List[Dict[str, str]]:
    """Every catalogue code that names this case. Not a chosen diagnosis.

    A case often has more than one code, because the code says *which way*
    it failed and the tracker only says that it did. Listing them all is
    the honest bug note; picking one would invent a root cause.
    """
    lines = []
    for entry in by_case.get(case) or []:
        code = (entry.get("code") or "").strip()
        message = (entry.get("message") or "").strip()
        if code or message:
            lines.append({"code": code, "message": message})
    return lines


def _unique(values: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


# --------------------------------------------------------------------- render

def _summary(case: str, serials: Sequence[str]) -> str:
    noun = "serial" if len(serials) == 1 else "serials"
    return "{} failure ({} {})".format(case, len(serials), noun)


def render_markdown(draft: Dict[str, Any]) -> str:
    """A bug report a person can paste, or read before ``--create``."""
    hits: List[Dict[str, Any]] = draft["hits"]
    serials: List[str] = draft["serials"]
    stations_seen = _unique(hit["stationLabel"] or hit["station"] for hit in hits)
    releases = _unique(hit.get("release") or "" for hit in hits)
    days = _unique(hit["day"] for hit in hits)
    lines = [
        "Bug: {}".format(draft["summary"]),
        "Epic: {}".format(draft["epic"]),
        "Issue type: {}".format(draft["issueType"]),
        "",
        "Summary",
        "{} failed on {}.".format(
            draft["case"],
            ", ".join(stations_seen) if stations_seen else "the line"),
        "",
        "Environment",
        "Stations: {}".format(", ".join(stations_seen) or "unknown"),
        "Releases: {}".format(", ".join(releases) or "unknown"),
        "Days: {}".format(
            days[0] if len(days) == 1 else "{} .. {}".format(days[0], days[-1])
            if days else "unknown"),
    ]
    if draft.get("trackerUrl"):
        lines.append("Test tracker: {}".format(draft["trackerUrl"]))
    lines.extend([
        "",
        "Steps",
        "Run the station suite. The failing step is {}.".format(draft["case"]),
        "",
        "Expected",
        "{} passes.".format(draft["case"]),
        "",
        "Actual",
        "{} failed on {} serial{} ({} occurrence{}).".format(
            draft["case"], len(serials), "" if len(serials) == 1 else "s",
            len(hits), "" if len(hits) == 1 else "s"),
    ])
    catalogue = draft.get("catalogue") or []
    if catalogue:
        lines.append("")
        lines.append(
            "Catalogue wording for this case. More than one code means the "
            "tracker did not say which way it failed:")
        for entry in catalogue:
            lines.append("- {}: {}".format(entry["code"], entry["message"]))
    lines.extend(["", "Affected serial numbers", *serials, "", "Occurrences"])
    lines.append(_occurrences_target(draft)[0])
    existing = draft.get("existingJira") or []
    if existing:
        lines.extend(["", "Already on the tracker"])
        for key in existing:
            lines.append("- {}".format(daily_report.jira_url(key)))
    lines.append("")
    return "\n".join(lines)


def _text(value: str, href: Optional[str] = None) -> Dict[str, Any]:
    node: Dict[str, Any] = {"type": "text", "text": value}
    if href:
        node["marks"] = [{"type": "link", "attrs": {"href": href}}]
    return node


def _para(*nodes: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "paragraph", "content": list(nodes) or [_text("")]}


def _heading(value: str) -> Dict[str, Any]:
    return {"type": "heading", "attrs": {"level": 2},
            "content": [_text(value)]}


def _bullets(items: Sequence[str]) -> Dict[str, Any]:
    return {
        "type": "bulletList",
        "content": [
            {"type": "listItem", "content": [_para(_text(item))]}
            for item in items
        ],
    }


def _inline(text: str) -> List[Dict[str, Any]]:
    """Plain text with http(s) URLs turned into ADF links."""
    nodes: List[Dict[str, Any]] = []
    pos = 0
    for match in _URL_RE.finditer(text or ""):
        if match.start() > pos:
            nodes.append(_text(text[pos:match.start()]))
        url = match.group(0).rstrip(".,);")
        nodes.append(_text(url, url))
        pos = match.start() + len(url)
        if pos < match.end():
            nodes.append(_text(text[pos:match.end()]))
            pos = match.end()
    if pos < len(text or ""):
        nodes.append(_text(text[pos:]))
    return nodes or [_text("")]


def adf_from_plain(text: str) -> Dict[str, Any]:
    """Turn an edited ticket body into the ADF Jira's create API wants.

    Blank lines separate paragraphs. Consecutive ``- `` lines become a
    bullet list. URLs in the text are linked.
    """
    content: List[Dict[str, Any]] = []
    bullets: List[str] = []

    def flush_bullets() -> None:
        if bullets:
            content.append(_bullets(list(bullets)))
            bullets.clear()

    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        stripped = raw.rstrip()
        if stripped.startswith("- "):
            bullets.append(stripped[2:])
            continue
        flush_bullets()
        if not stripped:
            continue
        content.append(_para(*_inline(stripped)))
    flush_bullets()
    if not content:
        content.append(_para(_text("")))
    return {"type": "doc", "version": 1, "content": content}


def apply_ticket_edits(draft: Dict[str, Any],
                       summary: Optional[str] = None,
                       markdown: Optional[str] = None) -> Dict[str, Any]:
    """Overlay the operator's preview edits onto a generated draft."""
    if summary is not None:
        text = str(summary).strip()
        if text:
            draft["summary"] = text[:_JIRA_SUMMARY_MAX]
    if markdown is not None:
        body = str(markdown).replace("\r\n", "\n")
        if not body.endswith("\n"):
            body += "\n"
        draft["markdown"] = body
        draft["adf"] = adf_from_plain(body)
    return draft


def render_adf(draft: Dict[str, Any]) -> Dict[str, Any]:
    """Atlassian document for the issue description. API v3 requires this."""
    hits: List[Dict[str, Any]] = draft["hits"]
    serials: List[str] = draft["serials"]
    content: List[Dict[str, Any]] = [
        _heading("Summary"),
        _para(_text("{} failed.".format(draft["case"]))),
        _heading("Environment"),
    ]
    stations_seen = _unique(hit["stationLabel"] or hit["station"] for hit in hits)
    releases = _unique(hit.get("release") or "" for hit in hits)
    days = _unique(hit["day"] for hit in hits)
    env = [
        "Stations: {}".format(", ".join(stations_seen) or "unknown"),
        "Releases: {}".format(", ".join(releases) or "unknown"),
        "Days: {}".format(
            days[0] if len(days) == 1 else "{} .. {}".format(days[0], days[-1])
            if days else "unknown"),
        "Epic: {}".format(draft["epic"]),
    ]
    if draft.get("trackerUrl"):
        env.append("Test tracker: {}".format(draft["trackerUrl"]))
    content.append(_bullets(env))
    content.extend([
        _heading("Steps"),
        _para(_text(
            "Run the station suite. The failing step is {}.".format(draft["case"]))),
        _heading("Expected"),
        _para(_text("{} passes.".format(draft["case"]))),
        _heading("Actual"),
        _para(_text(
            "{} failed on {} serial{} ({} occurrence{}).".format(
                draft["case"], len(serials), "" if len(serials) == 1 else "s",
                len(hits), "" if len(hits) == 1 else "s"))),
    ])
    catalogue = draft.get("catalogue") or []
    if catalogue:
        content.append(_para(_text(
            "Catalogue wording for this case. The tracker does not say which "
            "code applies:")))
        content.append(_bullets([
            "{}: {}".format(entry["code"], entry["message"])
            for entry in catalogue
        ]))
    content.extend([
        _heading("Affected serial numbers"),
        {
            "type": "codeBlock",
            "content": [_text("\n".join(serials))],
        },
        _heading("Occurrences"),
    ])
    target, linked = _occurrences_target(draft)
    if linked:
        content.append(_para(_text(target, target)))
    else:
        content.append(_para(_text(target)))
    existing = draft.get("existingJira") or []
    if existing:
        content.append(_heading("Already on the tracker"))
        content.append(_bullets([
            daily_report.jira_url(key) for key in existing
        ]))
    return {"type": "doc", "version": 1, "content": content}


def draft_for(
    case: str,
    hits: Sequence[Dict[str, Any]],
    epic: str,
    issue_type: str,
    tracker_url: str,
    by_case: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    serials = _unique(hit["sn"] for hit in hits)
    existing: List[str] = []
    for hit in hits:
        for key in hit.get("jira") or []:
            if key not in existing:
                existing.append(key)
    project = epic.split("-", 1)[0]
    draft: Dict[str, Any] = {
        "case": case,
        "epic": epic,
        "project": project,
        "issueType": issue_type,
        "summary": _summary(case, serials),
        "serials": serials,
        "hits": list(hits),
        "catalogue": _catalogue_lines(case, by_case),
        "trackerUrl": tracker_url,
        "existingJira": existing,
    }
    draft["markdown"] = render_markdown(draft)
    draft["adf"] = render_adf(draft)
    return draft


def build_drafts(
    bundle: Dict[str, Any],
    cases: Sequence[str] = DEFAULT_CASES,
    epic: str = DEFAULT_EPIC,
    issue_type: str = DEFAULT_ISSUE_TYPE,
    day_from: Optional[str] = None,
    day_to: Optional[str] = None,
    tracker_url: Optional[str] = None,
    by_case: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> List[Dict[str, Any]]:
    """One draft per requested case that actually failed. Empty cases are omitted."""
    wanted = [case.strip() for case in cases if case and case.strip()]
    hits = collect_hits(bundle, wanted, day_from=day_from, day_to=day_to)
    if not hits:
        raise NoHits(
            "no failures of {} in the tracker".format(", ".join(wanted)))
    catalogue = by_case if by_case is not None else build_errors.by_case(
        build_errors.catalogue())
    tracker = tracker_url
    if tracker is None:
        tracker = (bundle.get("source") or {}).get("url") or build_dailyexcel.source_url()
    drafts = []
    for case in wanted:
        group = [hit for hit in hits if hit["case"] == case]
        if not group:
            continue
        drafts.append(draft_for(
            case, group, epic.strip(), issue_type, tracker or "", catalogue))
    return drafts


def occurrences_filename(draft: Dict[str, Any]) -> str:
    return "{}-occurrences.csv".format(draft["case"])


def occurrences_relpath(draft: Dict[str, Any]) -> str:
    """Repo-relative path. This is what the ticket shows until a server URL exists."""
    return "daily/bug-drafts/{}".format(occurrences_filename(draft))


def _occurrences_target(draft: Dict[str, Any]) -> Tuple[str, bool]:
    """``(text, is_link)``. A server URL is a link; the local path is text."""
    url = (draft.get("occurrencesUrl") or "").strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url, True
    return occurrences_relpath(draft), False


def publish_local_csv(draft: Dict[str, Any],
                      directory: Optional[Path] = None) -> Path:
    """Write the occurrences CSV under ``daily/bug-drafts``."""
    root = directory or (config.REPO_ROOT / "daily" / "bug-drafts")
    root.mkdir(parents=True, exist_ok=True)
    path = root / occurrences_filename(draft)
    path.write_text(occurrences_csv(draft), encoding="utf-8")
    draft["markdown"] = render_markdown(draft)
    draft["adf"] = render_adf(draft)
    return path


def occurrences_csv(draft: Dict[str, Any]) -> str:
    """One row per occurrence. This is what the Drive file contains."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(OCCURRENCE_COLUMNS)
    for hit in draft["hits"]:
        writer.writerow([
            hit["sn"],
            hit["day"],
            hit.get("stationLabel") or hit.get("station") or "",
            hit.get("release") or "",
            hit.get("run") or "",
            hit.get("url") or "",
        ])
    return buffer.getvalue()


def drive_folder_id() -> str:
    return os.environ.get("DRIVE_OCCURRENCES_FOLDER", "").strip() or DEFAULT_DRIVE_FOLDER


def apply_occurrences_url(draft: Dict[str, Any], url: str) -> Dict[str, Any]:
    """Point the ticket at the uploaded CSV and rebuild the description."""
    draft["occurrencesUrl"] = url
    draft["markdown"] = render_markdown(draft)
    draft["adf"] = render_adf(draft)
    return draft


def render_all(drafts: Sequence[Dict[str, Any]]) -> str:
    return "\n".join(draft["markdown"].rstrip() for draft in drafts) + "\n"


def write_drafts(drafts: Sequence[Dict[str, Any]], directory: Path) -> List[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for draft in drafts:
        path = directory / "{}.md".format(draft["case"])
        path.write_text(draft["markdown"], encoding="utf-8")
        written.append(path)
        csv_path = directory / occurrences_filename(draft)
        csv_path.write_text(occurrences_csv(draft), encoding="utf-8")
        written.append(csv_path)
    return written


def generate(
    cases: Sequence[str] = DEFAULT_CASES,
    epic: Optional[str] = None,
    issue_type: Optional[str] = None,
    day_from: Optional[str] = None,
    day_to: Optional[str] = None,
    bundle: Optional[Dict[str, Any]] = None,
    fetch: bool = True,
) -> List[Dict[str, Any]]:
    """Load the tracker and build the bug drafts. Does not call Jira."""
    if bundle is not None:
        data = bundle
    elif fetch:
        data = daily_report.refresh(day=day_to)
    else:
        data = daily_report.load_bundle()
    return build_drafts(
        data,
        cases=cases,
        epic=epic or os.environ.get("JIRA_EPIC", "").strip() or DEFAULT_EPIC,
        issue_type=issue_type or os.environ.get(
            "JIRA_ISSUE_TYPE", "").strip() or DEFAULT_ISSUE_TYPE,
        day_from=day_from,
        day_to=day_to,
    )


# --------------------------------------------------------------------- jira

def site() -> str:
    base = links.jira_base()
    if base.endswith("/browse"):
        return base[: -len("/browse")]
    return base


def credentials() -> tuple:
    email = (os.environ.get("JIRA_EMAIL") or os.environ.get("ATLASSIAN_EMAIL")
             or "").strip()
    token = (os.environ.get("JIRA_API_TOKEN") or os.environ.get("ATLASSIAN_API_TOKEN")
             or "").strip()
    if not email or not token:
        raise JiraError(
            "Set JIRA_EMAIL and JIRA_API_TOKEN (an Atlassian API token, "
            "not a password)")
    return email, token


def issue_fields(draft: Dict[str, Any], epic_field: Optional[str] = None
                 ) -> Dict[str, Any]:
    """Create-issue fields. ``epic_field`` is the classic Epic Link id.

    Team-managed projects parent a bug with ``parent``. Company-managed
    projects still use the Epic Link custom field. The caller tries parent
    first and passes the custom field id only on the retry.
    """
    fields: Dict[str, Any] = {
        "project": {"key": draft["project"]},
        "issuetype": {"name": draft["issueType"]},
        "summary": draft["summary"],
        "description": draft["adf"],
    }
    if epic_field:
        fields[epic_field] = draft["epic"]
    else:
        fields["parent"] = {"key": draft["epic"]}
    return fields


class JiraClient:
    """Minimal Jira Cloud client. Stdlib only, same rule as the rest of the ETL."""

    def __init__(self, email: str, token: str, root: Optional[str] = None) -> None:
        self._email = email
        self._token = token
        self._root = (root or site()).rstrip("/")
        self._epic_field: Optional[str] = None
        self._epic_field_loaded = False

    def _request(self, method: str, path: str,
                 body: Optional[Dict[str, Any]] = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        password = "{}:{}".format(self._email, self._token).encode("utf-8")
        request = urllib.request.Request(
            self._root + path,
            data=data,
            method=method,
            headers={
                "Authorization": "Basic {}".format(
                    base64.b64encode(password).decode("ascii")),
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30,
                                         context=ssl.create_default_context()) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise JiraError(_error_text(raw, exc.code), status=exc.code) from exc
        except urllib.error.URLError as exc:
            raise JiraError("Jira is not reachable ({})".format(exc.reason)) from exc
        if not raw:
            return {}
        return json.loads(raw)

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, body: Dict[str, Any]) -> Any:
        return self._request("POST", path, body)

    def put(self, path: str, body: Dict[str, Any]) -> Any:
        return self._request("PUT", path, body)

    def epic_link_field(self) -> Optional[str]:
        if self._epic_field_loaded:
            return self._epic_field
        self._epic_field_loaded = True
        for field in self.get("/rest/api/3/field"):
            if field.get("name") == "Epic Link":
                self._epic_field = field.get("id")
                break
        return self._epic_field

    def find_by_summary(self, summary: str) -> Optional[str]:
        """The existing issue with this exact summary, if Jira already has one."""
        if not summary:
            return None
        escaped = summary.replace("\\", "\\\\").replace('"', '\\"')
        payload = self.post("/rest/api/3/search/jql", {
            "jql": 'summary = "{}" ORDER BY created ASC'.format(escaped),
            "maxResults": 1,
            "fields": ["summary"],
        })
        issues = payload.get("issues") or []
        if not issues:
            return None
        return issues[0].get("key") or None

    def list_filed_issues(self, epic: str) -> List[Dict[str, str]]:
        """Bugs already opened for Daily FA.

        ``parent`` is the team-managed epic. The summary fallback covers a
        company-managed Epic Link, which does not appear as ``parent``.
        """
        queries = [
            "parent = {} ORDER BY created DESC".format(epic),
            'summary ~ "L10 FAT" OR summary ~ "L10 SFT" OR summary ~ "L10 RIN" '
            'OR summary ~ "L6 MLT" OR summary ~ "L6 HTT" '
            "ORDER BY created DESC",
        ]
        out: List[Dict[str, str]] = []
        seen = set()
        for jql in queries:
            token = None
            for _ in range(6):
                body: Dict[str, Any] = {
                    "jql": jql, "maxResults": 50, "fields": ["summary"],
                }
                if token:
                    body["nextPageToken"] = token
                try:
                    payload = self.post("/rest/api/3/search/jql", body)
                except JiraError:
                    break
                for issue in payload.get("issues") or []:
                    key = issue.get("key") or ""
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    fields = issue.get("fields") or {}
                    out.append({
                        "key": key,
                        "summary": fields.get("summary") or "",
                        "url": daily_report.jira_url(key),
                    })
                token = payload.get("nextPageToken")
                if not token:
                    break
            if out:
                break
        return out

    def create_bug(self, draft: Dict[str, Any]) -> str:
        """Create the bug under the epic. Returns the new issue key."""
        try:
            created = self.post(
                "/rest/api/3/issue",
                {"fields": issue_fields(draft)})
        except JiraError as exc:
            if exc.status != 400:
                raise
            epic_field = self.epic_link_field()
            if not epic_field:
                raise
            created = self.post(
                "/rest/api/3/issue",
                {"fields": issue_fields(draft, epic_field=epic_field)})
        key = created.get("key")
        if not key:
            raise JiraError("Jira created an issue but returned no key")
        return key

    def update_description(self, key: str, draft: Dict[str, Any]) -> None:
        """Replace the description. Used when the occurrences link arrives
        after the bug was already opened."""
        self.put("/rest/api/3/issue/{}".format(key), {
            "fields": {"description": draft["adf"]},
        })


def _error_text(raw: str, status: int) -> str:
    try:
        payload = json.loads(raw) if raw else {}
    except ValueError:
        payload = {}
    messages = list(payload.get("errorMessages") or [])
    errors = payload.get("errors") or {}
    if isinstance(errors, dict):
        messages.extend("{}: {}".format(key, value) for key, value in errors.items())
    detail = "; ".join(str(item) for item in messages if item)
    if detail:
        return "Jira HTTP {}: {}".format(status, detail)
    return "Jira HTTP {}".format(status)


def upload_occurrences_csv(draft: Dict[str, Any], token: Optional[str] = None,
                           folder_id: Optional[str] = None) -> str:
    """Upload the occurrences CSV into the Drive folder. Returns its link.

    ``GOOGLE_ACCESS_TOKEN`` is a Drive OAuth token with file-create scope.
    The folder is the one the manufacturing notes already use.
    """
    token = (token or os.environ.get("GOOGLE_ACCESS_TOKEN")
             or os.environ.get("DRIVE_ACCESS_TOKEN") or "").strip()
    if not token:
        raise JiraError(
            "Set GOOGLE_ACCESS_TOKEN to upload the occurrences CSV to "
            + DRIVE_FOLDER_URL)
    folder = folder_id or drive_folder_id()
    boundary = "factory-bug-csv"
    metadata = json.dumps({
        "name": occurrences_filename(draft),
        "mimeType": "text/csv",
        "parents": [folder],
    })
    body = (
        "--{b}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        "{meta}\r\n"
        "--{b}\r\n"
        "Content-Type: text/csv\r\n\r\n"
        "{csv}\r\n"
        "--{b}--\r\n"
    ).format(b=boundary, meta=metadata, csv=occurrences_csv(draft))
    request = urllib.request.Request(
        "https://www.googleapis.com/upload/drive/v3/files"
        "?uploadType=multipart&supportsAllDrives=true&fields=id,webViewLink",
        data=body.encode("utf-8"),
        method="POST",
        headers={
            "Authorization": "Bearer {}".format(token),
            "Content-Type": "multipart/related; boundary={}".format(boundary),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60,
                                     context=ssl.create_default_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise JiraError(_error_text(raw, exc.code), status=exc.code) from exc
    except urllib.error.URLError as exc:
        raise JiraError("Drive is not reachable ({})".format(exc.reason)) from exc
    link = payload.get("webViewLink")
    file_id = payload.get("id")
    if not link and file_id:
        link = "https://drive.google.com/file/d/{}/view".format(file_id)
    if not link:
        raise JiraError("Drive uploaded the CSV but returned no link")
    return link


def sft_draft(report: Dict[str, Any], kind: Dict[str, Any],
              epic: str) -> Dict[str, Any]:
    """One bug for one L10 SFT failure family, listing that day's case ids."""
    case_ids = list(kind.get("caseIds") or [])
    test = kind.get("test") or "unclassified failure"
    tests = list(kind.get("tests") or [])
    day = report.get("day") or ""
    label = test
    if tests and (len(tests) > 1 or tests[0] != test):
        label = "{} ({})".format(test, ", ".join(tests))
    summary = "L10 SFT {} {} ({} case ids)".format(day, test, len(case_ids))
    if len(summary) > 250:
        summary = summary[:247] + "..."
    lines = [
        "L10 SFT {} failed {}.".format(day, label),
        "",
        "Case IDs",
        *case_ids,
        "",
        "Chassis that finished failed",
        *(kind.get("sns") or ["none"]),
        "",
        "A chassis that failed and later passed the same day is not in the "
        "failed count. Its case id is still listed above, because the case "
        "did fail.",
    ]
    content: List[Dict[str, Any]] = [
        _heading("Summary"),
        _para(_text(lines[0])),
        _heading("Case IDs"),
        {"type": "codeBlock", "content": [_text("\n".join(case_ids) or "NA")]},
        _heading("Chassis that finished failed"),
        _bullets(kind.get("sns") or ["none"]),
    ]
    if tests:
        content.insert(2, _heading("Tests"))
        content.insert(3, _bullets(tests))
    return {
        "case": test,
        "epic": epic,
        "project": epic.split("-", 1)[0],
        "issueType": DEFAULT_ISSUE_TYPE,
        "summary": summary,
        "adf": {"type": "doc", "version": 1, "content": content},
        "markdown": "\n".join(lines) + "\n",
    }


def stage_kinds(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One family per L10_FLOW_TEST_COVERAGE column C stage."""
    from .build_l10 import stage_of_test

    buckets: Dict[str, Dict[str, Any]] = {}

    def add(stage: str, test: str = "", case_id: str = "",
            serial: str = "") -> None:
        if not stage:
            return
        bucket = buckets.setdefault(stage, {
            "test": stage, "tests": [], "caseIds": [], "sns": [],
        })
        if test and test not in bucket["tests"]:
            bucket["tests"].append(test)
        if case_id and case_id not in bucket["caseIds"]:
            bucket["caseIds"].append(case_id)
        if serial and serial not in bucket["sns"]:
            bucket["sns"].append(serial)

    for kind in report.get("kinds") or []:
        test = kind.get("test") or ""
        stage = stage_of_test(test)
        add(stage, test)
        for case_id in kind.get("caseIds") or []:
            add(stage, test, case_id=case_id)
        for serial in kind.get("sns") or []:
            add(stage, test, serial=serial)
    for row in report.get("rows") or []:
        serial = row.get("sn") or "" if row.get("final") == "fail" else ""
        for test, case_id in zip(row.get("tests") or [],
                                 row.get("caseIds") or []):
            add(stage_of_test(test), test, case_id=case_id or "",
                serial=serial)
        leftover = (row.get("tests") or [])[len(row.get("caseIds") or []):]
        for test in leftover:
            add(stage_of_test(test), test, serial=serial)
    return [buckets[name] for name in buckets]


def fa_draft(report: Dict[str, Any], row: Dict[str, Any],
             epic: str) -> Dict[str, Any]:
    """One bug for one DUT + error-type failure on a Daily FA row."""
    from .build_l10 import as_dri

    labels = {
        "fat": "L10 FAT", "sft": "L10 SFT", "rin": "L10 RIN",
        "mlt": "L6 MLT", "htt": "L6 HTT",
    }
    stage = report.get("stage") or "sft"
    if stage not in labels:
        stage = "sft"
    label = labels[stage]
    day = report.get("day") or ""
    sn = row.get("sn") or ""
    tests = list(row.get("tests") or [])
    if not tests:
        tests = [part.strip() for part in
                 str(row.get("test") or "").splitlines() if part.strip()]
    test = tests[0] if tests else (row.get("test") or "unclassified failure")
    error_type = row.get("errorType") or test
    named = error_type if len(tests) != 1 else test
    summary = "{} {} {} {}".format(label, day, sn, named)
    if len(summary) > 250:
        summary = summary[:247] + "..."
    dri = as_dri(row.get("dri") or "", error_type)
    lines = [
        "{} {} failed {} on {}.".format(label, day, named, sn or "unknown SN"),
        "",
        "Error type: {}".format(error_type),
        "Test case: {}".format("\n".join(tests) or test),
        "Error code: {}".format(row.get("code") or "NA"),
        "DRI: {}".format(dri),
        "Tested at: {}".format(row.get("at") or "unknown"),
        "pega URL: {}".format(row.get("url") or "none"),
    ]
    content: List[Dict[str, Any]] = [
        _heading("Summary"),
        _para(_text(lines[0])),
        _heading("Failure"),
        _bullets([
            "DUT SN: {}".format(sn or "unknown"),
            "Error type: {}".format(error_type),
            "Test case: {}".format(" / ".join(tests) or test),
            "Error code: {}".format(row.get("code") or "NA"),
            "DRI: {}".format(dri),
            "Tested at: {}".format(row.get("at") or "unknown"),
        ]),
    ]
    url = (row.get("url") or "").strip()
    if url:
        content.append(_heading("pega URL"))
        content.append(_para(_text(url, url)))
    return {
        "case": named,
        "epic": epic,
        "project": epic.split("-", 1)[0],
        "issueType": DEFAULT_ISSUE_TYPE,
        "summary": summary,
        "adf": {"type": "doc", "version": 1, "content": content},
        "markdown": "\n".join(lines) + "\n",
    }


def _matches_fa_id(row: Dict[str, Any], row_id: str) -> bool:
    from .build_l10 import group_id

    if row.get("id") == row_id:
        return True
    return group_id(row.get("sn") or "", row.get("errorType") or "",
                    row.get("url") or "") == row_id


def _fa_row(report: Dict[str, Any], row_id: str,
            dri: Optional[str] = None
            ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], str]:
    """Leaves matching ``row_id``, the grouped table row, and any existing URL."""
    from .build_l10 import DRI_OPTIONS, as_dri, expand_fail_rows, group_fail_rows

    report["rows"] = expand_fail_rows(report)
    matches = [item for item in report["rows"] if _matches_fa_id(item, row_id)]
    if not matches:
        raise JiraError("that failure is not in the report")
    already = next((item.get("jira") for item in matches if item.get("jira")), "")
    chosen = (dri or "").strip()
    if chosen not in DRI_OPTIONS:
        chosen = as_dri(matches[0].get("dri") or "",
                        matches[0].get("errorType") or "")
    for item in matches:
        item["dri"] = chosen
    grouped = group_fail_rows(matches)
    row = grouped[0] if grouped else matches[0]
    row["dri"] = chosen
    return matches, row, already or ""


def preview_fa_row(report: Dict[str, Any], row_id: str,
                   epic: Optional[str] = None,
                   dri: Optional[str] = None) -> Dict[str, Any]:
    """The ticket that would be filed, without creating it."""
    parent = (epic or os.environ.get("JIRA_EPIC", "").strip() or DEFAULT_EPIC)
    matches, row, already = _fa_row(report, row_id, dri=dri)
    draft = fa_draft(report, row, parent)
    key = str(already).rstrip("/").rsplit("/", 1)[-1] if already else ""
    return {
        "id": row_id,
        "sn": row.get("sn") or "",
        "test": row.get("test") or "",
        "errorType": row.get("errorType") or "",
        "dri": row.get("dri") or "",
        "epic": draft["epic"],
        "summary": draft["summary"],
        "markdown": draft["markdown"],
        "already": bool(already),
        "key": key,
        "url": already,
    }


def ledger_path() -> Path:
    """Filed Daily FA tickets. Survives a bundle rebuild and a process restart."""
    override = (os.environ.get("FA_JIRAS_PATH") or "").strip()
    if override:
        return Path(override)
    return config.DATA_DIR / "fa_jiras.json"


_LEDGER_LOCK = threading.Lock()


def load_ledger() -> Dict[str, Any]:
    """``rows`` keyed by the table group id, plus ``issues`` synced from Jira."""
    path = ledger_path()
    if not path.is_file():
        return {"rows": {}, "issues": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"rows": {}, "issues": []}
    if not isinstance(data, dict):
        return {"rows": {}, "issues": []}
    if not isinstance(data.get("rows"), dict):
        data["rows"] = {}
    if not isinstance(data.get("issues"), list):
        data["issues"] = []
    return data


def save_ledger(book: Dict[str, Any]) -> None:
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(book, indent=2), encoding="utf-8")
    tmp.replace(path)


def _ticket_summary(report: Dict[str, Any], row: Dict[str, Any]) -> str:
    """The same summary ``fa_draft`` files under, so a rebuild can find it."""
    draft = fa_draft(report, row, DEFAULT_EPIC)
    return draft.get("summary") or ""


def _ledger_hit(book: Dict[str, Any], report: Dict[str, Any],
                row: Dict[str, Any], row_id: str = "") -> str:
    from .build_l10 import group_id

    rows = book.get("rows") or {}
    keys = [
        row_id,
        row.get("id") or "",
        group_id(row.get("sn") or "", row.get("errorType") or "",
                 row.get("url") or ""),
    ]
    for key in keys:
        hit = rows.get(key) or {}
        url = hit.get("url") or ""
        if url:
            return url
    summary = _ticket_summary(report, row)
    if not summary:
        return ""
    for issue in book.get("issues") or []:
        if issue.get("summary") == summary and issue.get("url"):
            return issue["url"]
    return ""


def remembered_url(report: Dict[str, Any], row_id: str,
                   rows: Sequence[Dict[str, Any]]) -> str:
    """A ticket filed earlier for this row, including after the bundle was rebuilt."""
    book = load_ledger()
    for row in rows:
        url = _ledger_hit(book, report, row, row_id)
        if url:
            return url
    return ""


def remember_filed(report: Dict[str, Any], row_id: str,
                   rows: Sequence[Dict[str, Any]],
                   url: str, key: str, summary: str = "") -> None:
    """Keep the link where a later rebuild of dailyfa.js cannot drop it."""
    from .build_l10 import group_id

    if not url:
        return
    entry = {
        "url": url,
        "key": key,
        "day": report.get("day") or "",
        "stage": report.get("stage") or "",
    }
    with _LEDGER_LOCK:
        book = load_ledger()
        stored = book.setdefault("rows", {})
        if row_id:
            stored[row_id] = entry
        for row in rows:
            gid = group_id(row.get("sn") or "", row.get("errorType") or "",
                           row.get("url") or "")
            if gid:
                stored[gid] = dict(entry, summary=_ticket_summary(report, row))
            if row.get("id"):
                stored[row["id"]] = entry
        issues = book.setdefault("issues", [])
        if summary and not any(item.get("summary") == summary for item in issues):
            issues.append({"key": key, "summary": summary, "url": url})
        save_ledger(book)


def apply_ledger_to_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """Fill empty ``jira`` fields from the ledger. Does not clear a link."""
    book = load_ledger()
    for row in report.get("rows") or []:
        if row.get("jira"):
            continue
        url = _ledger_hit(book, report, row, row.get("id") or "")
        if url:
            row["jira"] = url
    return report


def sync_ledger(max_age_s: int = 300) -> Dict[str, Any]:
    """Refresh the issue list from Jira so a restart still knows what was filed.

    A missing token or a search failure leaves the ledger as it is. The page
    still gets whatever was remembered locally.
    """
    with _LEDGER_LOCK:
        book = load_ledger()
        synced = book.get("syncedAt") or ""
        if synced:
            try:
                stamp = datetime.fromisoformat(synced.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - stamp).total_seconds()
            except ValueError:
                age = max_age_s + 1
            if age < max_age_s:
                return book
        try:
            email, token = credentials()
        except JiraError:
            return book
        epic = os.environ.get("JIRA_EPIC", "").strip() or DEFAULT_EPIC
        try:
            issues = JiraClient(email, token).list_filed_issues(epic)
        except JiraError:
            return book
        book["issues"] = issues
        book["syncedAt"] = datetime.now(timezone.utc).replace(
            microsecond=0).isoformat()
        save_ledger(book)
        return book


def file_fa_row(report: Dict[str, Any], row_id: str,
                epic: Optional[str] = None,
                client: Optional["JiraClient"] = None,
                dri: Optional[str] = None,
                summary: Optional[str] = None,
                markdown: Optional[str] = None
                ) -> Dict[str, Any]:
    """File one Jira for one table row. A second click returns the same ticket."""
    parent = (epic or os.environ.get("JIRA_EPIC", "").strip() or DEFAULT_EPIC)
    matches, row, already = _fa_row(report, row_id, dri=dri)
    if not already:
        already = remembered_url(report, row_id, matches)
    if not already:
        draft = apply_ticket_edits(fa_draft(report, row, parent),
                                   summary=summary, markdown=markdown)
        finder = client
        if finder is None:
            try:
                email, token = credentials()
            except JiraError:
                finder = None
            else:
                finder = JiraClient(email, token)
        if finder is not None and hasattr(finder, "find_by_summary"):
            try:
                found = finder.find_by_summary(draft["summary"])
            except JiraError:
                found = None
            if found:
                already = daily_report.jira_url(found)
        if already:
            client = finder
    if already:
        key = str(already).rstrip("/").rsplit("/", 1)[-1]
        for item in matches:
            item["jira"] = already
        remember_filed(report, row_id, matches, already, key,
                       _ticket_summary(report, row))
        return {
            "id": row_id,
            "sn": matches[0].get("sn") or "",
            "test": matches[0].get("test") or "",
            "key": key,
            "url": already,
            "already": True,
        }
    if client is None:
        email, token = credentials()
        client = JiraClient(email, token)
    draft = apply_ticket_edits(fa_draft(report, row, parent),
                               summary=summary, markdown=markdown)
    key = client.create_bug(draft)
    filed = {
        "id": row_id,
        "sn": row.get("sn") or "",
        "test": row.get("test") or "",
        "key": key,
        "url": daily_report.jira_url(key),
        "already": False,
    }
    for item in matches:
        item["jira"] = filed["url"]
    remember_filed(report, row_id, matches, filed["url"], key,
                   draft.get("summary") or "")
    return filed


def file_sft_report(report: Dict[str, Any], epic: Optional[str] = None,
                    client: Optional["JiraClient"] = None
                    ) -> List[Dict[str, Any]]:
    """One Jira bug per coverage-sheet stage that failed that day."""
    parent = (epic or os.environ.get("JIRA_EPIC", "").strip() or DEFAULT_EPIC)
    if client is None:
        email, token = credentials()
        client = JiraClient(email, token)
    filed = []
    for kind in stage_kinds(report):
        if not kind.get("sns"):
            continue
        if not kind.get("tests") and not kind.get("caseIds"):
            continue
        draft = sft_draft(report, kind, parent)
        key = client.create_bug(draft)
        filed.append({
            "test": kind["test"],
            "tests": list(kind.get("tests") or []),
            "key": key,
            "url": daily_report.jira_url(key),
        })
    apply_sft_jiras(report, filed)
    return filed


def apply_sft_jiras(report: Dict[str, Any],
                    filed: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Stamp each run with the ticket for that row's coverage-sheet stage."""
    from .build_l10 import stage_of_test

    by_stage: Dict[str, str] = {}
    by_test: Dict[str, str] = {}
    for item in filed:
        url = item.get("url") or ""
        if not url:
            continue
        stage = item.get("test") or ""
        if stage:
            by_stage[stage] = url
        for test in item.get("tests") or []:
            by_test[test] = url
    if not by_stage and not by_test:
        return report
    for row in report.get("rows") or []:
        urls: List[str] = []
        for test in row.get("tests") or []:
            url = by_test.get(test) or by_stage.get(stage_of_test(test)) or ""
            if url and url not in urls:
                urls.append(url)
        if urls:
            row["jira"] = "; ".join(urls)
    return report


def file_drafts(drafts: Sequence[Dict[str, Any]],
                client: Optional[JiraClient] = None,
                upload: Optional[Any] = None) -> List[Dict[str, str]]:
    """POST each draft. Returns ``[{case, key, url}, ...]`` in draft order.

    ``upload`` turns the occurrence rows into a URL before the ticket is
    opened, so the description can link the CSV instead of listing it.
    """
    if client is None:
        email, token = credentials()
        client = JiraClient(email, token)
    filed = []
    for draft in drafts:
        if upload and not draft.get("occurrencesUrl"):
            apply_occurrences_url(draft, upload(draft))
        key = client.create_bug(draft)
        filed.append({
            "case": draft["case"],
            "key": key,
            "url": daily_report.jira_url(key),
            "occurrencesUrl": draft.get("occurrencesUrl") or "",
        })
    return filed

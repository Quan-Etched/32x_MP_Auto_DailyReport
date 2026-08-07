#!/bin/bash
# One hourly tick: collect from EOS, record fetch state, rebuild both bundles.
#
# Installed as a launchd agent (see deploy/launchd/). Kept as a wrapper rather
# than calling python directly from the plist so that logging, locking and the
# environment are handled in one visible place.
#
# Exit codes: 0 = fetched (whether or not anything changed), 2 = fetch failed.
# "Nothing changed" is a healthy outcome, not an error — the dashboard shows it
# as `last fetch` advancing while `last update` stays put.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

LOG_DIR="$REPO/data/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/refresh.log"
LOCK="$LOG_DIR/.refresh.lock"

DAYS="${FACTORY_REFRESH_DAYS:-30}"

log() { printf '%s  %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"; }

# A slow collection must not overlap the next hour's tick.
if ! mkdir "$LOCK" 2>/dev/null; then
    log "SKIP another refresh is already running ($LOCK)"
    exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

# launchd gives an almost-empty environment; load the key the same way the CLI
# would from an interactive shell.
[ -f "$REPO/.env" ] && set -a && . "$REPO/.env" && set +a

PY="${PYTHON:-python3}"
export PYTHONPATH="$REPO/src"

log "START refresh days=$DAYS"

if ! out="$("$PY" -m factory.cli refresh --days "$DAYS" 2>&1)"; then
    log "FAIL $(printf '%s' "$out" | tail -3 | tr '\n' ' ')"
    printf '%s\n' "$out" >> "$LOG"
    exit 2
fi

printf '%s\n' "$out" | sed 's/^/    /' >> "$LOG"
log "OK $(printf '%s' "$out" | grep -E '^(Fetch|Update)' | tr '\n' ' ')"

# Publish every successful tick, not only when the data changed: the page's
# "last fetch" panel is itself information — it is how a reader knows the
# pipeline is alive rather than silently dead.
if [ "${FACTORY_PUBLISH:-1}" = "1" ]; then
    if pub="$(bash "$REPO/tools/publish.sh" 2>&1)"; then
        log "PUBLISH $pub"
    else
        log "PUBLISH FAILED $(printf '%s' "$pub" | tail -2 | tr '\n' ' ')"
    fi
fi

# Trim the log so an hourly job cannot fill the disk over months.
if [ "$(wc -l < "$LOG")" -gt 5000 ]; then
    tail -2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

exit 0

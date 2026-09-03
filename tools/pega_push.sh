#!/bin/bash
# Warm the controller cache here, then hand it to the dashboard host.
#
# WHY THIS EXISTS
# The box cannot read pega3, pega4 or pega5. Not slowly — measured 2026-09-03,
# one 50-run listing delivered 8,452 of 26,400 bytes in 180 seconds, 46 bytes a
# second, because its Tailscale path to those hosts is relayed through a DERP
# node in Hong Kong. The identical request from a laptop on the same tailnet
# takes 0.09 seconds.
#
# So the laptop fetches and the box borrows: `data/raw/pega/` is a cache keyed
# by host and URL, it is portable between machines, and docs/deploy.md has
# always described it as the transport for a host with no route. This is that,
# on a timer, so the controller half of the dashboard stops depending on
# somebody remembering.
#
#   make pega-push                    warm and push, once
#   make schedule-pega-push-install   hourly at :50, so it lands before the
#                                     box's own :05 rebuild
#
# It does NOT rebuild or publish on the box. The hourly job there already does
# both, and one publish path is worth more than ten minutes of freshness.
#
# HONEST LIMITATION: this is a laptop. Asleep, off the VPN, or shut means no
# push, and the box keeps serving the last cache it got — which is precisely
# the fragility the dashboard host was bought to remove. It is a workaround for
# a network fault, not a design. Delete it when infra gives the box a direct
# path; see "The box cannot reach the controllers" in docs/deploy.md.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

[ -f "$REPO/.env" ] && set -a && . "$REPO/.env" && set +a

# launchd hands over an almost-empty environment — no PYTHONPATH, and the
# Makefile's `export PYTHONPATH := src` never runs because launchd calls this
# script directly. Without this the warm step dies on "No module named
# 'factory'" and every scheduled push exits 2 having sent nothing, while
# `make pega-push` by hand works perfectly. hourly_refresh.sh sets it for the
# same reason.
export PYTHONPATH="$REPO/src"

# macOS tar writes an AppleDouble `._file` header beside every entry unless
# told not to; GNU tar on the far side then warns about each one and 51 of them
# were left littering the box before this was noticed.
MAC_META=""
tar --no-mac-metadata --version >/dev/null 2>&1 && MAC_META="--no-mac-metadata"

# --plan prints the entries a push would send and stops. For checking the
# delta without waiting on a transfer, and for the test that pins it.
PLAN=0
[ "${1:-}" = "--plan" ] && PLAN=1

HOST="${FACTORY_DEPLOY_HOST:-chuck@chuck-dashboard.usw2.i.etched.com}"
DEST="${FACTORY_DEPLOY_PATH:-factory_data_analysis}"
LOG_DIR="$REPO/data/logs"
LOG="$LOG_DIR/pega_push.log"
LOCK="$LOG_DIR/.pega_push.lock"
mkdir -p "$LOG_DIR"

log() { printf '%s  %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG"; }

STAMP="$LOG_DIR/.pega_push.stamp"

# The cache entries the box does not have, one path per line, relative to the
# repo so `tar -C "$REPO" -T -` can read the list directly.
#
# BY NAME, NOT BY TIMESTAMP. The box writes its own pega2 and pega6 entries on
# every build, so its newest mtime is always about now: a "send what is newer
# than the box's latest" delta comes out empty while entries are genuinely
# absent. That was tried and it was wrong. The cache is keyed by a hash of host
# and URL, so a name the box does not have IS an entry it does not have.
# Its whole listing is ~4,500 short names — one cheap stream to know exactly
# what to send, instead of guessing or sending 97 MB.
#
# Plus whatever was written here since the last successful push, which catches
# an entry whose name the box already has but whose contents changed — a day
# listing that was provisional and has since settled.
missing_entries() {
    local theirs="$LOG_DIR/.pega_push.theirs"
    # A generous timeout on purpose: this one small call decides between
    # sending ~20 entries and sending 97 MB, so it is worth waiting out a slow
    # connect for. Observed failing at 20s on a link that then carried the
    # whole cache in under two minutes.
    if ! ssh -o ConnectTimeout=60 -o BatchMode=yes -o ServerAliveInterval=15 \
             "$HOST" "cd $DEST && ls data/raw/pega/ 2>/dev/null" \
             > "$theirs" 2>/dev/null || [ ! -s "$theirs" ]; then
        rm -f "$theirs"
        log "could not read the box's cache listing — sending all of it" >&2
        find data/raw/pega -type f 2>/dev/null
        return
    fi

    ls "$REPO/data/raw/pega/" 2>/dev/null | LC_ALL=C sort > "$theirs.mine"
    LC_ALL=C sort "$theirs" > "$theirs.sorted"
    local missing
    missing="$(LC_ALL=C comm -23 "$theirs.mine" "$theirs.sorted" \
               | sed 's|^|data/raw/pega/|')"
    local changed=""
    [ -f "$STAMP" ] && changed="$(find data/raw/pega -type f -newer "$STAMP" 2>/dev/null)"
    log "the box is missing $(printf '%s\n' "$missing" | sed '/^$/d' | wc -l | tr -d ' ') entries" >&2
    rm -f "$theirs" "$theirs.mine" "$theirs.sorted"
    printf '%s\n%s\n' "$missing" "$changed" | sed '/^$/d' | LC_ALL=C sort -u
}

# --plan: say what a push would send, change nothing.
plan_list() {
    local list
    list="$(missing_entries)"
    if [ -z "$list" ]; then
        echo "nothing to send — the box already has every cache entry"
        exit 0
    fi
    printf '%s\n' "$list"
    printf 'would send %s entries\n' \
        "$(printf '%s\n' "$list" | wc -l | tr -d ' ')"
    exit 0
}

# After the definitions above, because bash resolves a function at call time
# and calling plan_list before it exists just falls through into the push.
if [ "$PLAN" = "1" ]; then
    plan_list
fi

# A slow push must not overlap the next hour's, same rule as the refresh.
. "$REPO/tools/lock.sh"
if ! factory_lock_take "$LOCK" "pega_push"; then
    log "SKIP another push is already running"
    exit 0
fi
trap 'factory_lock_free "$LOCK"' EXIT

# ---------------------------------------------------------------- 1. warm it
# One cheap probe first: no VPN means no controllers, and a push of a cache we
# failed to warm is a push of yesterday's data over yesterday's data. Nothing
# is lost by it, but the log should say what happened.
if ! curl -sS -m 15 -o /dev/null \
        "http://pega4:3000/api/history/data-analysis/suite-runs?per_page=1"; then
    log "SKIP the controllers are not reachable from here — VPN?"
    exit 0
fi

log "START warming the cache"
before="$(find "$REPO/data/raw/pega" -name '*.json' 2>/dev/null | wc -l | tr -d ' ')"
if ! "${PYTHON:-python3}" -m factory.cli pega-stations >>"$LOG" 2>&1; then
    log "FAIL could not read the controllers; not pushing a half-warmed cache"
    exit 2
fi
after="$(find "$REPO/data/raw/pega" -name '*.json' 2>/dev/null | wc -l | tr -d ' ')"
log "cache $before -> $after entries"

# ---------------------------------------------------------------- 2. push it
# No --delete: the box has entries this laptop never fetched (pega2 and pega6
# it reads itself), and deleting them would take away the half that works.
# --timeout so a dropped VPN fails instead of hanging until the next tick.
# Retried, because the link to the box is itself intermittent: the same
# transfer took 25s one hour and died on `poll: timeout` the next, while plain
# ssh to the host kept working. --partial keeps what already crossed, so an
# attempt after a failed one resumes rather than restarting 97 MB.
log "pushing to $HOST"
pushed=0
for attempt in 1 2 3; do
    if rsync -a --partial --timeout=120 \
            -e "ssh -o ConnectTimeout=20 -o BatchMode=yes -o ServerAliveInterval=15" \
            "$REPO/data/raw/pega/" "$HOST:$DEST/data/raw/pega/" >>"$LOG" 2>&1; then
        pushed=1
        [ "$attempt" -gt 1 ] && log "succeeded on attempt $attempt"
        break
    fi
    log "attempt $attempt failed"
    [ "$attempt" -lt 3 ] && sleep $((attempt * 30))
done

# --------------------------------------------------- fallback: one tar stream
# rsync exchanges a file list and then negotiates per file, and over this link
# that is what fails: 4,460 files of round trips die on `poll: timeout` while a
# single stream of the same bytes goes through untouched. Measured the same
# hour — rsync failed three times, a 97 MB tar and a 57 MB bundle both landed.
#
# So the fallback sends only what is new since the last successful push, as one
# stream. COPYFILE_DISABLE because macOS tar otherwise writes an AppleDouble
# `._file` beside every entry, and 51 of them ended up littering the box.
if [ "$pushed" -ne 1 ]; then
    log "rsync will not cross this link; sending the new entries as one stream"
    list="$(missing_entries)"

    if [ -z "$list" ]; then
        log "OK the box already has everything"
        touch "$STAMP"
        exit 0
    fi

    count="$(printf '%s\n' "$list" | wc -l | tr -d ' ')"
    log "streaming $count entries"
    if printf '%s\n' "$list" \
        | COPYFILE_DISABLE=1 tar czf - -C "$REPO" -T - --exclude '._*' \
              $MAC_META 2>/dev/null \
        | ssh -o ConnectTimeout=20 -o BatchMode=yes -o ServerAliveInterval=15 \
              "$HOST" "cd $DEST && tar xzf - && find data/raw/pega -name '._*' -delete" \
              >>"$LOG" 2>&1; then
        pushed=1
        log "streamed $count entries"
    fi
fi

if [ "$pushed" -ne 1 ]; then
    log "FAIL could not reach $HOST by rsync or by stream — network, or the"
    log "     box is down. The box keeps serving the cache it already has;"
    log "     nothing is lost but freshness. The next tick at :50 tries again."
    exit 3
fi

# Only after something actually landed, so a failed push does not narrow what
# the next one considers new.
touch "$STAMP"

log "OK pushed; the box picks it up on its next hourly build at :05"
exit 0

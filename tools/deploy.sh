#!/bin/bash
# Put this checkout on the dashboard host, then rebuild and publish there.
#
# WHY THIS SCRIPT EXISTS
# The box serves 32x-production and collects hourly, but it has no GitHub
# credential and the hourly job never touches the code — it collects, builds
# and publishes whatever tree is already on disk. So code only ever reached
# production by somebody remembering a twelve-line rsync out of docs/deploy.md.
#
# When nobody remembered, nothing said so. On 2026-09-03 the box was still
# serving 75579de while main was eight commits ahead, and three separate fixes
# had been written, committed, and reported as done — including the one that
# put the station list back on the customize page. Each was real; none of them
# was ever on the site. The page carries a build stamp that would have shown it
# in a glance, and nothing compared the two.
#
# So: one command, and it prints the before and after stamps.
#
#   make deploy              rsync, then `make update` on the box
#   make deploy NO_UPDATE=1  rsync only
#   make deploy-status       what is on the box against what is here
#
# WHAT IS NOT SENT, AND WHY IT MATTERS
#   .env             the box's copy carries FACTORY_WEB_ROOT, which is what
#                    makes `make publish` copy into the web root instead of
#                    pushing to gh-pages. Overwrite it with a laptop .env and
#                    the box quietly becomes a laptop; it has happened once.
#   data/            the collected history, including items.sqlite (~233 MB)
#                    and the controller cache. The box's is the real one.
#   dashboard/data/  generated bundles; the box rebuilds them.
#
# --delete IS deliberate: without it a page deleted here lingers there, and
# `make publish` copies it back into the web root from the box's own stale
# tree. rsync will not delete an excluded path unless asked with
# --delete-excluded, which is why the three above survive.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

HOST="${FACTORY_DEPLOY_HOST:-chuck@chuck-dashboard.usw2.i.etched.com}"
DEST="${FACTORY_DEPLOY_PATH:-factory_data_analysis}"
SSH_OPTS=(-o ConnectTimeout=15)

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

box_stamp() {
    ssh "${SSH_OPTS[@]}" "$HOST" \
        "cd $DEST 2>/dev/null && git rev-parse --short HEAD 2>/dev/null" \
        2>/dev/null | tail -1
}

here_stamp() { git -C "$REPO" rev-parse --short HEAD; }

# A hash of everything the deploy actually sends.
#
# The commit alone is not enough, and saying so cost an afternoon: the box can
# sit on the same HEAD as this checkout while its files differ, because a
# deploy carries the WORKING TREE — uncommitted edits included — and because a
# half-finished sync leaves a mixture. `deploy-status` reported "In step" over
# exactly that. This compares content instead, so it answers the question
# somebody actually has: is the box running what I am looking at?
#
# Same exclusions as the rsync, or the two would never agree.
TREE_CMD='find . -type f \
    -not -path "./.git/*" -not -path "./data/*" -not -path "./dashboard/data/*" \
    -not -name ".env" -not -path "*/__pycache__/*" -not -name ".DS_Store" \
    -print0 | LC_ALL=C sort -z | xargs -0 cat 2>/dev/null \
    | { sha256sum 2>/dev/null || shasum -a 256; } | cut -c1-16'

here_tree() { ( cd "$REPO" && eval "$TREE_CMD" ); }
box_tree()  { ssh "${SSH_OPTS[@]}" "$HOST" "cd $DEST && $TREE_CMD" 2>/dev/null | tail -1; }

# ------------------------------------------------------------------- status
if [ "${1:-}" = "--status" ]; then
    there="$(box_stamp)"
    here="$(here_stamp)"
    echo "here: $here"
    echo "box:  ${there:-unreachable}"
    if [ -z "$there" ]; then
        echo "Could not read the box's checkout." >&2
        exit 1
    fi
    if [ "$there" != "$here" ]; then
        behind="$(git -C "$REPO" rev-list --count "$there..HEAD" 2>/dev/null)"
        echo "DRIFTED — the box is ${behind:-?} commits behind this checkout."
        echo "Nothing you commit here is on the site until \`make deploy\` runs."
        exit 1
    fi

    # Same commit is necessary, not sufficient. Compare the files.
    here_files="$(here_tree)"
    box_files="$(box_tree)"
    echo "tree: $here_files (here) vs ${box_files:-unreadable} (box)"
    if [ -z "$box_files" ]; then
        echo "Could not hash the box's tree; the commits match, the files are"
        echo "unverified."
        exit 1
    fi
    if [ "$here_files" != "$box_files" ]; then
        echo "DRIFTED — same commit, different files. Uncommitted work here"
        echo "that never shipped, or a deploy that did not finish. \`make deploy\`."
        exit 1
    fi
    echo "In step — same commit, same files."
    exit 0
fi

before="$(box_stamp)"
say "Deploying $(here_stamp) to $HOST:$DEST (box has ${before:-unknown})"

if ! ssh "${SSH_OPTS[@]}" "$HOST" "mkdir -p $DEST/data/processed"; then
    echo "deploy: cannot reach $HOST — office network or VPN?" >&2
    exit 1
fi

# Guard the one file whose loss converts the box back into a laptop. Checked
# before the sync as well as after: if it is already missing, the box is
# misconfigured and a deploy would bury the evidence under a working-looking
# publish to gh-pages.
if ! ssh "${SSH_OPTS[@]}" "$HOST" "grep -q FACTORY_WEB_ROOT $DEST/.env" 2>/dev/null; then
    echo "deploy: $DEST/.env on the box has no FACTORY_WEB_ROOT." >&2
    echo "        Publishing would push to gh-pages instead of the web root." >&2
    echo "        Fix on the box first:" >&2
    echo "          printf '\\nFACTORY_WEB_ROOT=/var/www/32x-production\\n' >> $DEST/.env" >&2
    exit 1
fi

say "rsync"
# --timeout: a stalled link must fail, not hang. This sat for 51 minutes
# with no bytes moving when the corporate network dropped mid-deploy,
# which looks exactly like a slow deploy until you go and look.
if ! rsync -a --delete --no-owner --no-group --timeout=120 \
        --exclude '.DS_Store' --exclude '__pycache__/' \
        --exclude '.env' \
        --exclude 'data/' --exclude 'dashboard/data/' \
        --stats \
        "$REPO/" "$HOST:$DEST/"; then
    echo "deploy: rsync failed" >&2
    exit 1
fi

after="$(box_stamp)"
if [ "$after" != "$(here_stamp)" ]; then
    echo "deploy: the box reports $after after the sync, expected $(here_stamp)" >&2
    exit 1
fi
say "Box is now at $after"

if [ "${NO_UPDATE:-0}" = "1" ]; then
    echo "NO_UPDATE=1 — skipping the rebuild. The site still shows the old"
    echo "bundle until the hourly tick at :05, or \`make update\` on the box."
    exit 0
fi

say "make update on the box (collect, build, publish)"
ssh "${SSH_OPTS[@]}" "$HOST" "cd $DEST && make update"
code=$?
if [ "$code" -ne 0 ]; then
    echo "deploy: the rebuild exited $code — 2 means the fetch failed, 3 the" >&2
    echo "        publish did. The code is deployed either way." >&2
    exit "$code"
fi

say "Deployed $(here_stamp) and published."

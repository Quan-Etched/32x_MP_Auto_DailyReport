# The dashboard host

The ETL and the site both live on `chuck-dashboard.usw2.i.etched.com` — a
t3.medium running AlmaLinux 9, inside the corporate network, provisioned by
infra under IN-2763. It collects from EOS hourly and serves the result at
**https://32x-production.i.etched.com**.

## Why a host at all

The pipeline used to run on one laptop, publishing to GitHub Pages. That put the
site's freshness on the same schedule as a laptop lid: asleep, off the VPN, or
missing the launchd agent all meant a silently stale dashboard. CI cannot take
over, because EOS resolves to a private address that a GitHub runner cannot
reach. A host inside the network can do both jobs — reach EOS, and stay awake.

## What infra provides

| | |
|---|---|
| SSH | `ssh chuck@chuck-dashboard.usw2.i.etched.com`, Etched credentials, office network or VPN |
| Web root | `/var/www/32x-production`, owned by `chuck` — anything dropped there is served immediately, no reload |
| Backend proxy | `https://32x-production.i.etched.com/api/` → `127.0.0.1:8765` |
| Packages | `sudo dnf install <pkg>` — the one sudo permission on the box |
| nginx config | ansible-managed. Do not hand-edit `/etc/nginx`; ask in #infra-help |

## What the repo needed before it could run there

Two assumptions were laptop-shaped, and both are now settings rather than
rewrites:

**Publishing.** `tools/publish.sh` takes a `FACTORY_WEB_ROOT` target: set (in
`.env`) it rsyncs `dashboard/` into that directory; unset it force-pushes an
orphan commit to `gh-pages` as before. A host that serves the site has nothing
to push and needs no git credential — which matters, since it also holds the API
key and runs unattended.

The copy is `rsync -a --delete` **in place**, not a staged directory moved in:
files created inside the web root inherit its SELinux context, while a directory
moved from `$HOME` would keep the home context and nginx would answer 403.

**Scheduling.** `deploy/systemd/` holds a user service and an hourly `:05` timer;
`make schedule-install` dispatches on `uname` and installs either that or the
make schedule-weekly-install   # Saturday 18:00 Pacific: deck + archive
launchd agent. User units need no root. Linger must be enabled or the timer
stops at logout — reintroducing exactly the failure the host exists to remove —
so the installer enables it and complains loudly if polkit refuses.

## Moving to it, from scratch

```sh
# 1. box: the only packages needed. Python 3.9 is preinstalled and the ETL is
#    stdlib-only, so this is the whole dependency list.
sudo dnf install -y git make

# 2. laptop: stop the old publisher first, so nothing writes to the item store
#    mid-copy and the two hosts never publish in parallel.
make schedule-uninstall
python3 -c "import sqlite3; sqlite3.connect('data/processed/items.sqlite').execute('PRAGMA wal_checkpoint(TRUNCATE)')"

# 3. laptop: the code, plus the two things git does not carry — the CA bundle
#    and .git itself, so the box can diff and pull later. .env is deliberately
#    NOT synced; see "Updating the code" below.
ssh chuck@chuck-dashboard.usw2.i.etched.com 'mkdir -p factory_data_analysis/data/processed'
rsync -av --delete --no-owner --no-group \
  --exclude '.DS_Store' --exclude '__pycache__/' \
  --exclude '.env' \
  --exclude 'data/' --exclude 'dashboard/data/' \
  ./ chuck@chuck-dashboard.usw2.i.etched.com:factory_data_analysis/

# 3b. laptop: the API key, once. Separate from the sync above precisely so a
#     later code deploy cannot overwrite the box's own settings.
scp .env chuck@chuck-dashboard.usw2.i.etched.com:factory_data_analysis/.env

# 4. laptop: the accumulated history. Worth the transfer — see below.
rsync -av --progress data/processed/items.sqlite data/processed/fetch_state.json \
  chuck@chuck-dashboard.usw2.i.etched.com:factory_data_analysis/data/processed/

# WEEKENDS: WST and FT come from Sigurd by message and have nowhere to come
# from automatically. Put the week's figures in weekly/external_yields.json —
# a fraction, the day it describes, and who reported it — then commit. They
# appear on the weekly page, the flow chart and the deck with that provenance
# attached. Leave a figure out and the page says "not reported" rather than
# showing last week's as though it were this week's.

# One step runs only on a laptop: `make release-source` reads the suite YAML
# out of a clone of etched-ai/sw — at each release's commit for the release
# profile, and at origin/master for the station-to-YAML map — and the box has
# no such clone (2.4 GB, and no reason to). Run it on the Mac, commit
# release_profile/release_source.js (dashboard/data/ is generated and
# gitignored; the committed copy outside it is what travels), and the box's
# build copies that into place. The box's own `make build` prints "Release
# source from the committed copy" and carries on.
#
# `make suite-map` prints the same station-to-YAML derivation in a terminal and
# writes nothing — for reading it, or for checking a pin after somebody renames
# a constant in sw. `make release-source` is what puts it on the page.

# The pages, and which source each one is:
#   index.html   station yield from the controllers  <- the default
#   ocp.html     the same page from OCP Logs         <- second opinion
#   runs.html    run table from the controllers, each row links to pega
#   ocpruns.html run table from OCP
#   direct.html and directruns.html redirect to the two defaults.

# 5. box: choose the publish target, then prove the network path.
printf '\nFACTORY_WEB_ROOT=/var/www/32x-production\n' >> .env && chmod 600 .env
make levels            # DNS + internal CA + API key, in one call
make update            # collect -> items -> build -> publish   (~2 minutes)
make schedule-install  # hourly at :05, with linger
```

**Carry `items.sqlite` across.** It is ~233 MB and it is the only copy of the
per-release item history the releases page diffs against; rebuilding it from
scratch recovers only what is still inside the 30-day collection window. The
transfer paid for itself immediately — the first run on the box reported
`1 new runs, 0 rows (1254 already present)`.

**`make trust` does not work here.** It authenticates the downloaded CA bundle
against the copy MDM installed in the macOS keychain, and the box has no
keychain. Copy `certs/etched-internal-ca.pem` from a Mac that has already run
it, or bootstrap with the fingerprint obtained there:

```sh
python3 -m factory.cli trust --fingerprint <sha256 of Etched RSA Corporate Root CA>
```

The check is never skipped — off macOS the anchor just comes from a trusted
channel instead of a keychain.

## Operating it

```sh
make schedule-status   # next tick, last result, Linger=yes, tail of the log
make status            # last fetch vs last update, per station
make update            # force a full cycle now
journalctl --user -u factory-refresh -n 50
tail -f data/logs/refresh.log
```

`hourly_refresh.sh` holds a lock, so a manual run during a scheduled tick backs
off rather than collecting twice. Exit codes: **2** the fetch failed, **3** the
fetch worked but publishing did not — in which case the local bundles are
current and `make publish` alone will retry.

### Reaching the controllers (pega2 - pega5)

The pega hosts live on the `etched.com` Tailscale tailnet, not on the corporate
network: `pega3` is `100.102.15.102`, and `pega3.core.etched.com` resolves to
the `*.core.etched.com` wildcard, which is a different machine entirely. Do not
chase the FQDN.

Tailscale is installed on the dashboard host and needs authenticating **once**,
with no sudo:

```sh
tailscale up --shields-up      # prints a URL; sign in as chuck@etched.com
```

Pick the **etched.com** tailnet, not `etchedexternal` — the latter is a separate
tailnet that does not contain the pega hosts. `--shields-up` blocks inbound
connections and leaves outbound intact, which is all the collector needs.

MagicDNS then resolves the short names, so nothing in this repo is configured
for it:

```sh
for h in pega2 pega3 pega4 pega5; do
  printf '%-7s ' "$h"
  curl -sS -m 6 -o /dev/null -w 'api %{http_code}\n' \
    "http://$h:3000/api/history/data-analysis/suite-runs?per_page=1"
done
```

**The login expires after about 180 days — around 2027-02-10.** When it does,
the daily tracker falls back to grading EOS's per-chip test names: it keeps
working and keeps saying which source it used, but names units `chip 3` instead
of by serial, and the feature-request page's first entry turns red again.
Re-running the same command fixes it.

Until 2026-08-14 the box had no route at all, and the workaround was to warm
`data/raw/pega/` on a laptop and rsync the directory across. That is no longer
needed. The cache still works and is still a valid transport for a host that
cannot reach the controllers, which is why the code path remains.

### Updating the code

```sh
make deploy          # rsync this checkout to the box, then rebuild there
make deploy-status   # is the box running this checkout? non-zero if not
```

**Nothing else updates the code.** The hourly job collects, builds and
publishes whatever tree is already on the box; it has never touched the code,
and the box has no GitHub credential to pull with. So a fix committed on a
laptop is not on the site until `make deploy` runs.

That is not theoretical. On 2026-09-03 the box was serving `75579de` while
`main` was eight commits ahead, and three separate fixes had been written,
committed and reported as done — one of them the fix that put the station list
back on the customize page. Every one of them was real and none of them had
ever been on the site. The page carries its build stamp in the masthead, next
to the version: **if it does not match `git rev-parse --short HEAD`, the site is
not running this code.** `make deploy-status` is that comparison, and the
deploy prints the before and after.

`make deploy` is the same `rsync` as step 3 — **including its `--delete` and
its `--exclude '.env'`** — plus the rebuild, plus a check that the box's `.env`
still carries `FACTORY_WEB_ROOT` before anything is copied. The rest of this
section explains why those flags are what they are; the command applies them
for you.

`--delete` is not tidiness either, and it was missing here until a page had to
be taken down. Without it a file deleted in the repo simply stays on the box,
and `make publish` — which *does* rsync `dashboard/` with `--delete` — copies
it back into the web root from the box's own stale tree. The page comes back
from the dead and the deploy looks like it worked. Deleting `validation.html`
and `builds.html` was the case that found it.

It is safe with the exclusions above: rsync protects excluded paths from
deletion unless you also pass `--delete-excluded`, so `.env`, `data/` and
`dashboard/data/` survive untouched while everything else is made to match.
`dashboard/data/` surviving has one consequence worth knowing: a *generated*
bundle whose builder was removed is not cleaned up by the sync. Delete those by
hand on the box — see below.

**Removing a page.** Deleting `dashboard/foo.html` (and its `.js`, `.css` and
builder) covers the page itself. Its generated bundle lives under
`dashboard/data/`, which the sync deliberately does not touch, so remove that
one on the box:

```bash
# box, after the rsync
rm -f dashboard/data/foo.js
make build && make publish
curl -o /dev/null -sw '%{http_code}\n' https://32x-production.i.etched.com/foo.html   # 404
```

That exclusion is not tidiness. The box's `.env` carries `FACTORY_WEB_ROOT`,
which is what makes `make publish` copy into the web root instead of pushing to
`gh-pages`; a laptop `.env` has no such line. Syncing it over silently converts
the dashboard host back into a laptop, and the failure surfaces one step later
as a git authentication error from a box that has no GitHub credential and
should never need one. It has happened once.

Anything host-specific belongs in the box's `.env` and nowhere else:

```sh
grep FACTORY_WEB_ROOT .env || printf '\nFACTORY_WEB_ROOT=/var/www/32x-production\n' >> .env
```

`git pull` would be the cleaner path, but the box has no GitHub credential
today, deliberately. `make deploy` is the substitute, and `make deploy-status`
is how you find out you forgot it.

### When the controllers go quiet

`pega.TIMEOUT` is 30s because the box reaches pega2-pega6 through a Tailscale
DERP relay in Hong Kong and the *connect* alone measures 5-12s, occasionally
much longer. It was 8s, tuned on a laptop in the same city as the controllers,
and at 8s the relayed path reads as a dead host.

A timeout no longer writes a host off on the first failure — it takes
`FACTORY_PEGA_STRIKES` (3) in a row, and any answer resets the count. The old
behaviour is why the published weekly tracker sat at 2026-W32 for three weeks:
one slow connect at the start of a tick and pega3, pega4 and pega5 were served
from cache for every day of the build, from a cache last warm on 08-09, while
the collector reported success every hour.

If it happens again the log now says so in a `WARNING`. To recover, throw the
suspect range away and let it refill — a cached day-listing is never refetched,
so a bad one is permanent until it is deleted:

```sh
make pega-recache FROM=2026-08-01 DRY_RUN=1   # look first
make pega-recache FROM=2026-08-01
make update
```

### The box cannot reach the controllers today (2026-09-03)

Not "slowly" — measured from the box, one 50-run listing delivered **8,452 of
26,400 bytes in 180 seconds. 46 bytes per second.** The identical request from
a laptop on the same tailnet takes **0.09s**. `tailscale status` shows why:
pega3, pega4 and pega5 are reached `via DERP(hkg)`, a relay in Hong Kong, while
the box sits in us-west-2 — there is no direct path, and `netcheck` reports
`MappingVariesByDestIP: true`, the hard NAT that stops one being negotiated.

So the box runs on a cache warmed elsewhere, which is the transport this repo
has always had for a host with no route:

**This is automated.** `make schedule-pega-push-install` puts an hourly
launchd agent on the laptop that warms the cache and pushes it at **:50**, ten
minutes before the box's own :05 rebuild, so what the box builds from is the
cache that just arrived. `make pega-push` does one round by hand;
`make schedule-pega-push-status` shows the last few.

It retries three times with `--partial`, because the laptop-to-box link is
itself intermittent — the same 97 MB transfer took 25s one hour and died on
`poll: timeout` the next, while plain `ssh` to the host kept working. A failed
push loses freshness and nothing else: the box keeps serving the cache it
already has, and the next tick tries again.

**A sleeping laptop pushes nothing**, which is exactly the fragility the
dashboard host was bought to remove. That is the measure of how much this
wants fixing properly.

By hand, the same thing:

```sh
# laptop, on the VPN, where the controllers answer in milliseconds
make build
rsync -a data/raw/pega/ chuck@chuck-dashboard.usw2.i.etched.com:factory_data_analysis/data/raw/pega/

# box: build from that cache and never wait on the three broken hosts
grep -q FACTORY_PEGA_OFFLINE .env \
  || printf '\nFACTORY_PEGA_OFFLINE=pega3,pega4,pega5\n' >> .env
make build && make publish
```

`FACTORY_PEGA_OFFLINE=pega3,pega4,pega5` is in the box's `.env`. Without it the
hourly build spends five to eight minutes timing out before falling back to the
same cache it would have read anyway — 8m12s against 1m24s, measured.

**It names hosts because the fault is per host.** pega2 (0.7s) and pega6 (2s)
are on the corporate side and answer normally; only pega3, pega4 and pega5 are
relayed. The first version of this was a plain on/off, and taking all five to
the cache dropped 696 unit runs — everything pega2 and pega6 contribute — so
those two keep fetching live.

Every page still reports its controller data as a cached copy, so nobody is
told it is fresher than it is.

**This needs an infra fix, and until it lands the controller half of the
dashboard is only as current as the last cache push.** The ask is a direct
Tailscale path instead of a DERP relay — inbound UDP 41641 to the box, or a
subnet router on the pega side. `#infra-help`, and see IN-2763. Take
`FACTORY_PEGA_OFFLINE` out of `.env` the day it works.

## Known gaps

**The site's certificate does not verify.** nginx serves the leaf and nothing
else — `openssl s_client -connect 32x-production.i.etched.com:443 -showcerts`
returns exactly one certificate — so no client can build a path and every reader
gets a browser warning. The issuer, `O=IDM.ETCHED.COM, CN=Certificate
Authority`, is signed by `Etched RSA Corporate Root CA`, which MDM already
installs on managed Macs, so serving the fullchain would fix it for everyone
with no client change. It is an infra fix; `/etc/nginx` is ansible-managed.
Until then a reader can supply the intermediate locally without trusting
anything new:

```sh
security import certs/etched-internal-ca.pem -k ~/Library/Keychains/login.keychain-db
```

**Nothing authenticates readers.** Anyone on the office network or VPN can open
the site, and it carries DUT serials, failure signatures and yield. The Pages
copy required an authenticated Etched org member, so the move loosened this. It
was a side effect, not a decision — if the data warrants access control, that is
an infra request.

**The Update button is not wired up.** nginx already proxies `/api/` to
`127.0.0.1:8765`, which is what `factory.control` wants, and the ETL runs on the
same box — so the published page could carry a working button instead of a
`Snapshot` chip. Two things block it: `cli serve` binds 8787 on loopback, and
the POST guard requires a loopback `Host` header that an nginx proxy will not
send. The guard is not ceremony — it stops a page in someone's browser from
POSTing to the endpoint — so relaxing it needs a replacement, not a deletion,
now that the route would be reachable by everyone on the network rather than
only by someone already on the box.

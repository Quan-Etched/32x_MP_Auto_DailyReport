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
rsync -av --no-owner --no-group \
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

### The pega3 cache is carried, not fetched

The dashboard host cannot resolve `pega3` (`Name or service not known`), and
`pega3.core.etched.com` hits the `*.core.etched.com` wildcard at
`10.48.145.214`, which is not pega3. The real address is `100.102.15.102`, a
Tailscale one a laptop on the VPN has and the box does not.

pega3 is the only source of the slot -> DUT serial map, so without it the daily
tracker names units `chip 3` instead of `268494130000045`. The data does not
have to be fetched *by the box*: `data/raw/pega/` is a cache on disk, and it
copies across like the CA bundle. Warm it where there is a route, then send it:

```sh
# laptop, on the VPN
make dailyexcel                       # fetches pega3 and fills data/raw/pega/
rsync -av data/raw/pega/ \
  chuck@chuck-dashboard.usw2.i.etched.com:factory_data_analysis/data/raw/pega/
```

The box then builds real serials from the cache. It still tries the network
first for the day listing — a day's runs grow while the day is running — and
falls back to the cached copy, so a carried cache is a floor rather than a
ceiling. Re-send it whenever you want the box's view of today to catch up;
finished runs are immutable, so the transfer is small and mostly additive.

Fixing the route removes the whole step, which is the better answer:

> #infra-help: `chuck-dashboard.usw2.i.etched.com` needs to reach pega3 (ESVM)
> on port 3000. `pega3` does not resolve there, and `pega3.core.etched.com`
> resolves to the `*.core.etched.com` wildcard rather than to pega3. From a
> laptop it is `100.102.15.102` (Tailscale).

### Updating the code

Another `rsync` from the laptop — step 3, **including its `--exclude '.env'`**.
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
today, deliberately.

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

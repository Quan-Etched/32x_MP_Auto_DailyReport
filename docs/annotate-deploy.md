# Turning on Save for the error-code table

The customize page's admin mode edits three columns — Root Cause, Corrective
Action, Note — and posts them to `/annotate` on its own origin. Everything up to
that POST works on the published site today. What is missing is something at
`/annotate` that can write to the repo.

That is deliberate, and it is one nginx block away.

## Why it is not already on

The published dashboard is static files copied into `/var/www/32x-production`.
Nothing there can write to a git repo, and adding a route needs root on
`chuck-dashboard`, which the deploy account does not have — `sudo` prompts for a
password. So this last step is somebody's, not the build's.

## Option 1 — a laptop, today, no root anywhere

Works now, for whoever has the clone:

    make serve        # the dashboard, on http://localhost:8000
    make annotate     # the annotation service, on 127.0.0.1:8766

The page served by `make serve` posts to its own origin, so point the service
and the page at the same port to make this one origin — or run the service on
8000 behind the same reverse proxy. The simplest version: run `make annotate`,
open the customize page from `make serve`, and if the save fails the page hands
back the exact JSON to paste into `errors/annotations.json`. That fallback is
the reason the feature is useful before any of this is set up.

## Option 2 — on the box, for everyone

Needs a root on `chuck-dashboard` once.

1. A unit for the service. It must run as a user who can commit in
   `/home/chuck/factory_data_analysis` and push:

       # /etc/systemd/system/factory-annotate.service
       [Unit]
       Description=Factory dashboard annotation service
       After=network.target

       [Service]
       User=chuck
       WorkingDirectory=/home/chuck/factory_data_analysis
       Environment=FACTORY_ANNOTATE_PASSWORD=<the shared password>
       Environment=FACTORY_ANNOTATE_USERS=chuck,eason,chris
       ExecStart=/usr/bin/python3 tools/annotate_server.py 8766
       Restart=on-failure

       [Install]
       WantedBy=multi-user.target

2. The route. One location block in the server that serves the dashboard:

       location = /annotate {
           proxy_pass http://127.0.0.1:8766/annotate;
           proxy_set_header Host $host;
           # Nothing else proxies. This is the only writable path on the site,
           # and it should stay the only one.
       }

3. `systemctl enable --now factory-annotate && nginx -t && systemctl reload nginx`

Check it with `curl https://32x-production.i.etched.com/annotate` — a GET is a
health check and answers with the admin list and how many annotations are on
file.

## What the password is and is not

The shared password gates *writes*. It lives in the service's environment, not
in the repo and not in the served tree, and the service checks it on every POST.

The sign-in on the page does not check it — it only unlocks the cells. That is
not a shortcut: a check in published JavaScript is a check any reader can skip,
so putting one there would create the impression of access control without any.
The page names who it expects, opens the fields, and finds out at save time.

Which means: **anyone can open the editor, and only the three named admins with
the password can write.** If the requirement becomes "nobody can see the editing
interface", that needs real auth in front of the page — `auth_request` is
compiled into this nginx — and not a change to these files.

## Rotating it

Change `FACTORY_ANNOTATE_PASSWORD` in the unit and `systemctl restart
factory-annotate`. Nothing in the repo or the published pages needs to change,
because neither has ever held it.

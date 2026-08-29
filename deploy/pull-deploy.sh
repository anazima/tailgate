#!/usr/bin/env bash
#
# Deploy the current main branch on the server.
#
# Safe to run from the aaPanel terminal as root or as ubuntu; the parts that
# write into the checkout and the virtualenv run as `ubuntu` so ownership stays
# sane, while gunicorn and the pipeline run as `www`.
#
# Usage: /www/wwwroot/tailgate/deploy/pull-deploy.sh
set -euo pipefail

BASE=/www/wwwroot/tailgate
VENV=$BASE/venv

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

if [ "$(id -un)" = "ubuntu" ]; then
    as_ubuntu() { "$@"; }
else
    as_ubuntu() { sudo -u ubuntu -H "$@"; }
fi

step "Fetching main"
as_ubuntu git -C "$BASE" fetch --prune --quiet origin
as_ubuntu git -C "$BASE" reset --hard --quiet origin/main
as_ubuntu git -C "$BASE" log --oneline -1 | sed 's/^/  now at /'

step "Python dependencies"
as_ubuntu "$VENV/bin/pip" install --quiet --disable-pip-version-check -r "$BASE/requirements.txt"

step "Database migrations"
as_ubuntu "$VENV/bin/python" "$BASE/manage.py" migrate --noinput

step "Static files"
as_ubuntu "$VENV/bin/python" "$BASE/manage.py" collectstatic --noinput --verbosity 0

step "Permissions"
# ubuntu deploys, www serves and writes media/ + logs/.
sudo chgrp -R www "$BASE"
sudo chmod -R g+rX "$BASE"
sudo chmod -R g+w "$BASE/media" "$BASE/logs"
sudo chmod 640 "$BASE/.env"

step "Restarting gunicorn"
sudo supervisorctl restart tailgate
sleep 3
sudo supervisorctl status tailgate

step "Smoke test"
code=$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: tailgate.retoph.com' -H 'X-Forwarded-Proto: https' http://127.0.0.1:8100/login/)
echo "  /login/ -> $code"
[ "$code" = "200" ] || { echo "smoke test failed" >&2; exit 1; }

printf '\n\033[1;32mDeployed\033[0m\n'

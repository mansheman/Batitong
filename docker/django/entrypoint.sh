#!/usr/bin/env bash
set -euo pipefail

cd /app/gui

wait_for_postgres() {
  echo "[entrypoint] waiting for postgres at ${POSTGRES_HOST:-postgres}:${POSTGRES_PORT:-5432}…"
  for i in $(seq 1 60); do
    if pg_isready -h "${POSTGRES_HOST:-postgres}" -p "${POSTGRES_PORT:-5432}" \
        -U "${POSTGRES_USER:-batitong}" >/dev/null 2>&1; then
      echo "[entrypoint] postgres ready"
      return 0
    fi
    sleep 1
  done
  echo "[entrypoint] postgres never came up" >&2
  exit 1
}

run_migrations() {
  echo "[entrypoint] running migrations…"
  python manage.py migrate --noinput
}

create_superuser_if_missing() {
  if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
    echo "[entrypoint] ensuring superuser ${DJANGO_SUPERUSER_USERNAME} exists…"
    python manage.py shell <<PY
from django.contrib.auth import get_user_model
import os
User = get_user_model()
u = os.environ['DJANGO_SUPERUSER_USERNAME']
e = os.environ.get('DJANGO_SUPERUSER_EMAIL', f'{u}@batitong.local')
p = os.environ['DJANGO_SUPERUSER_PASSWORD']
if not User.objects.filter(username=u).exists():
    User.objects.create_superuser(username=u, email=e, password=p)
    print(f'created superuser {u}')
else:
    print(f'superuser {u} already exists')
PY
  fi
}

bootstrap_workspace_if_missing() {
  echo "[entrypoint] ensuring default workspace + admin membership…"
  python manage.py shell <<'PY'
from apps.accounts.models import Workspace, Membership
from django.contrib.auth import get_user_model
import os
User = get_user_model()
ws, _ = Workspace.objects.get_or_create(
    slug='default',
    defaults={'name': 'Default workspace'},
)
admin_username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')
admin = User.objects.filter(username=admin_username).first()
if admin and not Membership.objects.filter(user=admin, workspace=ws).exists():
    Membership.objects.create(user=admin, workspace=ws, role=Membership.Role.OWNER)
    print(f'attached {admin_username} as owner of {ws.slug}')
PY
}

bootstrap_mcp_providers_if_missing() {
  echo "[entrypoint] ensuring default MCP providers…"
  python manage.py shell <<'PY'
import os
from apps.mcp.services import ensure_default_providers
ensure_default_providers(
    kali_url=os.environ.get('KALI_MCP_URL', 'http://kali-mcp:5000/mcp'),
    hexstrike_url=os.environ.get('HEXSTRIKE_API_URL', 'http://hexstrike-api:8888'),
)
print('providers ensured')
PY
}

case "${1:-web}" in
  web)
    wait_for_postgres
    run_migrations
    create_superuser_if_missing || true
    bootstrap_workspace_if_missing || true
    bootstrap_mcp_providers_if_missing || true
    python manage.py collectstatic --noinput >/dev/null 2>&1 || true
    echo "[entrypoint] starting daphne ASGI server on 0.0.0.0:8000"
    exec python -m daphne -b 0.0.0.0 -p 8000 config.asgi:application
    ;;
  worker)
    wait_for_postgres
    echo "[entrypoint] starting celery worker"
    exec celery -A config worker --loglevel=info -Q default,heavy,llm
    ;;
  beat)
    wait_for_postgres
    echo "[entrypoint] starting celery beat"
    exec celery -A config beat --loglevel=info
    ;;
  shell)
    wait_for_postgres
    exec python manage.py shell
    ;;
  *)
    exec "$@"
    ;;
esac

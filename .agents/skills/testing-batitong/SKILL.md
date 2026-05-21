---
name: testing-batitong
description: End-to-end testing recipes for Batitong (Django + Celery + Channels + Postgres + Redis). Use when verifying RBAC gates, migrations, UI copy changes, or the Phase 2C rate-limit banner.
---

# Testing Batitong end-to-end

This skill documents the recipes that worked when testing Phase 2D sub-PR 1/3 (role enum collapse + capability properties + UI copy migration). Keep it general — the same patterns apply to any future RBAC, migration, or UI-copy testing.

## Booting the stack

Use the `core` profile to test everything except the heavy Kali / HexStrike / Ollama images:

```
docker compose --profile core up -d
```

Five containers should come up healthy: `postgres`, `redis`, `django-web`, `celery-worker`, `celery-worker-llm`. The Django app listens on `http://localhost:8000`. Postgres is exposed on `127.0.0.1:5432` (forwarded from the container), redis on `127.0.0.1:6379`.

## Template / view changes don't show up after edits

Django's `cached.Loader` is enabled in dev settings (it's the project's choice — `DEBUG=True` does *not* disable it here). The long-running daphne process caches compiled templates in memory at import time. Even though the template files are bind-mounted from the host, edits to `.html` files won't be visible in the browser until the worker reloads them.

**Fix**: restart `django-web` once after any template edit:

```
docker compose restart django-web
```

Validate with `grep` *inside the container* if you suspect a template is stale:

```
docker compose exec django-web bash -c "grep -rn 'Lead/Owner' /app/gui --include='*.html'"
```

If the source file on disk is correct but the served HTML still has the old copy, it's the loader cache — restart `django-web`, not a code bug.

## URL conventions (don't guess these)

| Page | URL |
| ---- | --- |
| Login | `/accounts/login/` |
| Dashboard | `/dashboard/` (also `/`) |
| Settings | `/dashboard/settings/` (NOT `/ui/settings/` — that returns 404) |
| Credentials | `/credentials/` (read-only for non-admins, write for admins) |
| Approvals inbox | `/approvals/` (admin-only; user gets redirected to dashboard) |
| Playbooks list | `/playbooks/` |
| Playbook authoring | `/playbooks/new/` (admin-only; user gets redirected with flash) |
| MITRE matrix | `/mitre/` |

## Testing RBAC capability gates

The capability properties on `Membership` are:

- `can_run_tools` — True for both admin and user
- `can_approve_high_risk` — True only for admin
- `can_manage_workspace` — True only for admin

To flip a user's role live and watch the UI gates change, use:

```
docker compose exec django-web python manage.py shell -c "
from apps.accounts.models import User, Workspace, Membership
u = User.objects.get(username='SOMEUSER')
w = Workspace.objects.get(slug='default')
m = Membership.objects.get(user=u, workspace=w)
m.role = Membership.Role.ADMIN   # or .USER
m.save()
print('role=', m.role, 'approve=', m.can_approve_high_risk)
"
```

No logout/login needed — middleware re-reads the membership on every request via `request.workspace` / `request.membership`. The active workspace is selected by `WORKSPACE_SESSION_KEY = 'active_workspace_id'` in the session, falling back to the user's first membership.

Typical end-to-end gate check sequence:

1. Create a USER-roled membership for a test account.
2. Log in as that account (or set their password via `u.set_password('...')` first).
3. Browse the page being tested — assert the gated string is present and the CTA is absent.
4. Flip the role to ADMIN via the shell snippet above.
5. Hard-refresh the page — assert the CTA is now present and the gated string is gone.
6. Flip back to USER if you need to test additional blocked paths (e.g. `/approvals/`, `/playbooks/new/`).

## Testing migrations against the live dev DB

For migrations that backfill data (e.g. role enum collapse), the test that proves it works is to:

1. Snapshot the legacy distribution **before** applying:
   ```
   docker compose exec django-web python manage.py shell -c "
   from apps.accounts.models import Membership
   from collections import Counter
   print(dict(Counter(Membership.objects.values_list('role', flat=True))))
   "
   ```
2. If any source role bucket is empty in your dev DB, insert a synthetic row via raw SQL **before** applying the migration so the path is actually exercised:
   ```
   docker compose exec postgres psql -U batitong -d batitong -c "INSERT INTO ..."
   ```
3. Apply: `docker compose exec django-web python manage.py migrate <app> <0003_name>`.
4. Snapshot **after** and assert the deltas land where you expected (row count preserved, no legacy values remain).
5. Roll back: `docker compose exec django-web python manage.py migrate <app> <0002_name>` — verify reverse mapping behaves as documented (lossy reverses should still preserve total row count).
6. Re-apply for idempotency: should land at the same post-migration shape.

Adversarial guard (catches a forward callable that updates only some of the legacy values):

```
docker compose exec postgres psql -U batitong -d batitong -tAc "
  SELECT count(*) FROM accounts_membership WHERE role IN ('owner','lead','operator','viewer');
"
# expect: 0
```

## Running pytest

The runtime container image deliberately does NOT include pytest (it's a prod image). Two ways to run the test suite:

1. **CI** — the canonical signal. Push the branch and check CI for the `lint` + `test` jobs (Phase 2D commits run 136 tests).
2. **Local via poetry** — from the **repo root** (not `gui/`), with the postgres host overridden to point at the docker container's forwarded port:
   ```
   POSTGRES_HOST=127.0.0.1 REDIS_URL=redis://127.0.0.1:6379/0 RATELIMIT_ENABLE=0 \
     poetry run pytest -q
   ```
   The repo's `.env` defaults `POSTGRES_HOST=postgres` (the docker-compose service name) which doesn't resolve from the host — overriding to `127.0.0.1` is the fix.

   Note: running pytest against the same postgres + redis as the live dev stack can produce flaky failures from shared state (existing `ApprovalRequest` rows, redis rate-limit keys, manually created test users). The CI run is the authoritative one. Local pytest is fine for narrow subset runs:
   ```
   poetry run pytest -q gui/tests/test_phase2d_roles.py
   ```

## Testing the rate-limit banner (Phase 2C invariant)

The per-IP login bucket is 10/min. To trigger HTTP 429 you need a valid CSRF token + session cookie — otherwise Django returns 403 (CSRF failure) before the request reaches the rate limiter:

```
rm -f /tmp/c.jar
CSRF=$(curl -s -c /tmp/c.jar -b /tmp/c.jar http://localhost:8000/accounts/login/ \
       | grep -oP 'csrfmiddlewaretoken[^>]*value="\K[^"]+' | head -1)
for i in {1..12}; do
  curl -s -o /tmp/body_$i.html -w "[$i] %{http_code}\n" \
    -b /tmp/c.jar -c /tmp/c.jar \
    -X POST http://localhost:8000/accounts/login/ \
    -d "csrfmiddlewaretoken=$CSRF&username=nobody-$i&password=wrong" \
    -H "Referer: http://localhost:8000/accounts/login/"
done
```

Expected output: first 10 are HTTP 200, 11th is HTTP 429 with a body that contains the markers `429`, `rate limit`, etc.

Requires `RATELIMIT_ENABLE=1` (or `True`) in the django-web env. If the container has `RATELIMIT_ENABLE=0`, the limiter is bypassed entirely.

## Useful diagnostic snippets

```
# Check what migration is applied and what's available
docker compose exec django-web python manage.py showmigrations <app>

# Inspect a migration's operations programmatically (must go through manage.py shell so apps are loaded)
docker compose exec django-web python manage.py shell -c "
from django.db.migrations.loader import MigrationLoader
from django.db import connection
loader = MigrationLoader(connection, ignore_no_migrations=True)
m = loader.disk_migrations[('<app>', '<migration_name>')]
for op in m.operations:
    print(type(op).__name__, op)
"

# Audit a model's runtime enum
docker compose exec django-web python manage.py shell -c "
from apps.accounts.models import Membership
print(sorted([(r.value, r.label) for r in Membership.Role]))
"

# Find a template's actual origin path (the one Django will use)
docker compose exec django-web python manage.py shell -c "
from django.template.loader import get_template
t = get_template('ui/dashboard.html')
print(t.origin.name)
"
```

## Devin secrets needed

None for backend regression testing. Logging in as the seeded `admin` superuser uses the default dev password `batitong-admin` (see `entrypoint.sh` / dev fixtures). Cloud LLM features (GitHub Models, OpenRouter, GROQ) need workspace credentials configured at `/credentials/manage/` — out of scope for role/migration testing.

---
name: testing-gui
description: End-to-end verification of the Batitong Django GUI (sidebar, RBAC gates, Alpine.js components, approvals badges, rate-limit banner). Use whenever a PR touches /gui/templates/, /gui/static/js/, /gui/static/css/, or any sidebar / dashboard / settings page. Live-browser verification is REQUIRED — template-only pytest cannot detect Alpine binding failures.
---

# Testing the Batitong GUI

The most important lesson from Phase 2D PR #9: **CI green is not sufficient** for any change that touches an Alpine.js binding. Template-rendered HTML, CSS, and the JS factory function can all look correct in isolation while Alpine fails to bind the component at runtime due to script-ordering issues. Always do a live-browser pass before declaring a sidebar/dashboard PR verified.

## Stack & access

- `docker compose --profile core up -d` boots postgres + redis + django-web + 2 celery workers. Heavy MCP tool images (kali-mcp / hexstrike / ollama) are NOT needed for any GUI/UX test and should be skipped to keep the loop fast.
- Django root is `gui/`. Settings: `config.settings.dev` (default), `config.settings.test` (CI/pytest).
- Local pytest: `DJANGO_SETTINGS_MODULE=config.settings.test poetry run pytest -q` (test settings use in-memory sqlite — env vars from `.env` like `POSTGRES_HOST=postgres` don't apply).
- Lint: `poetry run ruff check gui/ && poetry run black --check gui/`.

## Seed credentials (local dev only)

These are seeded fresh on each `docker compose --profile core up`. Never embed real secrets here.

| User | Role | Password | Purpose |
|---|---|---|---|
| `admin@batitong.local` | `Membership.Role.ADMIN` | `batitong-test` | Sees full sidebar incl. Workflow group, can approve high-risk |
| `op@batitong.local` | `Membership.Role.USER` | `batitong-test` | Use for RBAC-gate verification — Workflow group must be ABSENT from DOM |

Usernames in the `auth_user` table are `admin` and `op` (the `@batitong.local` is the email). The login form accepts username.

Workspace: `acme` (slug). All seeded data lives in this workspace.

## Login recipe (shell, for fixture priming)

```bash
curl -s -c /tmp/cj.txt http://localhost:8000/accounts/login/ -o /tmp/login.html
CSRF=$(grep -oP 'name="csrfmiddlewaretoken" value="\K[^"]+' /tmp/login.html | head -1)
curl -s -b /tmp/cj.txt -c /tmp/cj.txt \
  -H "Referer: http://localhost:8000/accounts/login/" \
  -d "csrfmiddlewaretoken=$CSRF&username=admin&password=batitong-test" \
  -X POST http://localhost:8000/accounts/login/ -o /dev/null -w "login=%{http_code}\n"
```

Expected: `login=200` (POST returns 200 because Django redirects to `next=` after success and curl-without-`-L` reports the post-302 page; either way subsequent `curl -b /tmp/cj.txt` calls are authenticated).

## Live-browser verification via Playwright over CDP

Devin's Chrome exposes CDP at `http://localhost:29229`. Attach Playwright instead of launching a fresh browser:

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://localhost:29229")
    ctx = browser.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("http://localhost:8000/dashboard/")
    # ... do real DOM/CSS/localStorage assertions via page.evaluate(...)
```

Login from Playwright (form fill, not API) so subsequent navigations carry the session cookie.

Maximize the Chrome window BEFORE starting any `ffmpeg -f x11grab` recording — half-tiled windows produce confusing recordings:

```bash
sudo apt-get install -y wmctrl 2>/dev/null; wmctrl -r :ACTIVE: -b add,maximized_vert,maximized_horz
```

Never use `xdotool key super+Up` — many WMs interpret it as half-screen tiling, not maximize.

## Seed two pending approvals (for sidebar dual-badge tests)

```python
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from apps.accounts.models import Workspace
from apps.engagements.models import Engagement, AttackPlanStep, ToolExecution
from apps.mcp.models import MCPProvider, MCPTool
from apps.approvals.services import request_approval_for_execution
from django.contrib.auth import get_user_model

U = get_user_model()
admin = U.objects.get(username="admin")
ws = Workspace.objects.get(slug="acme")
prov, _ = MCPProvider.objects.get_or_create(name="kali", defaults={"kind": "kali", "url": "http://kali:5000/mcp"})
tool, _ = MCPTool.objects.get_or_create(provider=prov, name="nmap",
    defaults={"description": "scan", "risk_level": "high", "tactic": "recon"})
for i in range(2):
    eng = Engagement.objects.create(workspace=ws, name=f"fixture-{i}", created_by=admin)
    step = AttackPlanStep.objects.create(engagement=eng, order=1, title="fixture")
    exe = ToolExecution.objects.create(step=step, tool=tool, tool_name="nmap",
        arguments={"target": "127.0.0.1"}, status="awaiting_approval")
    request_approval_for_execution(workspace=ws, execution=exe, requested_by=admin,
        risk_level="high", summary=f"fixture-{i}", rationale="test")
```

Run via `docker compose exec -T django-web python manage.py shell <<< "<script above>"`.

## Alpine.js race lesson — read this BEFORE editing any sidebar / Alpine component

Phase 2D PR #9 shipped this bug initially, even though CI passed and every template-level pytest assertion passed:

```
Alpine Expression Error: navGroups is not defined
Expression: "navGroups()"
```

**Root cause.** Under HTML5 deferred-script ordering, defer scripts run in document order after parsing. Alpine 3 auto-starts inside `alpine.min.js` when `document.readyState` is `'interactive'`. If your JS factory (e.g. `window.navGroups = () => {...}` defined in `app.js`) loads AFTER `alpine.min.js`, Alpine evaluates `x-data="navGroups()"` BEFORE the factory exists and prints the silent warning above. No component binds; every `x-show` stays at its `[x-cloak] { display: none }` fallback; `@click` handlers are no-ops. Server HTML looks correct. Template tests pass. CI is green. The page is broken.

**Rules.**
1. ALWAYS load `app.js` (the factory file) BEFORE `alpine.min.js` in `<head>`. Even if both are `defer`. Even if it feels wrong.
2. PREFER registry-based lookup: `x-data="navGroups"` (no parens). Register on `alpine:init`:
   ```js
   document.addEventListener("alpine:init", () => {
     window.Alpine.data("navGroups", navGroups);
   });
   ```
   This is defense-in-depth: even if a future refactor reorders scripts, Alpine resolves the component via its data registry instead of needing `window.navGroups`.
3. Add a pytest regression that asserts the script order in `base.html` (see `test_t13_app_js_loaded_before_alpine_min_js`).
4. Verify in DevTools console: NO `Alpine Expression Error` warnings on first paint of any page. If you see them, the component is unbound — don't ship.

## RBAC gating — verify in BOTH layers

Workflow / Approvals / Credentials are admin-only. A correct gate has two layers:

1. **Template**: `{% if active_membership.can_approve_high_risk %}` wraps the entire markup block. For a `user`-role member, the DOM literally does not contain the group — verify via view-source, not just CSS visibility.
2. **Server**: even if a non-admin types the URL directly, they get a 302 to `/accounts/login/?next=...` (Phase 2A gate via `@admin_required`). Verify with `curl -b cookies.txt -w '%{http_code} %{redirect_url}\n' http://localhost:8000/approvals/` — must be `302` with the login redirect URL.

**Harness caveat.** Playwright `fetch(..., redirect: 'manual')` returns `status=0` for opaque redirects. That is NOT a failure of the gate — it's a fetch-API artifact. If your Playwright assertion checks `r.status >= 300`, it will spuriously fail; verify out-of-band with `curl` instead, OR use `fetch(..., redirect: 'follow')` and check the final URL.

## Dual-place approvals badge (Phase 2D Q5=(b))

When pending approvals exist AND the user is admin, the count must appear in THREE places simultaneously:

1. Workflow group HEADER badge (`[data-component="workflow-count"]`) — visible even when the group is collapsed.
2. Inline next to the Approvals link (`.nav__count`) — visible only when the group is expanded.
3. Topbar bell — always visible.

Regressions that drop one of (1) or (2) make pending work invisible in the most common state (Workflow collapsed). The pytest `test_t6_workflow_header_count_badge_when_pending` uses `monkeypatch` on `_pending_approvals_count` to isolate this from the ApprovalRequest schema.

## Common gotchas

- The Django template `{% if ns in 'llm engagements playbooks' %}` is SUBSTRING matching, not list membership. It happens to work because no namespace name in the same group is a substring of another, but adding e.g. `engagement` would collide silently. Use a regroup tag or refactor to a list comparison if you add namespaces.
- `.env` in repo root has `POSTGRES_HOST=postgres` which only resolves inside the Docker network. Local `poetry run pytest` works because `config.settings.test` overrides DATABASES to sqlite `:memory:`. If pytest fails with `Temporary failure in name resolution`, you forgot `DJANGO_SETTINGS_MODULE=config.settings.test`.
- `docker compose exec -T django-web python -m pytest` will fail with `No module named pytest` — pytest is a dev-only dep and the production image doesn't include it. Use `poetry run pytest` from the host instead.
- Rate-limit banner (Phase 2C) is disabled in dev (`RATELIMIT_ENABLE=False` in `config.settings.test` and via env). Set `RATELIMIT_ENABLE=True` to test the 429 path.

## Recording / annotation conventions

- One mp4 per PR test run, store in `/home/ubuntu/recordings/<pr-name>_<ts>.mp4`.
- Stop the recording before writing the test report. Re-encoding mid-write corrupts the file.
- If a test plan reveals a shipping bug, **rename** the in-progress recording to `<pr-name>_pre_fix_<symptom>.mp4` and start a fresh recording for the post-fix verification. Both attached to the PR comment make the bug-fix journey legible.
- Test report should include screenshots of: default sidebar state, after-toggle state, after-reload state, non-admin POV, badge-present state, and any error / banner being verified.

## Devin secrets needed

None. All credentials in this skill are local-development seed values that exist only inside the dev Docker stack. No external API keys are required for GUI testing.

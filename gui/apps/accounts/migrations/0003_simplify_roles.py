"""Phase 2D: collapse the 4-role enum into a minimal 2-role model.

Forward mapping
---------------
* ``owner``    → ``admin`` (kept the manage-workspace capability)
* ``lead``     → ``admin`` (kept the approve-high-risk capability)
* ``operator`` → ``user``  (kept the run-tools capability)
* ``viewer``   → ``user``  (read-only no longer enforced at the role
  level; viewers acquire ``can_run_tools`` post-migration — this is an
  intentional trade-off documented in Phase 2D Q3=(a))

Reverse mapping (best-effort, used by ``migrate accounts 0002``)
----------------------------------------------------------------
* ``admin`` → ``owner`` (so the workspace remains manageable)
* ``user``  → ``operator``
"""

from __future__ import annotations

from django.db import migrations, models


def collapse_to_admin_user(apps, schema_editor):
    Membership = apps.get_model("accounts", "Membership")
    Membership.objects.filter(role__in=["owner", "lead"]).update(role="admin")
    Membership.objects.filter(role__in=["operator", "viewer"]).update(role="user")


def expand_to_owner_operator(apps, schema_editor):
    Membership = apps.get_model("accounts", "Membership")
    Membership.objects.filter(role="admin").update(role="owner")
    Membership.objects.filter(role="user").update(role="operator")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_workspace_llm_fallback_chain"),
    ]

    operations = [
        migrations.RunPython(collapse_to_admin_user, expand_to_owner_operator),
        migrations.AlterField(
            model_name="membership",
            name="role",
            field=models.CharField(
                choices=[("admin", "Admin"), ("user", "User")],
                default="user",
                max_length=16,
            ),
        ),
    ]

"""Initial migration for the credentials app."""

from __future__ import annotations

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkspaceCredential",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "key",
                    models.CharField(
                        help_text=(
                            "Stable identifier (e.g. shodan_api_key). " "Matches a CredentialSpec."
                        ),
                        max_length=64,
                    ),
                ),
                ("label", models.CharField(blank=True, default="", max_length=120)),
                ("value_encrypted", models.TextField()),
                ("note", models.CharField(blank=True, default="", max_length=240)),
                ("last_tested_at", models.DateTimeField(blank=True, null=True)),
                ("last_test_ok", models.BooleanField(blank=True, null=True)),
                (
                    "last_test_message",
                    models.CharField(blank=True, default="", max_length=240),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="credentials_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="credentials",
                        to="accounts.workspace",
                    ),
                ),
            ],
            options={
                "ordering": ["workspace__slug", "key"],
                "unique_together": {("workspace", "key")},
            },
        ),
    ]

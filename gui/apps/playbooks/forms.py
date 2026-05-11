"""Forms for playbook authoring + run start."""

from __future__ import annotations

import json
import re

from django import forms
from django.core.exceptions import ValidationError
from django.utils.text import slugify

from apps.engagements.models import Engagement
from apps.mcp.models import MCPTool
from apps.mitre.models import MitreTechnique
from apps.targets.models import Target

from .models import Playbook, PlaybookStep
from .templating import TemplateValidationError, validate_template_dict


class PlaybookForm(forms.ModelForm):
    technique_search = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )

    class Meta:
        model = Playbook
        fields = (
            "name",
            "slug",
            "description",
            "technique",
            "objective",
            "risk_envelope",
            "on_step_failure",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, workspace=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        self.fields["technique"].queryset = (
            MitreTechnique.objects.filter(is_active=True)
            .select_related("tactic")
            .order_by("tactic__order", "technique_id")
        )
        self.fields["objective"].choices = [
            c for c in Engagement.Objective.choices if c[0] != Engagement.Objective.MANUAL
        ]
        if not self.instance.pk:
            self.fields["slug"].required = False

    def clean_slug(self) -> str:
        raw = (self.cleaned_data.get("slug") or "").strip()
        if not raw:
            raw = slugify(self.cleaned_data.get("name") or "")
        slug = slugify(raw)[:120] or "playbook"
        if not re.match(r"^[a-z0-9][a-z0-9-]{1,118}[a-z0-9]$", slug):
            raise ValidationError("slug must be 3-120 lowercase letters/digits/dashes.")
        # Uniqueness scoped to workspace.
        qs = Playbook.objects.filter(workspace=self.workspace, slug=slug)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("a playbook with this slug already exists in your workspace.")
        return slug

    def save(self, commit: bool = True) -> Playbook:
        playbook: Playbook = super().save(commit=False)
        playbook.workspace = self.workspace
        playbook.is_built_in = False
        if commit:
            playbook.save()
        return playbook


class PlaybookStepForm(forms.ModelForm):
    arg_template_json = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "class": "font-mono"}),
        help_text='JSON object, e.g. {"url": "{{ target.value }}"}',
    )

    class Meta:
        model = PlaybookStep
        fields = ("order", "tool", "title", "rationale", "is_optional", "timeout_sec")
        widgets = {"rationale": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, workspace=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        self.fields["tool"].queryset = (
            MCPTool.objects.filter(is_available=True)
            .select_related("provider")
            .prefetch_related("techniques")
            .order_by("provider__kind", "name")
        )
        if self.instance.pk and self.instance.arg_template:
            self.initial["arg_template_json"] = json.dumps(
                self.instance.arg_template, indent=2, ensure_ascii=False
            )

    def clean_arg_template_json(self) -> dict:
        raw = (self.cleaned_data.get("arg_template_json") or "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"invalid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValidationError("arg_template must be a JSON object.")
        try:
            validate_template_dict(parsed)
        except TemplateValidationError as exc:
            raise ValidationError(str(exc)) from exc
        return parsed

    def save(self, commit: bool = True) -> PlaybookStep:
        step: PlaybookStep = super().save(commit=False)
        step.arg_template = self.cleaned_data.get("arg_template_json", {}) or {}
        if commit:
            step.save()
        return step


class StartRunForm(forms.Form):
    target = forms.ModelChoiceField(queryset=Target.objects.none())
    on_step_failure_override = forms.ChoiceField(
        required=False,
        choices=[("", "Use playbook default")] + list(Playbook.OnFailure.choices),
    )
    arg_overrides = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "class": "font-mono"}),
        help_text='Optional JSON: {"1": {"url": "https://..."}}',
    )
    force_envelope = forms.BooleanField(
        required=False,
        help_text="Run even if a step exceeds the playbook risk envelope.",
    )

    def __init__(self, *args, workspace=None, **kwargs):
        super().__init__(*args, **kwargs)
        if workspace is not None:
            self.fields["target"].queryset = Target.objects.filter(
                workspace=workspace, is_active=True
            ).order_by("value")

    def clean_arg_overrides(self) -> dict:
        raw = (self.cleaned_data.get("arg_overrides") or "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"invalid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValidationError("arg_overrides must be a JSON object keyed by step order.")
        for k, v in parsed.items():
            if not str(k).isdigit():
                raise ValidationError(f"key {k!r} must be a numeric step order.")
            if not isinstance(v, dict):
                raise ValidationError(f"value for step {k} must be a JSON object.")
        return parsed

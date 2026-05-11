"""Forms for chat session creation + LLM router settings."""

from __future__ import annotations

from django import forms
from django.conf import settings
from django.db.models import Q

from apps.targets.models import Target

from .adapters.github_models import GITHUB_MODELS_OPTIONS

PROVIDER_CHOICES = (
    ("ollama", "Ollama (local)"),
    ("github_models", "GitHub Models (cloud)"),
    ("openrouter", "OpenRouter (cloud, free-tier)"),
    ("groq", "GROQ (cloud, free-tier)"),
)
LOCAL_PROVIDER_CHOICES = (("ollama", "Ollama (local)"),)


class NewChatForm(forms.Form):
    title = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={"class": "input", "placeholder": "(optional) chat title"}),
    )
    provider_kind = forms.ChoiceField(
        choices=PROVIDER_CHOICES,
        widget=forms.Select(attrs={"class": "input input--mono"}),
        initial="ollama",
    )
    model_name = forms.CharField(
        required=False,
        max_length=120,
        widget=forms.TextInput(
            attrs={
                "class": "input input--mono",
                "placeholder": "leave blank for default",
            }
        ),
        help_text=(
            "GitHub Models: gpt-4o-mini / Phi-3.5-MoE-instruct / Llama-3.3-70B-Instruct. "
            "OpenRouter: see free-tier slugs (gemma-2-9b-it:free, …). "
            "GROQ: llama-3.1-8b-instant, llama-3.3-70b-versatile, mixtral-8x7b-32768."
        ),
    )
    system_prompt = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={"class": "input", "rows": 4, "placeholder": "extra workspace notes (optional)"}
        ),
    )
    anchored_playbook = forms.ModelChoiceField(
        required=False,
        queryset=None,  # set in __init__
        empty_label="(no anchor — free-form chat)",
        help_text=(
            "Anchor this chat to a playbook so the system prompt references "
            "the linked MITRE technique + recommended tool set."
        ),
    )
    anchored_target = forms.ModelChoiceField(
        required=False,
        queryset=Target.objects.none(),
        empty_label="(no target — leave blank when free-form)",
    )

    def __init__(self, *args, workspace=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        if workspace is not None and getattr(workspace, "privacy_mode", False):
            # Force Ollama when privacy mode is on; visually disable cloud options.
            self.fields["provider_kind"].choices = LOCAL_PROVIDER_CHOICES
            self.fields["provider_kind"].initial = "ollama"
            self.fields["provider_kind"].help_text = (
                "Workspace privacy mode is on — cloud providers are disabled."
            )

        # Lazy import to avoid circulars at module load.
        from apps.playbooks.models import Playbook

        if workspace is not None:
            self.fields["anchored_playbook"].queryset = (
                Playbook.objects.filter(is_active=True)
                .filter(Q(is_built_in=True) | Q(workspace=workspace))
                .select_related("technique", "technique__tactic")
                .order_by("-is_built_in", "name")
            )
            self.fields["anchored_target"].queryset = Target.objects.filter(
                workspace=workspace
            ).order_by("value")
        else:
            self.fields["anchored_playbook"].queryset = Playbook.objects.none()

    def clean(self):
        cleaned = super().clean()
        playbook = cleaned.get("anchored_playbook")
        target = cleaned.get("anchored_target")
        if target is not None and playbook is None:
            raise forms.ValidationError("Pick a playbook to anchor to, or leave the target blank.")
        return cleaned


class LLMRouterSettingsForm(forms.Form):
    """Form rendered in the Settings page (admin/lead only)."""

    privacy_mode = forms.BooleanField(
        required=False,
        help_text="When on, route every chat turn through the local Ollama provider.",
    )
    default_provider = forms.ChoiceField(
        choices=PROVIDER_CHOICES,
        required=False,
    )
    default_model = forms.CharField(
        required=False,
        max_length=120,
        widget=forms.TextInput(attrs={"class": "input input--mono"}),
        help_text=(
            "Optional default model override for new chats (e.g. "
            f"{GITHUB_MODELS_OPTIONS[0][0]} or qwen2.5-coder:7b)."
        ),
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["default_provider"].initial = getattr(
            settings, "LLM_DEFAULT_PROVIDER", "ollama"
        )

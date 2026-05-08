"""Forms for adding/editing credentials in the Settings UI."""

from __future__ import annotations

from django import forms

from .models import WorkspaceCredential
from .seed import CREDENTIAL_SPECS


class CredentialForm(forms.ModelForm):
    """Form that exposes a known credential key as a dropdown.

    The plaintext value lives outside the model so we can write-then-encrypt.
    Editing an existing credential replaces the value only when the user
    enters a non-empty new value (so users can rename a label without
    re-typing the secret).
    """

    KEY_CHOICES = [(s.key, f"{s.label} — {s.provider}") for s in CREDENTIAL_SPECS]

    key = forms.ChoiceField(
        choices=KEY_CHOICES,
        widget=forms.Select(attrs={"class": "input input--mono"}),
    )
    value = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"class": "input input--mono", "autocomplete": "off"}),
        help_text=(
            "Leave blank when editing to keep the existing value. "
            "Plaintext is stored encrypted (Fernet) and never logged."
        ),
    )
    label = forms.CharField(
        required=False,
        max_length=120,
        widget=forms.TextInput(attrs={"class": "input"}),
    )
    note = forms.CharField(
        required=False,
        max_length=240,
        widget=forms.TextInput(attrs={"class": "input"}),
    )

    class Meta:
        model = WorkspaceCredential
        fields = ["key", "label", "note"]

    def __init__(self, *args, **kwargs) -> None:
        self.workspace = kwargs.pop("workspace")
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            # Lock the key field once it's saved — prevents accidental remap.
            self.fields["key"].disabled = True

    def clean(self) -> dict:
        data = super().clean()
        key = data.get("key") or (self.instance.key if self.instance.pk else None)
        if not self.instance.pk and not data.get("value"):
            raise forms.ValidationError("Provide a value for the new credential.")
        if not self.instance.pk and key:
            qs = WorkspaceCredential.objects.filter(workspace=self.workspace, key=key)
            if qs.exists():
                raise forms.ValidationError(
                    f"This workspace already has a '{key}' credential — edit it instead."
                )
        return data

    def save(self, commit: bool = True) -> WorkspaceCredential:
        cred = super().save(commit=False)
        cred.workspace = self.workspace
        new_value = self.cleaned_data.get("value") or ""
        if new_value:
            cred.set_value(new_value)
        if commit:
            cred.save()
        return cred

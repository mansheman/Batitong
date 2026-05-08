"""Static seed data: which credentials each tool/provider can consume.

Each entry is keyed by a normalized credential ``key`` and describes:
  * ``label``: a short human label
  * ``provider``: free-form provider name (informational)
  * ``env_var``: the environment variable that downstream tools/CLIs expect
  * ``hint``: where to get the value
  * ``test_url``: optional URL we can ``GET`` with the credential to validate

The execution layer reads ``WorkspaceCredential.value_for_env(KEY)`` and
injects it under ``env_var`` when running tools.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CredentialSpec:
    key: str
    label: str
    provider: str
    env_var: str
    hint: str
    test_url: str | None = None


CREDENTIAL_SPECS: tuple[CredentialSpec, ...] = (
    CredentialSpec(
        key="shodan_api_key",
        label="Shodan API key",
        provider="shodan.io",
        env_var="SHODAN_API_KEY",
        hint="Account → API on https://account.shodan.io/",
        test_url="https://api.shodan.io/api-info?key={value}",
    ),
    CredentialSpec(
        key="censys_api_id",
        label="Censys API ID",
        provider="censys.io",
        env_var="CENSYS_API_ID",
        hint="Account → API credentials on https://search.censys.io/account/api",
    ),
    CredentialSpec(
        key="censys_api_secret",
        label="Censys API secret",
        provider="censys.io",
        env_var="CENSYS_API_SECRET",
        hint="Pair with the matching API ID.",
    ),
    CredentialSpec(
        key="virustotal_api_key",
        label="VirusTotal API key",
        provider="virustotal.com",
        env_var="VIRUSTOTAL_API_KEY",
        hint="Profile → API key on https://www.virustotal.com/",
    ),
    CredentialSpec(
        key="securitytrails_api_key",
        label="SecurityTrails API key",
        provider="securitytrails.com",
        env_var="SECURITYTRAILS_API_KEY",
        hint="Account → API on https://securitytrails.com/app/account/credentials",
    ),
    CredentialSpec(
        key="github_pat",
        label="GitHub PAT",
        provider="github.com",
        env_var="GITHUB_TOKEN",
        hint="Used by amass/subfinder for code search; fine-grained PAT is fine.",
    ),
    CredentialSpec(
        key="wpscan_api_token",
        label="WPScan API token",
        provider="wpscan.com",
        env_var="WPSCAN_API_TOKEN",
        hint="Profile → API token on https://wpscan.com/profile",
    ),
    CredentialSpec(
        key="hibp_api_key",
        label="HaveIBeenPwned API key",
        provider="haveibeenpwned.com",
        env_var="HIBP_API_KEY",
        hint="https://haveibeenpwned.com/API/Key",
    ),
    CredentialSpec(
        key="github_models_token",
        label="GitHub Models token (LLM)",
        provider="github.com (models.inference.ai.azure.com)",
        env_var="GITHUB_MODELS_TOKEN",
        hint=(
            "Fine-grained PAT with 'models:read' scope — used by the LLM router "
            "when this workspace is not in privacy mode."
        ),
    ),
)


SPECS_BY_KEY: dict[str, CredentialSpec] = {s.key: s for s in CREDENTIAL_SPECS}


def get_spec(key: str) -> CredentialSpec | None:
    return SPECS_BY_KEY.get(key)


__all__ = ["CredentialSpec", "CREDENTIAL_SPECS", "SPECS_BY_KEY", "get_spec"]

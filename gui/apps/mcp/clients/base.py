"""Common dataclasses and helpers shared by MCP clients."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class HealthStatus:
    healthy: bool
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ToolDefinition:
    """Provider-agnostic representation of a callable tool."""

    name: str
    description: str
    schema: dict[str, Any]


@dataclass
class ToolResult:
    output: str
    is_error: bool = False
    structured: dict[str, Any] | None = None


def parse_tactic_from_description(desc: str) -> str:
    """Extract MITRE ATT&CK tactic id from a tool docstring like ``[TA0043 ...]``."""
    desc = desc or ""
    if not desc:
        return "unknown"
    head = desc.strip()
    if head.startswith("["):
        end = head.find("]")
        if end != -1:
            tag = head[1:end].strip().split()
            if tag:
                first = tag[0]
                if first.startswith("TA") and first[2:].isdigit():
                    return first
                if first.lower() == "utility":
                    return "util"
    if head.lower().startswith("utility"):
        return "util"
    return "unknown"


def guess_risk_level(tool_name: str) -> str:
    """Heuristic classification of tools that should require Lead approval."""
    name = tool_name.lower()

    critical = {
        "msfvenom_generate",
        "metasploit_run_module",
        "weevely_generate",
        "weevely_cmd",
    }
    high = {
        "sqlmap_dump",
        "hydra_bruteforce",
        "medusa_bruteforce",
        "commix_scan",
        "responder_run",
        "impacket_ntlmrelayx",
        "arpspoof_attack",
        "ettercap_mitm",
        "impacket_psexec",
        "impacket_smbexec",
        "impacket_wmiexec",
        "impacket_secretsdump",
        "evil_winrm",
        "netexec_run",
        "run_custom_command",
    }
    medium = {
        "sqlmap_scan",
        "nikto_scan",
        "wapiti_scan",
        "nuclei_scan",
        "feroxbuster_scan",
        "ffuf_fuzz",
        "wfuzz_fuzz",
        "gobuster_dir",
        "dirb_scan",
        "masscan_scan",
        "tcpdump_capture",
        "scapy_probe",
    }
    if name in critical:
        return "crit"
    if name in high:
        return "high"
    if name in medium:
        return "med"
    return "low"

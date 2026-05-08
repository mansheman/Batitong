# Batitong

> **Phase 1 (Foundation)** — Django GUI + Docker Compose stack on top of the
> Kali MCP server and HexStrike-AI control plane. See [DESIGN.md](DESIGN.md)
> for the full architectural blueprint.

Batitong is a developer-focused web console for **MCP-driven offensive
security tooling**. It wraps two existing projects vendored in this repo:

- `kali_mcp_server.py` — a [FastMCP](https://github.com/modelcontextprotocol/python-sdk)
  server exposing 82 Kali Linux tools over `streamable-http` (described
  further down this file).
- `hexstrike-ai/` — a Flask-based AI control plane that produces target
  profiles and execution plans.

Phase 1 ships:

- Django 5 + DRF + Channels skeleton with apps for `accounts`, `targets`,
  `engagements`, `mcp`, and `ui`.
- An MCP adapter layer (`apps/mcp/clients/`) that talks to both Kali MCP and
  HexStrike, plus a `sync_mcp_tools` management command that mirrors the
  upstream tool catalog into Postgres.
- **Manual Mode**: browse the tool catalog, pick a tool, fill an
  auto-generated form, run it. Output is streamed live to the browser via
  WebSocket Channels backed by Redis.
- A dark, terminal-inspired UI with JetBrains Mono / Inter typography,
  numbered sections, severity badges, and live-log terminal panels.
- Single-command Docker Compose (`docker compose --profile full up -d --build`)
  bringing up Postgres, Redis, the Django ASGI server, a Celery worker,
  Kali MCP, HexStrike API, and Ollama (with auto-pulled models).

### Quick start (laptop dev)

```bash
git clone https://github.com/mansheman/Batitong.git
cd Batitong
cp .env.example .env

# Generate strong values for SECRET_KEY and FERNET_KEY (one-liner):
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(64))" >> .env
python -c "from cryptography.fernet import Fernet; print('FERNET_KEY=' + Fernet.generate_key().decode())" >> .env

# Build and start everything (heavy first build — Kali image is large):
docker compose --profile full up -d --build

# Once healthy, sync the tool registry from the running MCP servers:
docker compose exec django-web python manage.py sync_mcp_tools --bootstrap
```

Open <http://localhost:8000>, log in with the seeded admin credentials from
your `.env` (`DJANGO_SUPERUSER_USERNAME` / `DJANGO_SUPERUSER_PASSWORD`).

If you only want the control plane without the heavy tool images:

```bash
docker compose --profile core up -d --build
```

### LLM strategy (Phase 2 wiring)

We use a **hybrid** strategy:

- **Local default** — `ollama` container with auto-pulled models
  (`qwen2.5-coder:7b`, `llama3.1:8b`, `phi3:mini` by default).
- **Cloud option** — the official **GitHub Models API** via
  `https://models.inference.ai.azure.com` (set `GITHUB_MODELS_TOKEN` in
  `.env` to enable). This is **not** the same as the GitHub Copilot editor
  plugin, whose terms of service forbid backend / unattended use.

The LLM router itself ships in Phase 2; Phase 1 only stores the configuration
and shows it on the Settings page.

---

# Kali MCP Server (vendored)

The original Kali MCP server documentation is preserved below.

A Model Context Protocol (MCP) server that exposes Kali Linux penetration testing tools as structured, callable tools for large language models. Designed for integration with VS Code GitHub Copilot and any MCP-compatible LLM client.

Tools are organized according to the [MITRE ATT&CK Framework](https://attack.mitre.org/) tactics to provide a structured methodology for offensive security workflows.

---

## Architecture Overview

```
VS Code / LLM Client
        |
        | MCP (streamable-http)
        |
kali_mcp_server.py  (FastMCP / uvicorn)
        |
        | subprocess (no shell=True)
        |
Kali Linux Tools (nmap, sqlmap, impacket, ...)
```

The server uses the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) (`FastMCP`) and communicates over the `streamable-http` transport. All tool invocations use `subprocess.run` directly — shell injection is not possible because no `shell=True` is used anywhere.

---

## Hybrid Orchestration Workflow

When combining HexStrike AI with Kali MCP, use a two-layer model:

- **HexStrike AI** as the control plane for analysis, planning, tool selection, and parameter optimization
- **Kali MCP** as the execution plane for stable tool invocation and structured outputs

The included [hybrid_orchestrator.py](hybrid_orchestrator.py) script wires both together:

```bash
python3 hybrid_orchestrator.py health
python3 hybrid_orchestrator.py plan https://localhost --objective comprehensive
python3 hybrid_orchestrator.py recon https://localhost
```

Workflow summary:

1. Check HexStrike health and request an execution plan
2. Check Kali MCP availability
3. Execute a stable recon subset through Kali MCP
4. Run any HexStrike-selected tools that are also present in Kali MCP
5. Return normalized output for downstream correlation

This keeps the reasoning layer flexible while keeping the execution layer deterministic.

---

## Requirements

- Kali Linux (or a Debian-based system with Kali repositories)
- Python 3.11+
- MCP Python SDK

```bash
pip install mcp
```

---

## Installation

```bash
git clone <repository-url>
cd Pen-AI
```

No additional Python dependencies beyond `mcp` are required. All tools rely on system-installed Kali packages.

---

## Running the Server

```bash
python3 kali_mcp_server.py
```

The server starts on `http://127.0.0.1:5000/mcp` using the `streamable-http` MCP transport.

Expected output:

```
Starting Kali MCP server on http://127.0.0.1:5000/mcp
INFO:     Started server process [...]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:5000
```

To run as a background service:

```bash
nohup python3 kali_mcp_server.py > /var/log/kali-mcp.log 2>&1 &
```

---

## VS Code Integration

### Configuration

The MCP server is pre-configured in [.vscode/mcp.json](.vscode/mcp.json):

```json
{
  "servers": {
    "kali-mcp": {
      "type": "http",
      "url": "http://127.0.0.1:5000/mcp",
      "displayName": "Kali MCP (local)",
      "description": "Local Kali MCP server for tools/resources"
    }
  }
}
```

### Connection Steps

1. Start the server: `python3 kali_mcp_server.py`
2. Open VS Code in this workspace
3. Open the Copilot Chat panel
4. Verify the `kali-mcp` server shows as **Connected** in the MCP servers list
5. All 82 tools are immediately available to GitHub Copilot and other MCP clients

### Reconnecting

If the server was restarted, click **Reconnect** next to `kali-mcp` in the MCP panel, or reload the VS Code window (`Ctrl+Shift+P` > `Developer: Reload Window`).

---

## Tool Reference

**Total tools: 82** across 13 ATT&CK tactics.

### TA0043 — Reconnaissance (21 tools)

| Tool | Underlying Binary | Description |
|---|---|---|
| `nmap_scan` | nmap | Service/version scan with configurable flags |
| `nmap_port_scan` | nmap | Targeted port scan with scan type selection |
| `nmap_script_scan` | nmap | NSE script scan (vuln, auth, smb-enum-*, etc.) |
| `masscan_scan` | masscan | Ultra-fast TCP port scan, configurable rate |
| `gobuster_dir` | gobuster | Directory/file brute-force |
| `gobuster_dns` | gobuster | DNS subdomain enumeration |
| `dirb_scan` | dirb | Web content scanner |
| `ffuf_fuzz` | ffuf | Web fuzzer with FUZZ keyword replacement |
| `wfuzz_fuzz` | wfuzz | Alternative web fuzzer |
| `feroxbuster_scan` | feroxbuster | Recursive directory brute-force |
| `nikto_scan` | nikto | Web vulnerability scanner |
| `whatweb_scan` | whatweb | Web technology fingerprinting |
| `wapiti_scan` | wapiti | Web application vulnerability scanner |
| `dnsenum_scan` | dnsenum | DNS enumeration and zone transfer |
| `dnsrecon_scan` | dnsrecon | DNS reconnaissance (std, axfr, brt, goo) |
| `theharvester_scan` | theHarvester | OSINT: emails, subdomains, IPs |
| `amass_enum` | amass | Subdomain enumeration (passive/active) |
| `recon_ng_modules` | recon-ng | List and query recon-ng marketplace modules |
| `dig_lookup` | dig | DNS record lookup (A, MX, TXT, NS, ANY, etc.) |
| `whois_lookup` | whois | WHOIS query for domain or IP |
| `shodan_query` | shodan | Internet-wide device/service search |

### TA0042 — Resource Development (9 tools)

| Tool | Underlying Binary | Description |
|---|---|---|
| `searchsploit` | searchsploit | Search Exploit-DB for public exploits |
| `searchsploit_show` | searchsploit | Show exploit path by EDB-ID |
| `msfvenom_generate` | msfvenom | Generate payloads (elf, exe, ps1, php, etc.) |
| `msfvenom_list` | msfvenom | List payloads, encoders, formats, platforms |
| `radare2_analyze` | radare2 | Binary analysis (functions, strings, imports) |
| `msf_nasm_shell` | msf-nasm_shell | Assemble x86/x64 instructions to shellcode hex |
| `weevely_generate` | weevely | Generate PHP backdoor agent |
| `pyinstaller_build` | pyinstaller | Bundle Python script into standalone executable |
| `clang_compile` | clang / clang++ | Compile C/C++ source code |

### TA0001 — Initial Access (5 tools)

| Tool | Underlying Binary | Description |
|---|---|---|
| `sqlmap_scan` | sqlmap | SQL injection detection |
| `sqlmap_dump` | sqlmap | Database/table dump via SQL injection |
| `commix_scan` | commix | Command injection detection and exploitation |
| `hydra_bruteforce` | hydra | Credential brute-force (SSH, FTP, HTTP, SMB, RDP) |
| `medusa_bruteforce` | medusa | Parallel credential brute-force |

### TA0002 — Execution (2 tools)

| Tool | Underlying Binary | Description |
|---|---|---|
| `metasploit_run_module` | msfconsole | Run Metasploit auxiliary/exploit module non-interactively |
| `weevely_cmd` | weevely | Execute commands on a deployed weevely PHP agent |

### TA0003 — Persistence (3 tools)

| Tool | Path | Description |
|---|---|---|
| `webshells_list` | /usr/share/webshells | List available web shells by language |
| `laudanum_list` | /usr/share/laudanum | List Laudanum injected shells by type |
| `webshell_read` | — | Read content of a web shell or Laudanum file |

### TA0004 — Privilege Escalation (4 tools)

| Tool | Underlying Binary | Description |
|---|---|---|
| `linpeas_run` | linpeas.sh | Run LinPEAS on the local system |
| `unix_privesc_check` | unix-privesc-check | Unix privilege escalation checker |
| `winpeas_info` | — | List WinPEAS binaries available for upload to Windows targets |
| `peass_get_path` | — | Get PEASS-ng file paths for transfer to targets |

### TA0005 — Network Attack / Defense Evasion (6 tools)

| Tool | Underlying Binary | Description |
|---|---|---|
| `responder_run` | responder | LLMNR/NBT-NS/mDNS poisoning, captures Net-NTLMv2 hashes |
| `impacket_ntlmrelayx` | impacket-ntlmrelayx | NTLM relay attack |
| `arpspoof_attack` | arpspoof | ARP spoofing / Man-in-the-Middle |
| `ettercap_mitm` | ettercap | MitM, sniffing, and protocol dissection |
| `dsniff_capture` | dsniff | Passive credential sniffing from network traffic |
| `scapy_probe` | scapy | Custom packet crafting via Python/Scapy snippets |

### TA0006 — Credential Access (6 tools)

| Tool | Underlying Binary | Description |
|---|---|---|
| `hash_identify` | hashid | Identify hash type |
| `john_crack` | john | Dictionary attack with John the Ripper |
| `hashcat_crack` | hashcat | GPU/CPU hash cracking (MD5, NTLM, bcrypt, Kerberoast, etc.) |
| `impacket_getuserspns` | impacket-GetUserSPNs | Kerberoasting — extract TGS tickets for offline cracking |
| `impacket_getnpusers` | impacket-GetNPUsers | AS-REP Roasting — extract hashes from pre-auth-disabled accounts |
| `impacket_getadusers` | impacket-GetADUsers | Enumerate Active Directory user accounts |

### TA0007 — Discovery (13 tools)

| Tool | Underlying Binary | Description |
|---|---|---|
| `enum4linux_scan` | enum4linux | SMB/Windows enumeration (users, shares, groups) |
| `smbclient_list` | smbclient | List SMB shares |
| `rpcclient_enum` | rpcclient | RPC enumeration against Windows targets |
| `smbmap_scan` | smbmap | SMB share permissions and file listing |
| `netdiscover_scan` | netdiscover | ARP-based host discovery on local networks |
| `arping_scan` | arping | ARP ping for local host verification |
| `fping_sweep` | fping | Fast ICMP ping sweep across IP ranges |
| `fierce_dns` | fierce | DNS reconnaissance and subdomain brute-force |
| `nbtscan_scan` | nbtscan | NetBIOS name scanner |
| `onesixtyone_snmp` | onesixtyone | SNMP community string brute-force |
| `snmpwalk_enum` | snmpwalk | SNMP MIB tree enumeration |
| `tcpdump_capture` | tcpdump | Packet capture with BPF filter support |
| `hping3_probe` | hping3 | Advanced TCP/IP packet crafting and host probing |

### TA0008 — Lateral Movement (8 tools)

| Tool | Underlying Binary | Description |
|---|---|---|
| `evil_winrm` | evil-winrm | WinRM shell with Pass-the-Hash support |
| `impacket_psexec` | impacket-psexec | Remote command execution via SMB/psexec |
| `impacket_smbexec` | impacket-smbexec | Stealthy SMB execution (no binary on disk) |
| `impacket_wmiexec` | impacket-wmiexec | Remote execution via WMI (no service install) |
| `impacket_secretsdump` | impacket-secretsdump | Dump SAM, LSA secrets, and NTDS.dit hashes |
| `netexec_run` | netexec | Multi-protocol post-exploitation (SMB/SSH/WinRM/LDAP) |
| `xfreerdp_connect` | xfreerdp3 | RDP connection via xfreerdp3 |
| `rdesktop_connect` | rdesktop | Legacy RDP client for older Windows targets |

### TA0009 — Collection / Vulnerability Scanning (1 tool)

| Tool | Underlying Binary | Description |
|---|---|---|
| `nuclei_scan` | nuclei | Template-based vulnerability scanner |

### TA0011 — Wireless / C2 (1 tool)

| Tool | Underlying Binary | Description |
|---|---|---|
| `aircrack_crack` | aircrack-ng | WPA/WEP key cracking from .cap capture file |

### Utility (3 tools)

| Tool | Description |
|---|---|
| `list_installed_tools` | Check which Kali tools are installed, grouped by ATT&CK tactic |
| `wordlists_info` | List available wordlists under /usr/share/wordlists |
| `run_custom_command` | Execute any arbitrary command safely via subprocess |

---

## Adding New Tools

Every tool follows the same pattern. Add a new function anywhere in `kali_mcp_server.py` before the entry point:

```python
@mcp.tool()
def tool_name(target: str, flags: str = "") -> str:
    """[TA000X Tactic Name] Brief description — this is shown to the LLM.

    Args:
        target: Description of this parameter
        flags: Description of this parameter
    """
    cmd = ["binary-name"] + shlex.split(flags) + [target]
    return _format(_run(cmd, timeout=120))
```

Guidelines:

- Use `shlex.split()` for all flag strings — never build shell command strings
- Use `_require_file()` for any parameter that references a file path
- Include the `[TACTICxx Name]` prefix in the docstring so `list_installed_tools` groups it correctly
- Restart the server and reconnect in VS Code after adding tools

---

## Security Considerations

- The server binds to `127.0.0.1` only — it is not accessible from outside the local machine
- All subprocess calls use `shell=False` (the default) — shell injection via tool arguments is not possible
- File path parameters are validated with `_require_file()` to prevent path traversal
- `webshell_read` enforces a path allowlist restricted to `/usr/share/webshells` and `/usr/share/laudanum`
- The `run_custom_command` tool does not support shell operators (`|`, `&&`, `;`, `>`) due to `shlex` tokenisation without shell expansion
- No credentials or secrets are logged or persisted

---

## Project Structure

```
Pen-AI/
├── kali_mcp_server.py      # MCP server — all tool definitions
├── kali_mcp_server.py.bak  # Auto-generated backup (pre-rewrite)
├── README.md               # This file
└── .vscode/
    ├── mcp.json            # MCP server registration for VS Code
    └── settings.json       # VS Code workspace settings
```

---

## Troubleshooting

### VS Code shows "Error 404" in MCP logs

The server is not running, or is running the old Flask-based server that does not implement the MCP protocol. Ensure `kali_mcp_server.py` is running (not any other server), and that `mcp.json` points to `http://127.0.0.1:5000/mcp` (note the `/mcp` path).

### Port 5000 already in use

```bash
fuser -k 5000/tcp
python3 kali_mcp_server.py
```

### Tool returns "Tool not found: binary-name"

The underlying Kali binary is not installed. Install it with:

```bash
sudo apt install <package-name>
```

Use `list_installed_tools` within the LLM chat to check which tools are available on the current system.

### MCP SDK not installed

```bash
pip3 install mcp
```

---

## License

This project is intended for use in authorized penetration testing and security research environments only. Ensure you have explicit written permission before testing any system you do not own /m4n\.

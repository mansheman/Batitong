# =============================================================================
# Kali MCP server — runs kali_mcp_server.py inside a Kali Linux base image so
# every tool (nmap, sqlmap, hydra, …) referenced by the FastMCP server is
# available on $PATH.
#
# This image is large (~3-5 GB). It is opt-in via the docker-compose `tools`
# profile — operators on smaller machines can skip it and call out to a
# pre-existing kali host instead by pointing KALI_MCP_URL there.
# =============================================================================

FROM kalilinux/kali-rolling:latest

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PIP_NO_CACHE_DIR=1

# Core OS deps + a curated subset of Kali tools used by kali_mcp_server.py.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates curl wget python3 python3-pip git \
        nmap masscan rustscan \
        nikto whatweb wafw00f sqlmap wpscan dirb \
        gobuster ffuf wfuzz feroxbuster wapiti \
        hydra medusa john hashcat crunch \
        netcat-traditional dnsutils whois dnsrecon dnsenum fierce \
        subfinder amass enum4linux smbclient smbmap \
        ldap-utils enum4linux-ng \
        tcpdump tshark \
        responder ettercap-text-only \
        impacket-scripts \
        arp-scan \
        binwalk exiftool \
        wordlists \
 && rm -rf /var/lib/apt/lists/*

# Python deps for the FastMCP server.
RUN pip install --no-cache-dir 'mcp>=1.0' 'uvicorn[standard]>=0.30'

WORKDIR /opt/kali-mcp
COPY kali_mcp_server.py /opt/kali-mcp/kali_mcp_server.py

# FastMCP listens on streamable-http; expose 5000 to the docker network.
EXPOSE 5000

# Bind to 0.0.0.0 so other containers on the network can reach it. The
# upstream script defaults to 127.0.0.1 — we set MCP_HOST so the FastMCP
# transport binds publicly inside the network.
ENV MCP_HOST=0.0.0.0 \
    MCP_PORT=5000

CMD ["python3", "-u", "/opt/kali-mcp/kali_mcp_server.py"]

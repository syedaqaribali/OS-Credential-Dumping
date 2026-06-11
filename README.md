# OS-Credential-Dumping
#	Technique	Platform	What It Extracts
1	LSASS Memory Dump	Windows	NTLM hashes, Kerberos tickets, plaintext passwords (via comsvcs.dll, procdump, sqldumper)
2	SAM Registry Hives	Windows	Local user NTLM hashes (SAM + SYSTEM boot key)
3	Credential Manager	Windows	Saved web credentials, Windows credentials, generic credentials
4	Browser Credentials	All	Chrome/Edge/Firefox saved passwords (encrypted, with extraction scripts)
5	Shadow File Dump	Linux	/etc/shadow password hashes (SHA-512, yescrypt, bcrypt)
6	Keychain Dump	macOS	Login keychain, Safari passwords, iCloud keychain
7	Memory Scraping	Linux/macOS	In-memory credentials from process address spaces
8	Config File Scanner	All	Passwords from web.config, .env, config.php, .npmrc, .git-credentials
9	SSH Key Discovery	All	SSH private keys, known_hosts, authorized_keys
10	Cloud Credentials	All	AWS (~/.aws/credentials), GCP, Azure access tokens
11	DPAPI Master Keys	Windows	Master keys for decrypting Chrome/Edge/RDP/other DPAPI-protected data
12	Docker Credentials	Linux	Container env vars, Docker config, compose files, swarm secrets
13	Process Environment Scan	Linux	Passwords/secrets exposed in /proc/*/environ of running processes

#Usage
# Interactive menu - choose techniques
python3 cred_dump.py

# Run ALL applicable techniques for your platform
python3 cred_dump.py --all

# Run specific techniques only
python3 cred_dump.py --browsers --cloud --ssh

# Platform-specific shortcuts
python3 cred_dump.py --shadow          # Linux only
python3 cred_dump.py --lsass --sam     # Windows only
python3 cred_dump.py --keychain        # macOS only

# Custom output directory
python3 cred_dump.py --all --output /path/to/evidence

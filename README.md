# Browser Automation Validator

**Built by unknone hart**

A powerful Playwright-based login validator that tests credentials against login pages. Supports multiple credential formats, batch testing, and multi-file processing.

---

## Features

- ✅ Multiple credential formats (`URL|user|pass` and `URL:user:pass`)
- ✅ Auto-continue mode (`--c`) - no prompts, just test
- ✅ Multi-file support (`--ms file1.txt file2.txt`)
- ✅ URL override mode (`--bl URL`) - test all creds against one URL
- ✅ Colored output (green for SUCCESS, red for failed)
- ✅ Graceful exit on Ctrl+C
- ✅ Real browser automation with Playwright
- ✅ Smart field detection for login forms

---

## Installation

### Linux

```bash
# 1. Install Python 3.8+
sudo apt update
sudo apt install python3 python3-pip

# 2. Install Playwright
pip3 install playwright

# 3. Install browsers
playwright install
sudo playwright install-deps

# 4. Clone/download validator.py
```

### Termux (Android)

```bash
# 1. Update packages
pkg update && pkg upgrade

# 2. Install Python
pkg install python

# 3. Install Playwright
pip install playwright

# 4. Install browsers
playwright install chromium

# 5. For remote access (optional) - install ngrok
pkg install wget
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm64.tgz
tar xvzf ngrok-v3-stable-linux-arm64.tgz
mv ngrok $PREFIX/bin/
ngrok config add-authtoken YOUR_TOKEN

# 6. Clone/download validator.py
```

---

## Usage

### Basic Usage

```bash
# Single file with prompts
python3 validator.py credentials.txt

# Auto-continue (no prompts)
python3 validator.py --c credentials.txt

# Multiple files
python3 validator.py --ms file1.txt file2.txt file3.txt --c

# Test all against one URL
python3 validator.py --bl https://example.com/login --c credentials.txt
```

### Input File Formats

**Pipe format:**
```
https://example.com:2083|username|password
https://site.com/login|admin|secret123
```

**Colon format:**
```
https://example.com:2083/:username:password
https://site.com/login:admin:secret123
```

### Flags Reference

| Flag | Description | Example |
|------|-------------|---------|
| `--c` | Auto-continue, skip all prompts | `python3 validator.py --c file.txt` |
| `--ms` | Multiple files mode | `python3 validator.py --ms f1.txt f2.txt` |
| `--bl URL` | Override all URLs to test | `python3 validator.py --bl https://site.com/login --c file.txt` |

### Examples

```bash
# Test credentials from subdirectory
python3 validator.py --c 'idpass/rcu_login_pass (1).txt'

# Multiple files with auto-continue
python3 validator.py --ms 'idpass/file1.txt' 'idpass/file2.txt' --c

# Override URL for all credentials
python3 validator.py --bl https://edusanjal.com/account/login/ --c edusanjal_login_pass.txt

# Combine all flags
python3 validator.py --ms cp.txt 'Cpanel (1).txt' --bl https://test.com/login --c
```

---

## Termux + Ngrok Setup (Remote Access)

```bash
# 1. Start ngrok to expose your device
ngrok tcp 22

# 2. Note the forwarding URL (e.g., tcp://0.tcp.ngrok.io:12345)

# 3. Connect from remote machine
ssh user@0.tcp.ngrok.io -p 12345

# 4. Run validator on your Android via SSH
cd ~/Desktop/validator
python3 validator.py --c credentials.txt
```

---

## Output

- **Successful logins** saved to `successful_*.txt`
- **Multi-file mode** saves to `successful_multi.txt`
- **Console output** shows real-time progress with colors:
  - 🟢 `✓ SUCCESS` - Valid credentials found
  - 🔴 `✗ failed` - Invalid credentials

---

## Troubleshooting

### Playwright not found
```bash
pip3 install playwright
playwright install
```

### File not found
Use correct path relative to where you run the command:
```bash
# Wrong: file.txt (if in subdirectory)
# Correct: idpass/file.txt
python3 validator.py idpass/file.txt
```

### Browser launch fails
```bash
# Linux
sudo playwright install-deps

# Termux
playwright install chromium
```

---

## Credits

**Built by unknone hart**

- Playwright for browser automation
- Python 3 for the core engine

---

## License

For educational and authorized testing only. Always have permission before testing credentials.

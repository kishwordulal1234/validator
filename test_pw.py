from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    page.goto("https://edusanjal.com/account/login/")
    page.wait_for_timeout(2000)
    page.fill("input[type='email']", "madhukaryogi@gmail.com")
    page.fill("input[type='password']", "Himal12#")
    page.screenshot(path="before_submit.png")
    page.click("button:has-text('Sign In')")
    page.wait_for_timeout(4000)
    page.screenshot(path="after_submit.png")
    print(page.url)
    browser.close()

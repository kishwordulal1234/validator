from playwright.sync_api import sync_playwright
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page.goto("https://nepaltraveller.com/login")
        page.wait_for_timeout(2000)
        page.screenshot(path="nt_0_initial.png")
        
        page.fill("input[type='email']", "ydvgoitindra6217@gmail.com")
        page.fill("input[type='password']", "avashgoit621712")
        page.screenshot(path="nt_1_filled.png")
        
        # Click the login button
        page.click("button:has-text('LOGIN')")
        page.wait_for_timeout(4000)
        page.screenshot(path="nt_2_after_submit.png")
        
        print("Final URL:", page.url)
        browser.close()
except Exception as e:
    print(e)

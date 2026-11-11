# -*- coding: utf-8 -*-
"""Same as read_share_link.py, but a VISIBLE window on the owner's screen: Google answers an
automated browser with /sorry/index (captcha), and a person can clear that in one click. The
script waits for the real page, then saves the text and a screenshot. Read-only.

  python read_share_link_visible.py <url> [out.txt] [wait_seconds]
"""
import sys, os, re, time
from playwright.sync_api import sync_playwright
sys.stdout.reconfigure(encoding='utf-8')
URL = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else 'C:/Users/Flo/Downloads/pce-ops/data/share-capture.txt'
WAIT = int(sys.argv[3]) if len(sys.argv) > 3 else 150
PROFILE = 'C:/Users/Flo/Downloads/pce-ops/data/.browser-profile'   # our own profile, never the owner's Chrome data
CONSENT = re.compile(r'^(accept all|acceptă tot|accepta tot|accept|i agree|sunt de acord)', re.I)

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        PROFILE, headless=False, viewport={'width': 1366, 'height': 950}, locale='en-GB', timezone_id='Europe/Bucharest',
        args=['--disable-blink-features=AutomationControlled', '--start-maximized'],
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36')
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>false});")
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(URL, wait_until='domcontentloaded', timeout=60000)
    page.wait_for_timeout(2500)
    for frame in page.frames:                       # consent wall, once
        for el in frame.query_selector_all('button, [role=button], input[type=submit]'):
            try: t = (el.inner_text() or el.get_attribute('aria-label') or el.get_attribute('value') or '').strip()
            except Exception: continue
            if t and CONSENT.match(t):
                try: el.click(); page.wait_for_timeout(2500)
                except Exception: pass
                break
    deadline = time.time() + WAIT
    while time.time() < deadline:
        u = page.url
        if '/sorry/index' not in u and 'consent.google' not in u:
            body = page.inner_text('body')
            if len(body) > 1200:                    # the real answer page, not a stub
                break
        print(f'   waiting for the page ({int(deadline - time.time())}s left) — if a captcha is on screen, click it', flush=True)
        page.wait_for_timeout(5000)
    page.wait_for_timeout(2000)
    body = page.inner_text('body')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'w', encoding='utf-8').write(f'URL: {URL}\nFINAL: {page.url}\nTITLE: {page.title()}\n\n{body}\n')
    shot = OUT.rsplit('.', 1)[0] + '.png'
    try: page.screenshot(path=shot, full_page=True)
    except Exception: pass
    print('final url:', page.url[:120]); print('chars:', len(body)); print('saved:', OUT)
    print('--- text ---'); print(body[:3000])
    ctx.close()

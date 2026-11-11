# -*- coding: utf-8 -*-
"""Open a shared Google link in a real browser, clear the consent wall, and save the page text.

  python read_share_link.py <url> [out.txt]

curl and WebFetch only ever reach Google's consent redirect; a browser can accept it once and
read what the owner sees. Read-only: it clicks consent and nothing else.
"""
import sys, os, re, time
from playwright.sync_api import sync_playwright
sys.stdout.reconfigure(encoding='utf-8')
URL = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else 'C:/Users/Flo/Downloads/pce-ops/data/share-capture.txt'
MASK = "Object.defineProperty(navigator,'webdriver',{get:()=>false});"
CONSENT = re.compile(r'^(accept all|acceptă tot|accepta tot|accept|i agree|sunt de acord|acceptați tot)', re.I)

with sync_playwright() as pw:
    br = pw.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
    ctx = br.new_context(viewport={'width': 1366, 'height': 950}, locale='en-GB', timezone_id='Europe/Bucharest',
                         user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36')
    ctx.add_init_script(MASK)
    page = ctx.new_page()
    page.goto(URL, wait_until='domcontentloaded', timeout=60000)
    page.wait_for_timeout(2500)
    for _ in range(3):
        if 'consent.google' not in page.url and 'sorry/index' not in page.url: break
        clicked = False
        for frame in page.frames:
            for sel in ('button', '[role=button]', 'input[type=submit]'):
                for el in frame.query_selector_all(sel):
                    try:
                        t = (el.inner_text() or el.get_attribute('aria-label') or el.get_attribute('value') or '').strip()
                    except Exception:
                        continue
                    if t and CONSENT.match(t):
                        try:
                            el.click(); clicked = True; break
                        except Exception:
                            pass
                if clicked: break
            if clicked: break
        page.wait_for_timeout(3000)
        if not clicked: break
    page.wait_for_timeout(4000)
    print('final url:', page.url[:140])
    print('title:', page.title()[:120])
    body = page.inner_text('body')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'w', encoding='utf-8').write(f'URL: {URL}\nFINAL: {page.url}\nTITLE: {page.title()}\n\n{body}\n')
    shot = OUT.rsplit('.', 1)[0] + '.png'
    page.screenshot(path=shot, full_page=True)
    print('saved:', OUT, '|', len(body), 'chars |', shot)
    print('--- first 1500 chars ---')
    print(body[:1500])
    br.close()

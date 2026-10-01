# -*- coding: utf-8 -*-
"""Does a real-looking visit still send a GA4 hit? navigator.webdriver is masked, because the
site deliberately skips analytics for automation. Read-only: loads two pages, sends nothing else."""
import sys, re
from playwright.sync_api import sync_playwright
sys.stdout.reconfigure(encoding='utf-8')
B = 'https://projectcostestimator.com'
MASK = "Object.defineProperty(navigator,'webdriver',{get:()=>false});"
with sync_playwright() as pw:
    br = pw.chromium.launch(headless=True)
    ctx = br.new_context(viewport={'width': 1280, 'height': 900}, locale='en-US', timezone_id='Europe/London',
                         user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36')
    ctx.add_init_script(MASK)
    page = ctx.new_page()
    hits = []; errs = []
    page.on('request', lambda r: hits.append(r.url) if re.search(r'google-analytics\.com|analytics\.google\.com|googletagmanager\.com/gtag', r.url) else None)
    page.on('pageerror', lambda e: errs.append(str(e)[:160]))
    page.on('console', lambda m: errs.append('console:' + m.text[:140]) if m.type == 'error' else None)
    page.goto(B + '/', wait_until='networkidle'); page.wait_for_timeout(4000)
    state = page.evaluate("""() => ({
        hasGtag: typeof window.gtag === 'function',
        dl: (window.dataLayer||[]).length,
        dlFirst: JSON.stringify((window.dataLayer||[]).slice(0,8)),
        webdriver: navigator.webdriver,
        consent: localStorage.getItem('pce_cookie_consent'),
        gaCookie: document.cookie.split(';').map(c=>c.trim()).filter(c=>c.startsWith('_ga')).join(' | '),
        tz: Intl.DateTimeFormat().resolvedOptions().timeZone
    })""")
    print('gtag fn:', state['hasGtag'], '| dataLayer len:', state['dl'], '| webdriver:', state['webdriver'], '| tz:', state['tz'])
    print('consent in storage:', state['consent'])
    print('_ga cookie:', state['gaCookie'] or '(none)')
    print('dataLayer head:', state['dlFirst'][:320])
    print('GA requests on load:', len(hits))
    for u in hits[:6]: print('   ', u[:150])
    if errs: print('errors:', errs[:5])
    try:
        b = page.get_by_role('button', name=re.compile('Accept', re.I))
        if b.count(): b.first.click(); page.wait_for_timeout(2500); print('clicked Accept')
    except Exception as e:
        print('banner:', str(e)[:80])
    hits.clear()
    page.goto(B + '/pricing', wait_until='networkidle'); page.wait_for_timeout(4000)
    print('GA requests after Accept + navigation:', len(hits))
    for u in hits[:6]: print('   ', u[:150])
    print('_ga cookie now:', page.evaluate("document.cookie.split(';').map(c=>c.trim()).filter(c=>c.startsWith('_ga')).join(' | ')") or '(none)')
    br.close()

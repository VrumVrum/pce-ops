# -*- coding: utf-8 -*-
"""Build data/sponsor-prospects.csv - the send list of the sponsor lane - from the research files.
  python scripts/sponsor_prospects.py [--max-fetch 400]

Inputs (any that exist): data/sponsor-prospects-*.csv (curated by research agents: page_slug, company, website,
partner_status, contact_email, found_at ...) and data/sponsor-directory-bulk.csv (vendor, company, website, tier,
country). Output columns: name,email,market,website,topic,page_slug,partner_status,found_at,sent.

Rules
  * An address is used only when it is visible on the company's own site. Curated addresses are re-checked at
    their found_at page; for rows without one, the home, contact and about pages are fetched and an address on
    the company's own domain is taken (role addresses first). Nothing is guessed or constructed.
  * One row per company (by domain). The page pitched is the article about the product they are a partner of.
  * market: from the directory country, the TLD, or phone/address hints on the site; unknown counts as "us",
    which the engine holds until a postal address is configured (CAN-SPAM).
  * Existing rows keep their `sent` value; a company already written to is never added twice.
Model-free. Results per domain are cached in data/sponsor-email-cache.json.
"""
import csv, glob, html, io, json, os, re, sys, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data') + os.sep
OUT = D + 'sponsor-prospects.csv'
CACHE = D + 'sponsor-email-cache.json'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36'
FIELDS = ['name', 'email', 'market', 'website', 'topic', 'page_slug', 'partner_status', 'found_at', 'sent']
VENDOR_PAGE = {
    'hubspot': ('HubSpot', 'hubspot-cost-2026'), 'klaviyo': ('Klaviyo', 'mailchimp-vs-klaviyo-cost-2026'),
    'mailchimp': ('Mailchimp', 'mailchimp-cost-2026'), 'shopify': ('Shopify', 'shopify-store-cost-2026'),
    'bigcommerce': ('BigCommerce', 'shopify-vs-bigcommerce-cost-2026'), 'woocommerce': ('WooCommerce', 'woocommerce-vs-shopify-cost-2026'),
    'magento': ('Magento', 'magento-website-cost-2026'), 'webflow': ('Webflow', 'webflow-website-cost-2026'),
    'framer': ('Framer', 'framer-website-cost-2026'), 'bubble': ('Bubble', 'bubble-io-cost-2026'),
    'wix': ('Wix', 'wix-website-cost-calculator'), 'squarespace': ('Squarespace', 'squarespace-website-cost-calculator'),
    'airtable': ('Airtable', 'airtable-cost-2026'), 'notion': ('Notion', 'notion-cost-2026'), 'clickup': ('ClickUp', 'clickup-cost-2026'),
}
SLUG_TOPIC = {'seo-services-cost-2026': 'SEO services', 'content-marketing-cost-2026': 'content marketing', 'calendly-cost-2026': 'Calendly',
              'chatbot-development-cost-2026': 'chatbot development', 'headless-commerce-cost-2026': 'headless commerce',
              'wp-engine-cost-2026': 'WP Engine', 'website-hosting-cost-2026': 'website hosting', 'wordpress-migration-cost-2026': 'WordPress migration',
              'wcag-accessibility-cost-2026': 'WCAG accessibility', 'gdpr-compliance-website-cost-2026': 'GDPR compliance',
              'website-security-cost-2026': 'website security', 'ghost-cms-cost-2026': 'Ghost', 'astro-website-cost-2026': 'Astro',
              'progressive-web-app-cost-2026': 'progressive web app', 'idx-website-cost-2026': 'IDX website', 'how-much-does-an-mvp-cost-2026': 'MVP',
              'saas-development-cost-2026': 'SaaS development', 'multi-vendor-marketplace-cost-2026': 'multi-vendor marketplace',
              'cost-to-build-online-marketplace-2026': 'online marketplace', 'ecommerce-website-cost-by-platform-2026': 'ecommerce platform'}
BAD_LOCAL = ('noreply', 'no-reply', 'donotreply', 'example', 'sentry', 'wixpress', 'privacy', 'legal', 'abuse', 'postmaster', 'webmaster',
             'careers', 'jobs', 'recruit', 'hr@', 'billing', 'invoice', 'support', 'help@', 'press', 'security', 'dpo', 'gdpr', 'unsubscribe')
ROLE_ORDER = ('partnership', 'marketing', 'hello', 'hi@', 'hey', 'contact', 'info', 'sales', 'team', 'office', 'enquir', 'inquir', 'studio', 'mail@')
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]{1,40}@[A-Za-z0-9.-]{2,60}\.[A-Za-z]{2,10}')


def domain(url):
    try:
        h = urllib.parse.urlparse(url if '//' in url else 'https://' + url).netloc.lower()
        return h[4:] if h.startswith('www.') else h
    except Exception:
        return ''


def fetch(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'en'})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read(900_000).decode('utf-8', 'replace')
    except Exception:
        return ''


def cf_decode(page):
    out = []
    for h in re.findall(r'data-cfemail="([0-9a-fA-F]+)"', page) + re.findall(r'/cdn-cgi/l/email-protection#([0-9a-fA-F]+)', page):
        try:
            k = int(h[:2], 16)
            out.append(''.join(chr(int(h[i:i + 2], 16) ^ k) for i in range(2, len(h), 2)))
        except ValueError:
            pass
    return ' '.join(out)


def emails_on(page, dom):
    text = html.unescape(page) + ' ' + cf_decode(page)
    found = []
    base = dom.split('.')[-2] if dom.count('.') else dom
    for e in EMAIL_RE.findall(text):
        e = e.strip('.').lower()
        ed = e.split('@')[1]
        if any(b in e for b in BAD_LOCAL) or e.endswith(('.png', '.jpg', '.gif', '.webp', '.svg', '.js', '.css')):
            continue
        if ed == dom or ed.endswith('.' + dom) or dom.endswith('.' + ed) or base in ed:
            if e not in found:
                found.append(e)
    def rank(e):
        loc = e.split('@')[0] + '@'
        for i, r in enumerate(ROLE_ORDER):
            if loc.startswith(r) or r in loc:
                return i
        return len(ROLE_ORDER) + (0 if '.' not in loc else 1)
    return sorted(found, key=rank)


def market_of(dom, page, country=''):
    c = (country or '').lower()
    for k, m in (('united kingdom', 'uk'), ('uk', 'uk'), ('england', 'uk'), ('australia', 'australia'), ('ireland', 'ireland'), ('canada', 'other'),
                 ('new zealand', 'other'), ('germany', 'western_europe'), ('netherlands', 'western_europe'), ('france', 'western_europe'),
                 ('spain', 'western_europe'), ('sweden', 'western_europe'), ('denmark', 'western_europe'), ('poland', 'eastern_europe'),
                 ('romania', 'eastern_europe'), ('india', 'south_asia'), ('united states', 'us'), ('usa', 'us')):
        if c == k or (len(k) > 3 and k in c):
            return m
    for tld, m in (('.co.uk', 'uk'), ('.uk', 'uk'), ('.com.au', 'australia'), ('.au', 'australia'), ('.ie', 'ireland'), ('.ca', 'other'), ('.nz', 'other'),
                   ('.de', 'western_europe'), ('.nl', 'western_europe'), ('.fr', 'western_europe'), ('.es', 'western_europe'), ('.it', 'western_europe'),
                   ('.se', 'western_europe'), ('.dk', 'western_europe'), ('.be', 'western_europe'), ('.ch', 'western_europe'), ('.at', 'western_europe'),
                   ('.pl', 'eastern_europe'), ('.ro', 'eastern_europe'), ('.in', 'south_asia'), ('.eu', 'western_europe')):
        if dom.endswith(tld):
            return m
    p = page[:300_000]
    hints = (('uk', (r'\+44[\s(]', r'\bLondon\b', r'\bManchester\b', r'United Kingdom', r'\bVAT (No|Reg)')),
             ('australia', (r'\+61[\s(]', r'\bSydney\b', r'\bMelbourne\b', r'\bABN\b')),
             ('other', (r'\bToronto\b', r'\bVancouver\b', r'\bMontreal\b', r'\bAuckland\b')),
             ('western_europe', (r'\+49[\s(]', r'\+31[\s(]', r'\bAmsterdam\b', r'\bBerlin\b', r'\+33[\s(]', r'\bDublin\b', r'\+353')))
    for m, pats in hints:
        if sum(1 for x in pats if re.search(x, p)) >= 1:
            return m
    return 'us'


def discover(item, cache):
    dom = item['dom']
    if dom in cache:
        return cache[dom]
    root = 'https://' + dom
    res = {'email': '', 'found_at': '', 'market': 'us'}
    home = ''
    cand_email = (item.get('email') or '').lower()
    if any(b in cand_email for b in BAD_LOCAL):
        cand_email = ''  # a support@ or careers@ box is not where a sponsorship offer belongs, even if research wrote it down
    pages = [item.get('found_at') or ''] if cand_email and (item.get('found_at') or '').startswith('http') else []
    pages += [root, root + '/contact', root + '/contact-us', root + '/about', root + '/about-us']
    for u in pages:
        if not u:
            continue
        pg = fetch(u)
        if not pg:
            continue
        if u == root:
            home = pg
        found = emails_on(pg, dom)
        if cand_email and (cand_email in found or cand_email in (html.unescape(pg) + cf_decode(pg)).lower()):
            res.update(email=cand_email, found_at=u)
            break
        if found and not cand_email:
            res.update(email=found[0], found_at=u)
            break
        if found and cand_email and u != pages[0]:
            res.update(email=found[0], found_at=u)
            break
    res['market'] = market_of(dom, home or '', item.get('country', ''))
    cache[dom] = res
    return res


def main():
    max_fetch = int(sys.argv[sys.argv.index('--max-fetch') + 1]) if '--max-fetch' in sys.argv else 400
    cache = json.load(open(CACHE, encoding='utf-8')) if os.path.exists(CACHE) else {}
    existing = list(csv.DictReader(open(OUT, encoding='utf-8', newline=''))) if os.path.exists(OUT) else []
    have = {domain(r['website']) for r in existing}
    items = {}
    for path in sorted(glob.glob(D + 'sponsor-prospects-*.csv')):
        for r in csv.DictReader(open(path, encoding='utf-8', newline='')):
            dom = domain(r.get('website') or '')
            slug = (r.get('page_slug') or '').strip().strip('/').split('/')[-1]
            if not dom or not slug or dom in items or dom in have or 'stickydigital' in dom:
                continue
            vs = re.match(r'^([a-z0-9-]+)-vs-([a-z0-9-]+?)-cost', slug)
            lab_of = lambda w: next((lab for v, (lab, _s) in VENDOR_PAGE.items() if v == w), w.replace('-', ' ').title())
            topic = (f'{lab_of(vs.group(1))} vs {lab_of(vs.group(2))}' if vs else None) \
                or next((lab for v, (lab, _s) in VENDOR_PAGE.items() if v in slug), None) or SLUG_TOPIC.get(slug)
            if not topic:
                continue
            items[dom] = {'dom': dom, 'name': (r.get('company') or '').strip(), 'website': 'https://' + dom, 'topic': topic, 'page_slug': slug,
                          'partner_status': (r.get('partner_status') or '').strip(), 'email': (r.get('contact_email') or '').strip(),
                          'found_at': (r.get('found_at') or '').strip(), 'country': ''}
    bulk = D + 'sponsor-directory-bulk.csv'
    if os.path.exists(bulk):
        for r in csv.DictReader(open(bulk, encoding='utf-8', newline='')):
            dom = domain(r.get('website') or '')
            v = (r.get('vendor') or '').strip().lower()
            if not dom or v not in VENDOR_PAGE or dom in items or dom in have or 'stickydigital' in dom:
                continue
            lab, slug = VENDOR_PAGE[v]
            tier = (r.get('tier') or '').strip()
            items[dom] = {'dom': dom, 'name': (r.get('company') or '').strip(), 'website': 'https://' + dom, 'topic': lab, 'page_slug': slug,
                          'partner_status': (f'{lab} {tier} partner' if tier else f'{lab} partner'), 'email': '', 'found_at': '',
                          'country': (r.get('country') or '').strip()}
    todo = [it for it in items.values() if it['dom'] not in cache][:max_fetch]
    print(f'{len(items)} new companies, {len(todo)} to fetch now ({len(items) - len(todo)} cached or over --max-fetch)', flush=True)
    with ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(lambda it: discover(it, cache), todo))
    json.dump(cache, open(CACHE, 'w', encoding='utf-8'), indent=0)
    rows = existing[:]
    added = with_email = 0
    for dom, it in items.items():
        c = cache.get(dom)
        if not c:
            continue
        added += 1
        with_email += 1 if c['email'] else 0
        rows.append({'name': it['name'], 'email': c['email'], 'market': c['market'], 'website': it['website'], 'topic': it['topic'],
                     'page_slug': it['page_slug'], 'partner_status': it['partner_status'], 'found_at': c['found_at'], 'sent': ''})
    with io.open(OUT, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
    by = {}
    for r in rows:
        if r['email'] and not r['sent']:
            by[r['market']] = by.get(r['market'], 0) + 1
    print(json.dumps({'rows': len(rows), 'added': added, 'added_with_email': with_email, 'unsent_with_email_by_market': by}))


if __name__ == '__main__':
    main()

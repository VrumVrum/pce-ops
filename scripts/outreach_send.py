# -*- coding: utf-8 -*-
"""Agency outreach from hello@projectcostestimator.com via Resend (the identity Thunderbird
sends with). Authorised by the owner on 2026-09-20 ("poti singur prin thunderbird sa trimiti
mails la agentii").

  python outreach_send.py test                       -> the first message to the owner's test mailbox
  python outreach_send.py send [--csv path] [--limit N] [--gap S]
                                                    -> every row of a hand-made list with an email,
                                                       a specific line and no `sent` date
  python outreach_send.py daily --market us|australia [--limit N]
                                                    -> the discovered list, best fit score first,
                                                       capped per day (data/outreach-config.json)
  python outreach_send.py followup [--limit N]      -> one short nudge, once, to agencies written
                                                       to N days ago with no click / reply / listing
  python outreach_send.py preview --market au        -> print the next 5 messages, send nothing

Every send is appended to data/outreach-sent-YYYY-MM-DD.jsonl (ref, Resend id, address, subject,
body); the CSV row gets `sent` = today. Replies arrive at hello@ -> Gmail -> the Thunderbird
'Project Cost Estimator' local Inbox and are read by outreach_sync.py into /admin/outreach.

Rules that never bend: one true line per agency taken from their own site or their own directory
listing (never a number we do not have); a working opt-out line; US recipients get the postal
address CAN-SPAM requires (config `postal_address`) and are skipped while it is empty; bounced
and declined addresses are never written to again; one follow-up at most.
"""
import csv, io, json, re, sys, glob, time, datetime, urllib.request, urllib.error
sys.stdout.reconfigure(encoding='utf-8')
D = 'C:/Users/Flo/Downloads/pce-ops/data/'
CSV = D + 'outreach-agencies-2026-09-20.csv'
if '--csv' in sys.argv:
    CSV = sys.argv[sys.argv.index('--csv') + 1]
DISCOVERED = D + 'outreach-agencies-discovered.csv'
TEST_TO = 'florin.florea84@yahoo.com'
FROM = 'Florin Florea (Project Cost Estimator) <hello@projectcostestimator.com>'  # no comma: a bare comma splits the display name into two addresses in some MTAs
REPLY_TO = 'hello@projectcostestimator.com'
env = open('C:/Users/Flo/Downloads/scopebit/.env.vercel', encoding='utf-8').read()
KEY = re.search(r'^RESEND_API_KEY="?([^"' + chr(13) + chr(10) + r']+)"?', env, re.M).group(1).strip()
CFG = {'postal_address': '', 'daily_cap': {'us': 25, 'australia': 25}, 'min_score': 60, 'followup_after_days': 6}
try: CFG.update(json.load(open(D + 'outreach-config.json', encoding='utf-8-sig')))     # -sig: PowerShell writes a BOM
except Exception as _e: print('outreach-config.json not read:', _e)
TODAY = datetime.date.today().isoformat()
LOG = D + f'outreach-sent-{TODAY}.jsonl'

MARKET = {'eastern_europe': 'Eastern Europe', 'uk': 'the UK and Ireland', 'western_europe': 'Western Europe', 'us': 'the US', 'australia': 'Australia', 'south_asia': 'South and Southeast Asia'}
PLATFORM = {'shopify': 'Shopify', 'shopify_plus': 'Shopify Plus', 'wordpress': 'WordPress', 'woocommerce': 'WooCommerce', 'webflow': 'Webflow', 'magento2': 'Magento', 'magento': 'Magento', 'bigcommerce': 'BigCommerce', 'wix': 'Wix', 'squarespace': 'Squarespace', 'custom': 'custom-build', 'ecommerce': 'ecommerce', 'web-design': 'web design'}
NICHE = {'dental': 'dental practices', 'law': 'law firms', 'medical': 'medical practices', 'restaurant': 'restaurants', 'real-estate': 'real estate', 'trades': 'trades and home services', 'accounting': 'accounting firms', 'fitness': 'gyms and fitness studios',
         'hospitality': 'hotels and hospitality', 'nonprofit': 'churches and nonprofits', 'construction': 'construction companies', 'healthcare': 'healthcare', 'veterinary': 'veterinary clinics', 'beauty': 'salons and spas', 'finance': 'financial advisors', 'saas': 'SaaS and startups', 'smb': 'small businesses'}

# One true line per agency, from their own site (harvested 2026-09-20). Never a number we do not have.
SPECIFIC = {
    'Softsite': 'you build WordPress, React and Next.js sites for Romanian businesses, mobile-first and SEO-ready from the start',
    'WOLFPACK DIGITAL': 'you design, build and launch web and mobile products for brands from Cluj',
    'Osom Studio': 'you are a WordPress and WooCommerce specialist studio',
    'Brandweb': 'you build custom software products and websites out of Romania',
    'Grapefruit': 'the digital product and web work you do out of Iași',
    'Brand Active': 'you are a certified Shopify Plus partner covering Poland and CEE',
    'Zdobywcy Sieci': 'you build WooCommerce stores at a one-time price with no monthly fees',
    'Broker Media': 'you build WordPress and WooCommerce projects for clients in Poland and abroad',
    'PP Design Studio': 'you build WooCommerce stores for small and mid-size companies with a year of support included',
    'JCD.pl': 'the WordPress and WooCommerce implementations your Warsaw software house ships',
    'WebPanda': 'you build multilingual WordPress sites and WooCommerce stores',
    'The New Look': 'your WordPress and WooCommerce work from Łódź and Warsaw',
    'ProWP': 'your WooCommerce shops with payment, ERP and logistics integrations',
    'Ajmer': 'your WooCommerce store builds',
    'Hallwil': 'your web design subscription covering Webflow, WordPress and Shopify',
    'Charle': 'you are a Shopify Partner agency in Manchester',
    'MadeByShape': 'you are a small, award-winning team building Shopify and WordPress sites in Manchester',
    'Pixel Kicks': 'you are a Manchester Shopify Partner and WordPress agency',
    'Create8': 'you do Shopify design, branding and paid media for eCommerce and B2B brands in Manchester',
    'Flex Commerce': 'your Shopify Plus work from Manchester and Liverpool',
    'Stepholt': 'your Shopify design and development from the North West',
    'Weblogic': 'you are a WooCommerce Pro Partner building lead-generating WordPress sites in Ireland',
    'Visible': 'you build WordPress sites for Irish SMEs, from tradespeople to professional practices (freelancers are welcome on the list too)',
    'Nineline Digital': 'your WordPress web design in Dublin with SEO built in',
    'Chris Flynn Design': 'your UX-led WordPress work in Dublin (freelancers are welcome on the list too)',
    'Eclipso Studio': 'you are a certified Webflow partner in Berlin building for startups',
    'Flowtrix': 'your B2B Webflow design and development in Berlin',
    'Blocks & Colors': 'your Webflow and web app work in Berlin',
    'The Weather': 'the websites and digital products you build from Berlin and Prague',
    'Wezz e-Commerce': 'your 15+ years of Magento webshops from Amsterdam',
    'Wedigify': 'your technical, data-driven Magento and Hyvä work in Rotterdam',
    'Shopcommerce': 'your webshops on Magento, Hyvä and Shopify since 2008',
    'AGMA Studio': 'your web design work in Sofia since 2013',
    'Mooshfy': 'the high-converting Shopify stores your Lisbon team builds',
    'Sweans': 'your Shopify work for brands in Lisbon and London',
    'Brandability': 'your integrated marketing and web work in Lisbon',
    'UPQODE': 'your WordPress design and development studio in Austin',
    'Austin Web Design': 'your affordable website design for small and home-based businesses in Austin since 2001',
}
FIRST_NAME = {'Visible': 'Frank', 'Chris Flynn Design': 'Chris', 'Sweans': 'Ajay'}
# Extra lists carry their specific lines in data/outreach-specific-*.json ({name: {line, first_name?}}).
for _f in glob.glob(D + 'outreach-specific-*.json'):
    for _n, _v in json.load(open(_f, encoding='utf-8')).items():
        SPECIFIC[_n] = _v['line'] if isinstance(_v, dict) else _v
        if isinstance(_v, dict) and _v.get('first_name'): FIRST_NAME[_n] = _v['first_name']

def slug_of(name):
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', name.lower())).strip('-')[:40]

def their_line(row):
    """A true line about the agency: their own tagline, quoted, or what their own directory
    listing says they do. Nothing invented; None means we do not write to them."""
    tag = (row.get('tagline') or '').strip().strip('"\u201c\u201d')
    if 20 <= len(tag) <= 300 and '@' not in tag and 'http' not in tag and not re.search(r'\b(cookie|javascript|browser|404|error)\b', tag, re.I):
        if len(tag) > 150:
            cut = re.split(r'(?<=[.!?])\s', tag)[0]
            tag = cut if 20 <= len(cut) <= 150 else tag[:147].rsplit(' ', 1)[0] + '…'
        return f'your site says "{tag.rstrip(".!")}"'
    plats = [PLATFORM.get(p, p) for p in row.get('platforms', '').split(',') if p and p != 'web-design']
    niches = [NICHE[n] for n in row.get('niche', '').split(',') if n in NICHE]
    city = (row.get('city') or '').strip()
    if plats and niches: return f'you build {plats[0]} sites for {niches[0]}' + (f' in {city}' if city else '')
    if niches: return f'you build websites for {niches[0]}' + (f' in {city}' if city else '')
    if plats: return f'your {plats[0]} work' + (f' in {city}' if city else '')
    return None

def compose(row):
    name = row['name']
    ref = row.get('ref') or ('out-' + slug_of(name))
    market_key = row['market'].split(',')[0]
    market = MARKET.get(market_key, row['market'])
    platform = PLATFORM.get(row['platforms'].split(',')[0], row['platforms'].split(',')[0]) if row.get('platforms') else 'web design'
    specific = SPECIFIC.get(name) or their_line(row)
    if not specific:
        return None
    greet = f"Hi {FIRST_NAME[name]}," if name in FIRST_NAME else f"Hi {name} team,"
    # Since 21 Sep the product in the first message is Embed Pro (value on day one, whatever our
    # traffic does); the listing is the free part. Every claim below is what the licence does today
    # (src/app/embed/EmbedProOffer.tsx): own CTA target, own brand line, own colours, no credit, stats.
    subject = f"A website cost calculator on {name}'s site, and a free agency listing"
    postal = ('\n' + CFG['postal_address'].strip() + '\n') if CFG.get('postal_address', '').strip() else ''
    body = f"""{greet}

I run projectcostestimator.com, an independent website cost calculator (we don't build sites). Two things for {name}, since {specific}:

1. The calculator on your own site. The visitor prices their project on your page and the button sends them to your contact form; your name on it, your colours, no credit line, loads and clicks counted per day. Embed Pro is $29 a month for one domain, cancel any time.

2. A free listing here. People who finish an estimate can ask for quotes, and the request, with type, platform, budget band and deadline already filled in, goes to listed {platform} agencies that serve {market}. No commission, no contract, nothing billed for requests right now.

Both start from one two-minute form: https://projectcostestimator.com/for-agencies?ref={ref}

If it's not for you, reply "no" and I won't write again.

Florin Florea
founder, Project Cost Estimator
hello@projectcostestimator.com{postal}"""
    return subject, body

# Cost pages that exist today, per niche tag: the follow-up can offer the single "featured builder"
# slot on the page their prospects read. Only real pages; never a page we do not have.
NICHE_PAGE = {'law': '/law-firm-website-cost', 'restaurant': '/restaurant-website-cost', 'nonprofit': '/nonprofit-website-cost', 'real-estate': '/real-estate-website-cost',
              'healthcare': '/healthcare-website-cost', 'medical': '/healthcare-website-cost', 'dental': '/healthcare-website-cost', 'ecommerce': '/ecommerce-cost-calculator', 'shopify': '/ecommerce-cost-calculator', 'wordpress': '/wordpress-website-cost'}

def compose_followup(row):
    name = row['name']; ref = row.get('ref') or ('out-' + slug_of(name))
    greet = f"Hi {FIRST_NAME[name]}," if name in FIRST_NAME else f"Hi {name} team,"
    postal = ('\n' + CFG['postal_address'].strip() + '\n') if CFG.get('postal_address', '').strip() else ''
    subject = f"Re: A website cost calculator on {name}'s site, and a free agency listing"
    tags = [t for t in (row.get('niche') or '').split(',') + (row.get('platforms') or '').split(',') if t in NICHE_PAGE]
    slot = ''
    if tags:
        page = NICHE_PAGE[tags[0]]; price = CFG.get('slot_price', '$79')
        slot = f"""
There is also one "featured builder" slot on our {page.strip('/').replace('-', ' ')} page, the page your prospects read before they ask for quotes: one agency per country, {price} a month, and I send you the page's real visitor numbers before you decide. Reply "slot" if you want them.
"""
    body = f"""{greet}

A short follow-up on my note from last week. Still open for {name}: the free listing (quote requests with the budget band already set) and the calculator on your own site at $29 a month.
{slot}
The form is two minutes: https://projectcostestimator.com/for-agencies?ref={ref}

If not, no reply needed; this is the last message from me.

Florin Florea
founder, Project Cost Estimator
hello@projectcostestimator.com{postal}"""
    return subject, body

def send(to, subject, body, tag):
    payload = {'from': FROM, 'to': [to], 'reply_to': REPLY_TO, 'subject': subject, 'text': body, 'tags': [{'name': 'campaign', 'value': tag}]}
    req = urllib.request.Request('https://api.resend.com/emails', data=json.dumps(payload).encode(), headers={'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json', 'User-Agent': 'pce-outreach/1.0 (+https://projectcostestimator.com)'}, method='POST')
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def log(entry):
    with io.open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

def sent_log():
    """Every send so far, from every daily log: {ref: [entries]} and {email: [entries]}."""
    by_ref, by_email = {}, {}
    for f in sorted(glob.glob(D + 'outreach-sent-*.jsonl')):
        for line in open(f, encoding='utf-8'):
            try: e = json.loads(line)
            except Exception: continue
            if e.get('mode') not in ('send', 'daily', 'followup') or not e.get('resend'): continue
            r = e.get('ref') or ('out-' + slug_of(e.get('agency', '')))
            by_ref.setdefault(r, []).append(e); by_email.setdefault((e.get('to') or '').lower(), []).append(e)
    return by_ref, by_email

def board():
    try: return {p['ref']: p for p in json.load(open(D + 'outreach-prospects.json', encoding='utf-8'))['prospects']}
    except Exception: return {}

def mark(path, row, col, value):
    """Read-modify-write one row (matched by ref, else email): the verifier may be adding rows
    to the same file while we send, so never write back the list we loaded at start."""
    import os
    fresh = list(csv.DictReader(open(path, encoding='utf-8', newline='')))
    fields = list(fresh[0].keys()) if fresh else list(row.keys())
    for r in fresh:
        if (row.get('ref') and r.get('ref') == row['ref']) or (r.get('email') and r['email'].lower() == row['email'].lower()):
            r[col] = value
    with io.open(path + '.tmp', 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); w.writeheader(); w.writerows(fresh)
    for attempt in range(6):
        try: os.replace(path + '.tmp', path); break
        except PermissionError:
            if attempt == 5: raise
            time.sleep(2)

def us_blocked(market_key):
    return market_key == 'us' and not CFG.get('postal_address', '').strip()

def deliver(rows, path, fields, pick, mode, tag, limit, gap, composer=compose):
    by_ref, by_email = sent_log(); n = 0; skipped_us = 0
    for row in rows:
        if not pick(row): continue
        c = composer(row)
        if not c:
            print('skip (no true line):', row['name']); continue
        if us_blocked(row['market'].split(',')[0]) and mode != 'followup':
            skipped_us += 1; continue
        if mode != 'followup' and (row.get('ref') in by_ref or row['email'].lower() in by_email):
            row['sent'] = row.get('sent') or by_ref.get(row.get('ref'), by_email.get(row['email'].lower()))[0]['ts'][:10]; continue
        subject, body = c
        try:
            res = send(row['email'], subject, body, tag)
        except urllib.error.HTTPError as e:
            err = e.read().decode('utf-8', 'replace')[:200]
            print('ERROR', row['name'], row['email'], e.code, err)
            log({'ts': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'mode': mode, 'to': row['email'], 'agency': row['name'], 'ref': row.get('ref'), 'error': err})
            if e.code == 429: print('rate limited by Resend, stopping for today'); break
            continue
        if mode == 'followup': row['reply'] = ((row.get('reply') or '') + f' followup:{TODAY}').strip(); mark(path, row, 'reply', row['reply'])
        else: row['sent'] = TODAY; mark(path, row, 'sent', TODAY)
        log({'ts': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'mode': mode, 'to': row['email'], 'agency': row['name'], 'ref': row.get('ref'), 'market': row['market'], 'subject': subject, 'body': body, 'resend': res})
        n += 1
        print(f'{mode} {n}: {row["name"]} <{row["email"]}> ref={row.get("ref")} id={res.get("id")}')
        if n >= limit: break
        time.sleep(gap)
    if skipped_us: print(f'{skipped_us} US rows held: no postal address in data/outreach-config.json (CAN-SPAM)')
    print(f'done, {mode} sent {n}')
    return n

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'test'
    limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else None
    gap = int(sys.argv[sys.argv.index('--gap') + 1]) if '--gap' in sys.argv else 120
    market = sys.argv[sys.argv.index('--market') + 1] if '--market' in sys.argv else None
    market = {'au': 'australia'}.get(market, market)
    if mode in ('daily', 'preview', 'followup'):
        path = DISCOVERED
    else:
        path = CSV
    rows = list(csv.DictReader(open(path, encoding='utf-8', newline='')))
    fields = list(rows[0].keys())
    if mode == 'test':
        row = next(r for r in rows if r['email'] and compose(r))
        subject, body = compose(row)
        res = send(TEST_TO, '[TEST] ' + subject, body, 'outreach-test')
        log({'ts': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'mode': 'test', 'to': TEST_TO, 'agency': row['name'], 'ref': row.get('ref'), 'subject': subject, 'body': body, 'resend': res})
        print('test sent to', TEST_TO, 'for', row['name'], res)
        return
    if mode == 'send':
        deliver(rows, path, fields, lambda r: bool(r['email']) and not r.get('sent'), 'send', 'outreach-' + TODAY, limit or 999, gap)
        return
    minscore = int(CFG.get('min_score', 60)); b = board()
    def eligible(r):
        if not r['email'] or r.get('sent') or r.get('status') != '200': return False
        if market and r['market'].split(',')[0] != market: return False
        if int(r.get('score') or 0) < minscore or 'offshore' in (r.get('signals') or ''): return False
        p = b.get(r.get('ref'))
        if p and p['status'] in ('declined', 'bounced', 'listed', 'replied'): return False
        return True
    ranked = sorted(rows, key=lambda r: -int(r.get('score') or 0))
    if mode == 'preview':
        k = 0
        for r in ranked:
            if not eligible(r): continue
            c = compose(r)
            if not c: continue
            print('=' * 70); print('TO:', r['email'], '| score', r['score'], '|', r['market'], '|', r.get('city')); print('SUBJECT:', c[0]); print(c[1]); k += 1
            if k >= (limit or 5): break
        print('eligible now:', sum(1 for r in ranked if eligible(r) and compose(r)))
        return
    if mode == 'daily':
        cap = int(CFG.get('daily_cap', {}).get(market or 'us', 25))
        deliver(ranked, path, fields, eligible, 'daily', 'outreach-daily-' + TODAY, limit or cap, gap)
        return
    if mode == 'followup':
        by_ref, _ = sent_log(); days = int(CFG.get('followup_after_days', 6))
        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()
        def due(r):
            if not r['email'] or 'followup:' in (r.get('reply') or ''): return False
            es = by_ref.get(r.get('ref')) or []
            if not es or any(e.get('mode') == 'followup' for e in es) or es[0]['ts'] > cutoff: return False
            p = b.get(r.get('ref'))
            return not (p and p['status'] in ('clicked', 'replied', 'listed', 'declined', 'bounced'))
        deliver(rows, path, fields, due, 'followup', 'outreach-followup-' + TODAY, limit or 40, gap, composer=compose_followup)
        return
    print('unknown mode', mode)

if __name__ == '__main__':
    main()

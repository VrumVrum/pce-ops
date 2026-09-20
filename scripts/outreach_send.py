# -*- coding: utf-8 -*-
"""Agency outreach from hello@projectcostestimator.com via Resend (the identity
Thunderbird sends with). Authorised by the owner on 2026-09-20 for this list only.

  python outreach_send.py test        -> the first message to the owner's test mailbox
  python outreach_send.py send        -> every row with an email and no `sent` date, 2 min apart
  python outreach_send.py send --limit 10

Each send is appended to data/outreach-sent-2026-09-20.jsonl (Resend id, address,
subject, body) and the CSV row gets `sent` = today. Replies arrive at hello@ ->
Gmail -> the Thunderbird 'Project Cost Estimator' local Inbox.
"""
import csv, io, json, re, sys, time, datetime, urllib.request, urllib.error
sys.stdout.reconfigure(encoding='utf-8')
D = 'C:/Users/Flo/Downloads/pce-ops/data/'
CSV = D + 'outreach-agencies-2026-09-20.csv'
LOG = D + 'outreach-sent-2026-09-20.jsonl'
TEST_TO = 'florin.florea84@yahoo.com'
FROM = 'Florin Florea (Project Cost Estimator) <hello@projectcostestimator.com>'  # no comma: a bare comma splits the display name into two addresses in some MTAs
REPLY_TO = 'hello@projectcostestimator.com'
env = open('C:/Users/Flo/Downloads/scopebit/.env.vercel', encoding='utf-8').read()
KEY = re.search(r'^RESEND_API_KEY="?([^"\r\n]+)"?', env, re.M).group(1)

MARKET = {'eastern_europe': 'Eastern Europe', 'uk': 'the UK and Ireland', 'western_europe': 'Western Europe', 'us': 'the US'}
PLATFORM = {'shopify': 'Shopify', 'shopify_plus': 'Shopify Plus', 'wordpress': 'WordPress', 'woocommerce': 'WooCommerce', 'webflow': 'Webflow', 'magento2': 'Magento', 'custom': 'custom-build'}

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

def compose(row):
    name = row['name']
    market = MARKET.get(row['market'].split(',')[0], row['market'])
    platform = PLATFORM.get(row['platforms'].split(',')[0], row['platforms'].split(',')[0])
    specific = SPECIFIC.get(name)
    if not specific:
        return None
    greet = f"Hi {FIRST_NAME[name]}," if name in FIRST_NAME else f"Hi {name} team,"
    subject = f"Quote requests with a budget attached — free listing for {name}"
    body = f"""{greet}

I run projectcostestimator.com, an independent website cost calculator (we don't build sites). People price their project on it, then ask for quotes: the request comes with the type, platform, market, size, budget band and deadline already filled in.

I'm listing a small number of {platform} agencies that serve {market}, and {name} fits: {specific}.

The listing is free, no commission, no contract; requests are routed to listed agencies at no charge right now. If it's useful, the form takes two minutes: https://projectcostestimator.com/for-agencies

If it's not for you, reply "no" and I won't write again.

Florin Florea
founder, Project Cost Estimator
hello@projectcostestimator.com
"""
    return subject, body

def send(to, subject, body, tag):
    payload = {'from': FROM, 'to': [to], 'reply_to': REPLY_TO, 'subject': subject, 'text': body, 'tags': [{'name': 'campaign', 'value': tag}]}
    req = urllib.request.Request('https://api.resend.com/emails', data=json.dumps(payload).encode(), headers={'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json', 'User-Agent': 'pce-outreach/1.0 (+https://projectcostestimator.com)'}, method='POST')
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def log(entry):
    with io.open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'test'
    limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 999
    gap = int(sys.argv[sys.argv.index('--gap') + 1]) if '--gap' in sys.argv else 120
    rows = list(csv.DictReader(open(CSV, encoding='utf-8')))
    fields = list(rows[0].keys())
    today = datetime.date.today().isoformat()
    if mode == 'test':
        row = next(r for r in rows if r['email'] and compose(r))
        subject, body = compose(row)
        res = send(TEST_TO, '[TEST] ' + subject, body, 'outreach-test')
        log({'ts': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'mode': 'test', 'to': TEST_TO, 'agency': row['name'], 'subject': subject, 'body': body, 'resend': res})
        print('test sent to', TEST_TO, 'for', row['name'], res)
        return
    n = 0
    for row in rows:
        if not row['email'] or row.get('sent'):
            continue
        c = compose(row)
        if not c:
            print('skip (no specific line):', row['name']); continue
        subject, body = c
        try:
            res = send(row['email'], subject, body, 'outreach-2026-09-20')
        except urllib.error.HTTPError as e:
            err = e.read().decode('utf-8', 'replace')[:200]
            print('ERROR', row['name'], row['email'], e.code, err)
            log({'ts': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'mode': 'send', 'to': row['email'], 'agency': row['name'], 'error': err})
            continue
        row['sent'] = today
        log({'ts': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'mode': 'send', 'to': row['email'], 'agency': row['name'], 'subject': subject, 'body': body, 'resend': res})
        with io.open(CSV, 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
        n += 1
        print(f'sent {n}: {row["name"]} <{row["email"]}> id={res.get("id")}')
        if n >= limit:
            break
        time.sleep(gap)
    print('done, sent', n)

if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""Verify a candidate list (name, website, market, platforms, city, niche): does the
site answer, where is its contact page, a public email address (mailto: or plain
text, own domain preferred), one line of theirs to quote (meta description / H1).

  python outreach_harvest2.py data/outreach-candidates-us-au-2026-09-20.csv data/outreach-agencies-us-au-2026-09-20.csv
"""
import csv, io, re, sys, html, urllib.request, urllib.error, concurrent.futures as cf
sys.stdout.reconfigure(encoding='utf-8')
SRC, DST = sys.argv[1], sys.argv[2]
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36 pce-outreach-check', 'Accept': 'text/html,*/*;q=0.8', 'Accept-Language': 'en'}
CONTACT_RE = re.compile(r'href="([^"]*(?:contact|get-in-touch|getintouch|quote|estimate|start-a-project|lets-talk|let-s-talk|enquir)[^"]*)"', re.I)
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
SKIP = ('sentry', 'wixpress', 'example', 'yourdomain', 'email@', 'name@', 'user@', 'domain.com', '.png', '.jpg', '.svg', '.gif', '.webp', 'noreply', 'no-reply', 'privacy@', 'gdpr@', 'dpo@', 'jobs@', 'career', 'press@', 'billing@', 'abuse@', 'support@', 'help@', 'accounts@', 'invoice')
GENERIC = ('hello', 'info', 'contact', 'office', 'hi', 'team', 'sales', 'mail', 'studio', 'enquiries', 'enquiry', 'admin', 'welcome', 'newbusiness', 'new-business', 'projects')

def get(url):
    r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20)
    return r.geturl(), r.read(400000).decode('utf-8', 'replace')

def host_of(u):
    m = re.match(r'https?://([^/]+)', u); return (m.group(1) if m else '').lower().replace('www.', '')

def emails_in(h, site_host):
    found = [html.unescape(m.group(1)).strip().lower() for m in re.finditer(r'href="mailto:([^"?]+)', h, re.I)]
    found += [m.group(0).lower() for m in EMAIL_RE.finditer(html.unescape(re.sub(r'<[^>]+>', ' ', h)))]
    out = []
    for e in found:
        if any(s in e for s in SKIP) or e in out: continue
        out.append(e)
    own = [e for e in out if e.split('@')[1].replace('www.', '') in (site_host, site_host.split('.', 1)[-1])] if site_host else []
    own_generic = [e for e in own if e.split('@')[0] in GENERIC]
    return own_generic or own or out

def tagline_in(h):
    for pat in [r'<meta[^>]+property="og:description"[^>]+content="([^"]{20,300})"', r'<meta[^>]+name="description"[^>]+content="([^"]{20,300})"', r'<meta[^>]+content="([^"]{20,300})"[^>]+name="description"']:
        m = re.search(pat, h, re.I)
        if m: return re.sub(r'\s+', ' ', html.unescape(m.group(1))).strip()
    m = re.search(r'<h1[^>]*>(.*?)</h1>', h, re.S | re.I)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', m.group(1)))).strip()[:200] if m else ''

def work(row):
    site = row['website']; host = host_of(site)
    out = dict(row); out.update(contact='', email='', email_alts='', email_source='', tagline='', status='', title='')
    try:
        final, h = get(site)
    except urllib.error.HTTPError as e:
        out['status'] = str(e.code); return out
    except Exception as e:
        out['status'] = 'ERR ' + str(e)[:40]; return out
    out['status'] = '200'
    t = re.search(r'<title[^>]*>(.*?)</title>', h, re.S | re.I)
    out['title'] = re.sub(r'\s+', ' ', html.unescape(t.group(1))).strip()[:80] if t else ''
    out['tagline'] = tagline_in(h)[:220]
    contact = ''
    for m in CONTACT_RE.finditer(h):
        href = m.group(1)
        if href.startswith(('mailto:', '#', 'tel:')) or 'wp-json' in href: continue
        if href.startswith('/'): href = re.match(r'https?://[^/]+', final).group(0) + href
        elif not href.startswith('http'): href = final.rstrip('/') + '/' + href
        contact = href; break
    out['contact'] = contact
    es = emails_in(h, host); src = site
    if not es and contact:
        try:
            _, h2 = get(contact); es = emails_in(h2, host); src = contact
            if not out['tagline']: out['tagline'] = tagline_in(h2)[:220]
        except Exception:
            pass
    if es:
        out['email'], out['email_alts'], out['email_source'] = es[0], ' '.join(es[1:4]), src
    return out

rows = list(csv.DictReader(open(SRC, encoding='utf-8')))
with cf.ThreadPoolExecutor(8) as ex:
    rows = list(ex.map(work, rows))
fields = ['name', 'website', 'contact', 'email', 'email_alts', 'email_source', 'tagline', 'city', 'market', 'platforms', 'niche', 'status', 'title', 'sent', 'reply', 'ref']
def slug(n): return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', n.lower())).strip('-')[:40]
with io.open(DST, 'w', encoding='utf-8', newline='') as f:
    w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); w.writeheader()
    for r in rows:
        r['sent'] = ''; r['reply'] = ''; r['ref'] = 'out-' + slug(r['name'])
        w.writerow({k: r.get(k, '') for k in fields})
ok = [r for r in rows if r['status'] == '200']
print('candidates', len(rows), 'reachable', len(ok), 'with email', sum(1 for r in ok if r['email']), 'with contact page', sum(1 for r in ok if r['contact']))
for r in rows:
    print(('OK ' if r['email'] else ('-- ' if r['status'] == '200' else 'XX ')) + r['name'].ljust(28), r['status'].ljust(6), (r['email'] or ('contact form' if r['contact'] else '(none)')).ljust(38), (r['tagline'] or '')[:60])

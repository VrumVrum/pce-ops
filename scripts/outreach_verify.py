# -*- coding: utf-8 -*-
"""Verify discovered agencies at scale: does the site answer, a public email (own domain,
generic address preferred), the contact page, one line of theirs, where they really are
(offshore shops listed under US/AU addresses are common), and a fit score for the send queue.

  python outreach_verify.py [--limit N] [--market us|au] [--refresh] [--threads 16]

Reads  data/outreach-discovered.csv (merged by outreach_discover.py merge, run first here)
Writes data/outreach-agencies-discovered.csv  (same columns as the hand-made lists, so
       outreach_sync.py and outreach_send.py pick it up, plus score / sources / signals)
Resumable: domains already in the output are skipped unless --refresh.
"""
import csv, io, os, re, sys, html, json, time, glob, argparse, datetime, subprocess, urllib.request, urllib.error, concurrent.futures as cf
sys.stdout.reconfigure(encoding='utf-8')
D = 'C:/Users/Flo/Downloads/pce-ops/data/'
SRC = D + 'outreach-discovered.csv'
DST = D + 'outreach-agencies-discovered.csv'
FIELDS = ['name', 'website', 'contact', 'email', 'email_alts', 'email_source', 'tagline', 'city', 'market', 'platforms', 'niche', 'status', 'title', 'sent', 'reply', 'ref',
          'score', 'sources', 'country', 'signals', 'verified_at']
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36 pce-outreach-check (+https://projectcostestimator.com/for-agencies)',
      'Accept': 'text/html,*/*;q=0.8', 'Accept-Language': 'en'}
CONTACT_RE = re.compile(r'href="([^"]*(?:contact|get-in-touch|getintouch|start-a-project|lets-talk|let-s-talk|enquir|work-with-us|hire-us)[^"#]*)"', re.I)
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
SKIP = ('sentry', 'wixpress', 'example', 'yourdomain', 'email@', 'name@', 'user@', 'domain.com', '.png', '.jpg', '.svg', '.gif', '.webp', 'noreply', 'no-reply', 'privacy@', 'gdpr@', 'dpo@', 'jobs@', 'career', 'press@', 'billing@', 'abuse@', 'support@', 'help@', 'accounts@', 'invoice', 'unsubscribe', 'postmaster', 'webmaster', 'hostmaster', 'security@', 'legal@', 'hr@', 'recruit')
GENERIC = ('hello', 'info', 'contact', 'office', 'hi', 'team', 'sales', 'mail', 'studio', 'enquiries', 'enquiry', 'inquiries', 'admin', 'welcome', 'newbusiness', 'new-business', 'projects', 'hey', 'howdy', 'gday', 'letstalk', 'talk', 'start', 'connect', 'business', 'growth', 'marketing', 'web', 'design', 'digital', 'agency')
PLATFORMS = ('shopify', 'wordpress', 'webflow', 'bigcommerce', 'magento', 'wix', 'squarespace', 'woocommerce', 'ecommerce')
NICHES = ('dental', 'law', 'medical', 'restaurant', 'real-estate', 'trades', 'accounting', 'fitness', 'hospitality', 'nonprofit', 'construction', 'healthcare', 'veterinary', 'beauty', 'finance', 'saas', 'smb')
OFFSHORE = re.compile(r'\+91[\s\d-]{8,}|\+92[\s\d-]{8,}|\+380[\s\d-]{7,}|\+94[\s\d-]{8,}|\+880[\s\d-]{7,}|\+63[\s\d-]{8,}|\bPvt\.?\s*Ltd|Private Limited|\bAhmedabad\b|\bBangalore\b|\bBengaluru\b|\bHyderabad\b|\bJaipur\b|\bIndore\b|\bMohali\b|\bNoida\b|\bGurgaon\b|\bKolkata\b|\bChennai\b|\bPune\b|\bLahore\b|\bKarachi\b|\bIslamabad\b|\bDhaka\b|\bKyiv\b|\bKharkiv\b|\bLviv\b|\bColombo\b|\bCebu\b|\bManila\b|\bMakati\b|offshore development|outsourc', re.I)
ENTERPRISE = re.compile(r'Fortune\s*500|enterprise[- ]grade|global enterprises|\b(?:500|1000)\+\s*(?:employees|engineers|developers)\b', re.I)
AU_SIGNAL = re.compile(r'\+61[\s\d-]{8,}|\b(?:NSW|VIC|QLD|WA|SA|TAS|ACT)\s+\d{4}\b|\bABN\s*:?\s*\d{2}\s?\d{3}|\.com\.au\b|\bAustralia\b', re.I)
US_SIGNAL = re.compile(r'\+1[\s.(-]{1,3}\d{3}[\s.)-]{1,3}\d{3}[\s.-]?\d{4}|\(\d{3}\)\s?\d{3}-\d{4}\b|\b(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\s+\d{5}\b|\bUnited States\b|\bUSA\b')

def get(url, limit=500000):
    r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=18)
    return r.geturl(), r.read(limit).decode('utf-8', 'replace')
def host_of(u):
    m = re.match(r'https?://([^/]+)', u); return (m.group(1) if m else '').lower().replace('www.', '')
def clean(s): return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).strip()
def emails_in(h, site_host):
    found = [html.unescape(m.group(1)).strip().lower() for m in re.finditer(r'href="mailto:([^"?]+)', h, re.I)]
    found += [m.group(0).lower() for m in EMAIL_RE.finditer(html.unescape(re.sub(r'<[^>]+>', ' ', h)))]
    out = []
    for e in found:
        if '@' not in e or any(s in e for s in SKIP) or e in out or len(e) > 60: continue
        out.append(e)
    root = site_host.split('.', 1)[-1] if site_host.count('.') >= 2 and site_host.split('.')[-2] in ('com', 'co', 'net', 'org') else site_host
    own = [e for e in out if e.split('@')[1].replace('www.', '') in (site_host, root)] if site_host else []
    own_generic = [e for e in own if e.split('@')[0] in GENERIC]
    return own_generic or own or []          # a random third-party address is worse than none
def tagline_in(h):
    for pat in [r'<meta[^>]+property="og:description"[^>]+content="([^"]{20,300})"', r'<meta[^>]+name="description"[^>]+content="([^"]{20,300})"', r'<meta[^>]+content="([^"]{20,300})"[^>]+name="description"']:
        m = re.search(pat, h, re.I)
        if m: return clean(m.group(1))
    m = re.search(r'<h1[^>]*>(.*?)</h1>', h, re.S | re.I)
    return clean(m.group(1))[:200] if m else ''
def site_name(h, fallback, domain):
    m = re.search(r'<meta[^>]+property="og:site_name"[^>]+content="([^"]{2,60})"', h, re.I)
    if m: return clean(m.group(1))
    t = re.search(r'<title[^>]*>(.*?)</title>', h, re.S | re.I)
    if t:
        parts = [p.strip() for p in re.split(r'\s[|\-–—:·]\s', clean(t.group(1))) if p.strip()]
        cand = [p for p in parts if len(p) <= 40 and not re.search(r'\b(web|website|design|agency|company|best|top|services?|home|welcome)\b', p, re.I)]
        if cand: return cand[-1]
    if fallback and not re.search(r'\b(web|website|design|services?|agency)\b', fallback, re.I): return fallback
    return domain.split('.')[0].replace('-', ' ').title()
def slug(n): return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', n.lower())).strip('-')[:40]

def verify(row):
    out = {k: '' for k in FIELDS}
    dom = row['domain']; market = row['market']
    out.update(name=row['name'], website=row['website'], city=row['city'], market=market, country=row.get('country', ''), sources=row['sources'],
               platforms=','.join(t for t in row['tags'].split('|') if t in PLATFORMS), niche=','.join(t for t in row['tags'].split('|') if t in NICHES),
               tagline=row.get('blurb', ''), verified_at=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M'))
    home = 'https://' + dom + '/'
    try:
        final, h = get(home)
    except urllib.error.HTTPError as e:
        out['status'] = str(e.code); return out
    except Exception:
        try: final, h = get('http://' + dom + '/')
        except urllib.error.HTTPError as e:
            out['status'] = str(e.code); return out
        except Exception as e:
            out['status'] = 'ERR ' + str(e)[:40]; return out
    out['status'] = '200'; out['website'] = final if host_of(final) == dom else home
    t = re.search(r'<title[^>]*>(.*?)</title>', h, re.S | re.I)
    out['title'] = clean(t.group(1))[:80] if t else ''
    out['name'] = site_name(h, row['name'], dom)[:60]
    out['tagline'] = (tagline_in(h) or row.get('blurb', ''))[:220]
    contact = ''
    for m in CONTACT_RE.finditer(h):
        href = html.unescape(m.group(1))
        if href.startswith(('mailto:', '#', 'tel:', 'javascript')) or 'wp-json' in href or 'contactform' in href.lower(): continue
        if href.startswith('//'): href = 'https:' + href
        elif href.startswith('/'): href = re.match(r'https?://[^/]+', final).group(0) + href
        elif not href.startswith('http'): href = final.rstrip('/') + '/' + href
        if host_of(href) != dom: continue
        contact = href; break
    out['contact'] = contact
    es = emails_in(h, dom); src = final; text = h
    if not es and contact:
        try:
            _, h2 = get(contact); es = emails_in(h2, dom); src = contact; text = h + h2
        except Exception: pass
    if es: out['email'], out['email_alts'], out['email_source'] = es[0], ' '.join(es[1:4]), src
    # signals from the pages themselves
    sig = []
    if OFFSHORE.search(text): sig.append('offshore')
    if ENTERPRISE.search(text): sig.append('enterprise')
    if market == 'australia' and (dom.endswith('.au') or AU_SIGNAL.search(text)): sig.append('au-confirmed')
    if market == 'us' and US_SIGNAL.search(text): sig.append('us-confirmed')
    if market == 'us' and dom.endswith(('.au', '.uk', '.in', '.pk', '.ua', '.ca', '.nz', '.ie', '.de', '.nl', '.pl', '.ro')): sig.append('other-tld')
    if market == 'australia' and dom.endswith(('.in', '.pk', '.ua', '.uk', '.ca', '.nz', '.ie', '.de', '.nl', '.pl', '.ro')): sig.append('other-tld')
    if re.search(r'href="[^"]*/pricing[^"]*"', h, re.I): sig.append('has-pricing')
    if re.search(r'wp-content|wp-includes', h): sig.append('site:wordpress')
    elif 'cdn.shopify' in h: sig.append('site:shopify')
    elif 'webflow' in h: sig.append('site:webflow')
    elif 'squarespace' in h: sig.append('site:squarespace')
    elif 'wixstatic' in h or 'parastorage' in h: sig.append('site:wix')
    if re.search(r'\b(small business|small businesses|local business|startups?)\b', text, re.I): sig.append('smb')
    if re.search(r'\bSEO\b', out['title'] + ' ' + out['tagline']) and not re.search(r'\b(web|website|design|develop)', out['title'] + ' ' + out['tagline'], re.I): sig.append('seo-only')
    out['signals'] = ','.join(sig)
    # score
    s = 50
    if out['email']:
        s += 15 if out['email'].split('@')[0] in GENERIC else 8
    elif contact: s += 2
    else: s -= 10
    if 'offshore' in sig: s -= 30
    if 'other-tld' in sig: s -= 15
    if 'enterprise' in sig: s -= 10
    if 'au-confirmed' in sig or 'us-confirmed' in sig: s += 10
    if out['niche']: s += 10
    if out['platforms']: s += 5
    if 'smb' in sig: s += 5
    if 'has-pricing' in sig: s += 3
    if 'seo-only' in sig: s -= 8
    if row['sources'].count('|') >= 1: s += 4
    if row['sources'] == 'search': s += 3       # a niche landing page = they sell exactly what we track
    out['score'] = str(max(0, min(100, s)))
    return out

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--limit', type=int, default=0); ap.add_argument('--market', default='all'); ap.add_argument('--refresh', action='store_true'); ap.add_argument('--threads', type=int, default=16)
    a = ap.parse_args()
    subprocess.run([sys.executable, os.path.dirname(os.path.abspath(__file__)) + '/outreach_discover.py', 'merge'], check=False)
    rows = list(csv.DictReader(open(SRC, encoding='utf-8', newline='')))
    if a.market != 'all': rows = [r for r in rows if r['market'] == {'us': 'us', 'au': 'australia'}.get(a.market, a.market)]
    done = {}
    if os.path.exists(DST) and not a.refresh:
        for r in csv.DictReader(open(DST, encoding='utf-8', newline='')): done[host_of(r['website']) or r['website']] = r
    # refs must stay unique across every list (the board and the tracked link key on them)
    used = set()
    for f in glob.glob(D + 'outreach-agencies-*.csv'):
        if os.path.abspath(f) == os.path.abspath(DST): continue
        for r in csv.DictReader(open(f, encoding='utf-8', newline='')): used.add(r.get('ref', ''))
    for r in done.values(): used.add(r['ref'])
    todo = [r for r in rows if r['domain'] not in done]
    if a.limit: todo = todo[:a.limit]
    print(f'discovered {len(rows)}, verified before {len(done)}, to verify {len(todo)}')
    t0 = time.time(); n = 0
    def flush():
        # the sender marks `sent` / `reply` in this file while we run: keep what it wrote
        if os.path.exists(DST):
            try:
                for r in csv.DictReader(open(DST, encoding='utf-8', newline='')):
                    k = host_of(r['website']) or r['website']
                    if k in done:
                        for col in ('sent', 'reply'):
                            if r.get(col) and not done[k].get(col): done[k][col] = r[col]
            except Exception: pass
        with io.open(DST + '.tmp', 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore'); w.writeheader()
            for r in sorted(done.values(), key=lambda r: -int(r.get('score') or 0)): w.writerow(r)
        for attempt in range(6):          # Windows refuses the replace while the sender/sync has the file open
            try: os.replace(DST + '.tmp', DST); break
            except PermissionError:
                if attempt == 5: raise
                time.sleep(2)
    with cf.ThreadPoolExecutor(a.threads) as ex:
        for out in ex.map(verify, todo):
            base = 'out-' + slug(out['name'] or host_of(out['website'])); ref = base; k = 2
            while ref in used: ref = (base[:36] + '-' + str(k)); k += 1
            used.add(ref); out['ref'] = ref
            done[host_of(out['website']) or out['website']] = out; n += 1
            if n % 100 == 0:
                flush(); print(f'  {n}/{len(todo)} verified, {int(time.time() - t0)}s, with email so far: {sum(1 for r in done.values() if r["email"])}')
    flush()
    ok = [r for r in done.values() if r['status'] == '200']
    print(f'verified {len(done)}: reachable {len(ok)}, with email {sum(1 for r in ok if r["email"])}, score>=70 with email {sum(1 for r in ok if r["email"] and int(r["score"]) >= 70)}, offshore-flagged {sum(1 for r in ok if "offshore" in r["signals"])}')

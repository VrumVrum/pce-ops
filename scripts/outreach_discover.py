# -*- coding: utf-8 -*-
"""Discover web agencies at scale (US + Australia) from public directories and search engines.

One row per domain in data/outreach-discovered.csv; re-runs merge (tags and sources accumulate).
Resumable: data/discover/state.json remembers the last page per list, data/discover/profiles.tsv
remembers every profile already fetched (source, slug, website).

  python outreach_discover.py <source> [--market us|au|all] [--max-pages N] [--limit N]
  sources: selectedfirms  techbehemoths  shopify  sortlist  wix  semrush  search

Politeness: one browser-like UA that names us, a minimum gap per host, gzip, 3 retries with
backoff, and a stop on repeated 403/429. Directories that block plain HTTP (Clutch, DesignRush,
The Manifest, Yelp) are not touched.
"""
import csv, io, os, re, sys, json, time, gzip, glob, html, threading, argparse, datetime, urllib.request, urllib.error, urllib.parse
import concurrent.futures as cf
sys.stdout.reconfigure(encoding='utf-8')
D = 'C:/Users/Flo/Downloads/pce-ops/data/'
SD = D + 'discover/'; os.makedirs(SD, exist_ok=True)
MASTER = D + 'outreach-discovered.csv'          # the merged list (python outreach_discover.py merge)
SRC = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else 'merge'
STORE_P = SD + f'{SRC}.csv'                     # each source keeps its own file, so sources run in parallel
FIELDS = ['domain', 'name', 'website', 'city', 'country', 'market', 'sources', 'tags', 'blurb', 'size', 'rate', 'found_at']
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36 pce-outreach-discovery (+https://projectcostestimator.com/for-agencies)',
      'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8', 'Accept-Language': 'en-US,en;q=0.9', 'Accept-Encoding': 'gzip'}
MARKET = {'us': 'us', 'au': 'australia'}
COUNTRY_NAME = {'us': 'United States', 'au': 'Australia'}
JUNK = ('reddit.', 'yelp.', 'clutch.co', 'designrush', 'upwork', 'fiverr', 'linkedin', 'facebook', 'instagram', 'youtube', 'wikipedia', 'quora', 'medium.com', 'forbes', 'g2.com', 'capterra', 'goodfirms',
        'sortlist', 'semrush', 'hubspot', 'wix.com', 'wixsite', 'squarespace', 'godaddy', 'wordpress.com', 'wordpress.org', 'webflow.com', 'webflow.io', 'shopify.com', 'myshopify', 'bigcommerce', 'expertise.com', 'themanifest', 'upcity',
        'indeed', 'glassdoor', 'ziprecruiter', 'thumbtack', 'bark.com', 'houzz', 'angi.com', 'homeadvisor', 'amazon.', 'apple.com', 'google.', 'microsoft', 'pinterest', 'tiktok', 'x.com', 'twitter', 'trustpilot', 'bbb.org',
        'yellowpages', 'truelocal', 'hotfrog', 'localsearch', 'oneflare', 'hipages', 'airtasker', 'freelancer', 'peopleperhour', 'toptal', 'dribbble', 'behance', 'awwwards', 'mailchimp', 'canva', 'zoho', 'salesforce', 'adobe.',
        'envato', 'themeforest', 'etsy', 'ebay', 'nytimes', 'cnn.', 'bbc.', 'techbehemoths', 'selectedfirms', 'topdevelopers', 'agencyspotter', 'duckduckgo', 'bing.com', 'yahoo', 'msn.com', 'wikihow', 'youtu.be', 'vimeo',
        'craigslist', 'gumtree', 'seek.com', 'linktr.ee', 'eventbrite', 'meetup', 'crunchbase', 'zoominfo', 'apollo.io', 'wordpress.', 'elementor.com', 'wpengine', 'kinsta', 'hostinger', 'bluehost', 'siteground', 'cloudways',
        'weebly', 'jimdo', 'strikingly', 'carrd', 'duda.co', 'webnode', 'site123', 'ionos', 'namecheap', 'hostgator', 'dreamhost', 'network solutions', 'web.com', 'vistaprint', 'fbcdn', 'ada.gov', 'nih.gov')
now = lambda: datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')

# ---------- polite HTTP ----------
_last = {}; _lock = threading.Lock(); _blocked = {}
def get(url, gap=1.2, tries=3, timeout=45, data=None, extra=None):
    host = urllib.parse.urlparse(url).netloc
    if _blocked.get(host, 0) >= 5: raise RuntimeError('host blocked after repeated 403/429: ' + host)
    for attempt in range(tries):
        with _lock:
            wait = _last.get(host, 0) + gap - time.time()
            if wait > 0: time.sleep(wait)
            _last[host] = time.time()
        try:
            h = dict(UA); h.update(extra or {})
            r = urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=timeout)
            b = r.read()
            if r.headers.get('Content-Encoding') == 'gzip' or b[:2] == b'\x1f\x8b':
                try: b = gzip.decompress(b)
                except Exception: pass
            _blocked[host] = 0
            return r.geturl(), b.decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                _blocked[host] = _blocked.get(host, 0) + 1; time.sleep(20 * (attempt + 1))
            elif e.code in (404, 410):
                raise
            else: time.sleep(3 * (attempt + 1))
            if attempt == tries - 1: raise
        except Exception:
            if attempt == tries - 1: raise
            time.sleep(3 * (attempt + 1))

def domain_of(u):
    m = re.match(r'https?://([^/?#:]+)', (u or '').strip().lower())
    d = (m.group(1) if m else (u or '').strip().lower()).replace('www.', '', 1)
    return d if re.match(r'^[a-z0-9.-]+\.[a-z]{2,}$', d) else ''
def junk(d):
    return (not d) or any(j in d for j in JUNK) or d.endswith(('.gov', '.edu', '.gov.au', '.edu.au', '.mil')) or d.count('.') > 3
def clean(s): return re.sub(r'\s+', ' ', html.unescape(s or '')).strip()

# ---------- store ----------
class Store:
    def __init__(self, path=None):
        self.path = path or STORE_P
        self.rows = {}; self.lock = threading.Lock(); self.added = 0; self.dirty = 0
        if os.path.exists(self.path):
            for r in csv.DictReader(open(self.path, encoding='utf-8', newline='')): self.rows[r['domain']] = r
        self.n0 = len(self.rows)
    def add(self, name, website, market, source, tags='', city='', country='', blurb='', size='', rate=''):
        d = domain_of(website)
        if junk(d) or not name: return False
        with self.lock:
            r = self.rows.get(d)
            if r:
                st = set(filter(None, r['sources'].split('|'))); tg = set(filter(None, r['tags'].split('|')))
                new = source not in st; st.add(source); tg.update(filter(None, tags.split('|')))
                r['sources'] = '|'.join(sorted(st)); r['tags'] = '|'.join(sorted(tg))
                for k, v in (('city', city), ('blurb', blurb), ('size', size), ('rate', rate), ('country', country)):
                    if v and not r.get(k): r[k] = v
                self.dirty += 1; return new
            self.rows[d] = {'domain': d, 'name': clean(name)[:80], 'website': website.strip()[:200], 'city': clean(city)[:60], 'country': country or COUNTRY_NAME.get(market, ''),
                            'market': MARKET.get(market, market), 'sources': source, 'tags': tags, 'blurb': clean(blurb)[:220], 'size': size, 'rate': rate, 'found_at': now()}
            self.added += 1; self.dirty += 1
            if self.dirty >= 40: self._save()
            return True
    def _save(self):
        tmp = self.path + '.tmp'
        with io.open(tmp, 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore'); w.writeheader()
            for r in self.rows.values(): w.writerow({k: r.get(k, '') for k in FIELDS})
        for attempt in range(6):          # Windows refuses the replace while merge/verify has the file open
            try: os.replace(tmp, self.path); break
            except PermissionError:
                if attempt == 5: raise
                time.sleep(2)
        self.dirty = 0
    def save(self):
        with self.lock: self._save()
        print(f'store {os.path.basename(self.path)}: {len(self.rows)} domains (+{self.added} new this run, {self.n0} before)')

def merge():
    """Union of every discover/<source>.csv into outreach-discovered.csv (tags and sources accumulate)."""
    m = Store(MASTER)
    for f in sorted(glob.glob(SD + '*.csv')):
        for r in csv.DictReader(open(f, encoding='utf-8', newline='')):
            for s in r['sources'].split('|'):
                m.add(r['name'], r['website'], r['market'], s, r['tags'], city=r['city'], country=r['country'], blurb=r['blurb'], size=r['size'], rate=r['rate'])
    m.save()
    by = {}
    for r in m.rows.values():
        for s in r['sources'].split('|'): by[s] = by.get(s, 0) + 1
    print('by source:', by, '| by market:', {k: sum(1 for r in m.rows.values() if r['market'] == k) for k in ('us', 'australia')})

STATE_P = SD + f'state-{SRC}.json'
state = json.load(open(STATE_P, encoding='utf-8')) if os.path.exists(STATE_P) else {}
def state_save(): json.dump(state, open(STATE_P, 'w', encoding='utf-8'), indent=1)
PROF_P = SD + f'profiles-{SRC}.tsv'
profiles = {}
if os.path.exists(PROF_P):
    for line in open(PROF_P, encoding='utf-8'):
        p = line.rstrip('\n').split('\t')
        if len(p) >= 3: profiles[p[0] + '|' + p[1]] = p[2]
_pf = threading.Lock()
def profile_done(source, slug, website):
    with _pf:
        profiles[source + '|' + slug] = website or '-'
        with open(PROF_P, 'a', encoding='utf-8') as f: f.write(f'{source}\t{slug}\t{website or "-"}\n')

def walk_pages(key, url_of, parse, max_pages, first=1):
    """Iterate list pages from the saved state; parse(html) -> (n_items, last_page_hint)."""
    p = state.get(key, {}).get('page', first - 1) + 1
    empty = 0
    while p <= max_pages:
        try: _, h = get(url_of(p))
        except urllib.error.HTTPError as e:
            print(f'  {key} p{p}: HTTP {e.code}'); break
        except Exception as e:
            print(f'  {key} p{p}: {str(e)[:80]}'); break
        n, last = parse(h, p)
        state[key] = {'page': p, 'last': last, 'at': now()}; state_save()
        print(f'  {key} p{p}/{last or "?"}: {n} items')
        if n == 0: empty += 1
        else: empty = 0
        if empty >= 2 or (last and p >= last): break
        p += 1

# ---------- sources ----------
def src_selectedfirms(store, market, max_pages, limit):
    cats = ['web-design', 'web-development', 'ecommerce-development', 'shopify-development', 'wordpress-development', 'magento-development', 'woocommerce-development', 'bigcommerce-development', 'webflow-development', 'squarespace-development', 'wix-development', 'ui-ux-design']
    country = {'us': 'usa', 'au': 'australia'}[market]
    for cat in cats:
        tag = cat.replace('-development', '').replace('-design', '') if cat != 'web-design' else 'web-design'
        def parse(h, p, cat=cat, tag=tag):
            n = 0
            for m in re.finditer(r'data-url="(https?://[^"]+)"[^>]*class="head6 website-click"[^>]*>\s*<h3[^>]*title="Visit (.+?) Website"', h):
                if store.add(html.unescape(m.group(2)), html.unescape(m.group(1)), market, 'selectedfirms', tag): n += 1
            pages = [int(x) for x in re.findall(r'\?page=(\d+)', h)]
            return n, (max(pages) if pages else None)
        walk_pages(f'selectedfirms|{cat}|{country}', lambda p: f'https://selectedfirms.co/companies/{cat}/{country}?page={p}', parse, max_pages)
        if limit and store.added >= limit: return

def nuxt_resolver(h):
    m = re.search(r'\(function\(([a-zA-Z0-9_$,]+)\)\{return ', h)
    if not m: return lambda t: None
    params = m.group(1).split(',')
    j = h.find('}}(', m.end())
    if j < 0: return lambda t: None
    s = h[j + 3:]; i = 0; args = []; depth = 0
    while i < len(s):
        c = s[i]
        if c in ' \n\r\t,': i += 1; continue
        if c == ')' and depth == 0: break
        if c == '"':
            k = i + 1
            while k < len(s):
                if s[k] == '\\': k += 2; continue
                if s[k] == '"': break
                k += 1
            try: args.append(json.loads(s[i:k + 1]))
            except Exception: args.append(s[i + 1:k])
            i = k + 1; continue
        k = i
        while k < len(s) and s[k] not in ',)': k += 1
        t = s[i:k].strip()
        args.append({'null': None, 'true': True, 'false': False, 'void 0': None}.get(t, t))
        if re.match(r'^-?\d+(\.\d+)?$', t): args[-1] = float(t) if '.' in t else int(t)
        i = k
    amap = dict(zip(params, args))
    def resolve(tok):
        if tok is None: return None
        tok = tok.strip()
        if tok.startswith('"'):
            try: return json.loads(tok)
            except Exception: return tok.strip('"')
        if tok in amap: return amap[tok]
        if re.match(r'^-?\d+(\.\d+)?$', tok): return float(tok) if '.' in tok else int(tok)
        return None
    return resolve

def src_techbehemoths(store, market, max_pages, limit):
    services = ['web-design', 'web-development', 'ecommerce', 'e-commerce-development', 'shopify', 'wordpress', 'webflow', 'wix', 'wix-studio', 'squarespace', 'woocommerce', 'magento', 'bigcommerce', 'ux-ui-design']
    country = {'us': 'united-states', 'au': 'australia'}[market]
    STR = r'("(?:[^"\\]|\\.)*"|[a-zA-Z_$][\w$]*|-?\d+(?:\.\d+)?)'
    rx = re.compile(r'\{id:(\d+),name:' + STR + r',slug:' + STR + r',logo:[^,]*,description:' + STR + r',company_size:' + STR + r',hourly_rate:' + STR + r',is_featured:[^,]+,website:' + STR + r',')
    for svc in services:
        tag = {'e-commerce-development': 'ecommerce', 'ux-ui-design': 'ux', 'wix-studio': 'wix'}.get(svc, svc)
        def parse(h, p, tag=tag):
            R = nuxt_resolver(h); n = 0; seen = set()
            for m in rx.finditer(h):
                cid = m.group(1)
                if cid in seen: continue
                seen.add(cid)
                name, slug, desc, size, rate, web = (R(m.group(k)) for k in range(2, 8))
                if not web or not isinstance(web, str) or not web.startswith('http'): continue
                tail = h[m.end():m.end() + 2500]
                hq = re.search(r'headquarter:\{country:\{name:([^,]+),slug:[^}]+\},city:\{name:([^,]+),', tail)
                cn = R(hq.group(1)) if hq else None; city = R(hq.group(2)) if hq else ''
                if cn and cn != COUNTRY_NAME[market]: continue
                if store.add(name or slug, web, market, 'techbehemoths', tag, city=city or '', blurb=desc if isinstance(desc, str) else '', size=str(size or ''), rate=str(rate or '')): n += 1
            pages = [int(x) for x in re.findall(r'\?page=(\d+)', h)]
            return n, (max(pages) if pages else None)
        walk_pages(f'techbehemoths|{svc}|{country}', lambda p: f'https://techbehemoths.com/companies/{svc}/{country}?page={p}', parse, max_pages)
        if limit and store.added >= limit: return

def fetch_profiles(source, items, fetch_one, store, market, tag, limit, workers=3):
    """items: list of (slug, name, city, blurb). fetch_one(slug) -> (website, name, city, country) ; cached in profiles.tsv"""
    todo = [it for it in items if source + '|' + it[0] not in profiles]
    print(f'  {source}: {len(items)} listed, {len(todo)} profiles to fetch')
    def work(it):
        slug, name, city, blurb = it
        try: web, name2, city2, country = fetch_one(slug)
        except urllib.error.HTTPError as e:
            profile_done(source, slug, ''); return 0
        except Exception as e:
            print(f'    {slug}: {str(e)[:60]}'); return 0
        profile_done(source, slug, web)
        if not web: return 0
        return 1 if store.add(name2 or name, web, market, source, tag, city=city2 or city, country=country, blurb=blurb) else 0
    n = 0
    with cf.ThreadPoolExecutor(workers) as ex:
        for k in ex.map(work, todo):
            n += k
            if limit and store.added >= limit: break
    for it in items:
        if source + '|' + it[0] in profiles and profiles[source + '|' + it[0]] not in ('', '-'):
            store.add(it[1], profiles[source + '|' + it[0]], market, source, tag, city=it[2], blurb=it[3])
    return n

def src_shopify(store, market, max_pages, limit):
    country = {'us': 'united-states', 'au': 'australia'}[market]
    def fetch_one(slug):
        _, h = get(f'https://www.shopify.com/partners/directory/partner/{slug}', gap=1.0)
        m = re.search(r'Contact information.*?<a class="[^"]*" href="(https?://[^"]+)" rel="nofollow"', h, re.S)
        web = html.unescape(m.group(1)) if m else ''
        if 'shopify.com' in web: web = ''
        return web, '', '', COUNTRY_NAME[market]
    def parse(h, p):
        items = []
        for card in h.split('data-component-name="listing-profile-card"')[1:]:
            s = re.search(r'href="/partners/directory/partner/([a-z0-9-]+)"', card); a = re.search(r'alt="([^"]+)"', card)
            if not s or not a: continue
            txt = re.sub(r'<[^>]+>', '|', card)
            loc = re.search(r'\|\s*([A-Za-z .\'-]{2,40}, (?:United States|Australia))\s*\|', txt)
            items.append((s.group(1), html.unescape(a.group(1)), loc.group(1).split(',')[0].strip() if loc else '', ''))
        n = fetch_profiles('shopify', items, fetch_one, store, market, 'shopify', limit)
        pages = [int(x) for x in re.findall(r'\?page=(\d+)', h)]
        return len(items), (max(pages) if pages else None)
    walk_pages(f'shopify|{country}', lambda p: f'https://www.shopify.com/partners/directory/locations/{country}?page={p}', parse, max_pages)

def src_sortlist(store, market, max_pages, limit):
    cats = ['web-design', 'web-development', 'ecommerce']
    locs = {'us': ['united-states-us'], 'au': ['australia-au', 'sydney-au', 'melbourne-au', 'brisbane-au', 'perth-au']}[market]
    def fetch_one(slug):
        _, h = get(f'https://www.sortlist.com/agency/{slug}', gap=1.0)
        if COUNTRY_NAME[market] not in h: return '', '', '', ''      # listed as "serving" the place, based elsewhere
        m = re.search(r'href="(https?://[^"?]+)\?utm_source=sortlist&amp;utm_medium=profile', h)
        t = re.search(r'<meta property="og:title" content="([^"]+)"', h)
        name = re.sub(r'\s*\(\+?\s*\d*\s*reviews?\)', '', re.sub(r'\s*[|\-–].*$', '', html.unescape(t.group(1)))) if t else ''
        loc = re.search(r'([A-Z][A-Za-z .\'-]{2,30}), ' + COUNTRY_NAME[market], h)
        return (html.unescape(m.group(1)) if m else ''), name, (loc.group(1) if loc else ''), COUNTRY_NAME[market]
    for cat in cats:
        tag = {'ecommerce': 'ecommerce', 'web-development': 'web-development'}.get(cat, 'web-design')
        for loc in locs:
            city = loc.split('-')[0].title() if loc not in ('united-states-us', 'australia-au') else ''
            def parse(h, p, city=city, tag=tag):
                slugs = []
                for s in re.findall(r'sortlist\.com/agency/([a-z0-9-]+)#org', h):
                    if s not in slugs: slugs.append(s)
                items = [(s, s.replace('-', ' ').title(), city, '') for s in slugs]
                fetch_profiles('sortlist', items, fetch_one, store, market, tag, limit)
                pages = [int(x) for x in re.findall(r'page=(\d+)', h)]
                return len(items), (max(pages) if pages else None)
            walk_pages(f'sortlist|{cat}|{loc}', lambda p: f'https://www.sortlist.com/{cat}/{loc}?page={p}', parse, max_pages)
            if limit and store.added >= limit: return

def src_wix(store, market, max_pages, limit):
    cats = ['web-design', 'online-store', 'web-developer']
    loc = {'us': 'United States', 'au': 'Australia'}[market]; cc = {'us': 'US', 'au': 'AU'}[market]
    def fetch_one(slug):
        _, h = get(f'https://www.wix.com/studio/community/partners/{slug}', gap=5.0)     # wix answers 429 to anything faster
        for blob in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', h, re.S):
            if 'LocalBusiness' not in blob: continue
            try: d = json.loads(blob)
            except Exception: continue
            for o in (d if isinstance(d, list) else [d]):
                if o.get('@type') != 'LocalBusiness': continue
                a = o.get('@address') or o.get('address') or {}
                if a.get('addressCountry') != cc: return '', '', '', ''
                return o.get('url', ''), o.get('name', ''), a.get('addressLocality', ''), COUNTRY_NAME[market]
        return '', '', '', ''
    for cat in cats:
        tag = {'online-store': 'ecommerce', 'web-developer': 'web-development'}.get(cat, 'web-design') + '|wix'
        def parse(h, p, tag=tag):
            slugs = []
            for s in re.findall(r'href="/studio/community/partners/([a-z0-9-]+)"', h):
                if s not in slugs: slugs.append(s)
            items = [(s, s.replace('-', ' ').title(), '', '') for s in slugs]
            fetch_profiles('wix', items, fetch_one, store, market, tag, limit, workers=1)
            pages = [int(x) for x in re.findall(r'page=(\d+)', h)]
            return len(items), (max(pages) if pages else None)
        walk_pages(f'wix|{cat}|{loc}', lambda p: f'https://www.wix.com/marketplace/hire/{cat}?location={urllib.parse.quote(loc)}&page={p}', parse, min(max_pages, 36))
        if limit and store.added >= limit: return

def src_semrush(store, market, max_pages, limit):
    services = ['web-design', 'web-development', 'ux']
    locs = {'us': ['united-states', 'arizona', 'atlanta', 'austin', 'boston', 'california', 'charlotte', 'chicago', 'cleveland', 'colorado', 'connecticut', 'dallas', 'denver', 'florida', 'georgia-state', 'houston', 'illinois', 'indiana', 'indianapolis', 'las-vegas', 'los-angeles', 'massachusetts', 'miami', 'michigan', 'minneapolis', 'minnesota', 'nevada', 'new-jersey', 'new-york', 'new-york-city', 'north-carolina', 'ohio', 'oregon', 'pennsylvania', 'philadelphia', 'phoenix', 'portland', 'san-diego', 'seattle', 'south-carolina', 'tampa', 'tennessee', 'texas', 'utah', 'virginia', 'washington'],
            'au': ['australia', 'sydney', 'melbourne']}[market]
    CITIES = {'atlanta', 'austin', 'boston', 'charlotte', 'chicago', 'cleveland', 'dallas', 'denver', 'houston', 'indianapolis', 'las-vegas', 'los-angeles', 'miami', 'minneapolis', 'new-york-city', 'philadelphia', 'phoenix', 'portland', 'san-diego', 'seattle', 'tampa', 'sydney', 'melbourne'}
    def fetch_one(slug):
        _, h = get(f'https://agencies.semrush.com/{slug}/', gap=1.0)
        m = re.search(r'&quot;slot&quot;:\[0,&quot;website&quot;\],&quot;agencyId&quot;:\[0,\d+\],&quot;href&quot;:\[0,&quot;(https?://[^&?]+)', h)
        return (m.group(1) if m else ''), '', '', COUNTRY_NAME[market]
    for svc in services:
        tag = {'ux': 'ux'}.get(svc, svc)
        for loc in locs:
            city = loc.replace('-', ' ').title() if loc in CITIES else ''
            def parse(h, p, city=city, tag=tag):
                items = []
                for m in re.finditer(r'href="/([a-z0-9-]+)/" target="_blank"><astro-slot>([^<]+)</astro-slot></a>(?:.{0,400}?_tagline_[^>]*>\s*([^<]*?)\s*<)?', h, re.S):
                    items.append((m.group(1), html.unescape(m.group(2)), city, html.unescape(m.group(3) or '')))
                fetch_profiles('semrush', items, fetch_one, store, market, tag, limit)
                pages = [int(x) for x in re.findall(r'page=(\d+)', h)]
                return len(items), (max(pages) if pages else None)
            walk_pages(f'semrush|{svc}|{loc}', lambda p: f'https://agencies.semrush.com/list/{svc}/{loc}/?page={p}', parse, max_pages)
            if limit and store.added >= limit: return

NICHES = [('dental', 'dental'), ('law firm', 'law'), ('medical practice', 'medical'), ('restaurant', 'restaurant'), ('real estate', 'real-estate'), ('plumber electrician', 'trades'), ('accounting firm', 'accounting'), ('gym fitness', 'fitness'),
          ('hotel', 'hospitality'), ('church nonprofit', 'nonprofit'), ('ecommerce', 'ecommerce'), ('Shopify', 'shopify'), ('WordPress', 'wordpress'), ('Webflow', 'webflow'), ('small business', 'smb'), ('construction', 'construction'),
          ('healthcare', 'healthcare'), ('veterinary', 'veterinary'), ('salon spa', 'beauty'), ('financial advisor', 'finance'), ('SaaS startup', 'saas'), ('chiropractor', 'medical'), ('landscaping', 'trades'), ('roofing', 'trades')]
CITIES = {'us': ['New York', 'Los Angeles', 'Chicago', 'Houston', 'Phoenix', 'Philadelphia', 'San Antonio', 'San Diego', 'Dallas', 'Austin', 'San Jose', 'Jacksonville', 'Columbus', 'Charlotte', 'Indianapolis', 'San Francisco', 'Seattle', 'Denver', 'Nashville', 'Boston',
                'Las Vegas', 'Portland', 'Miami', 'Atlanta', 'Minneapolis', 'Tampa', 'Orlando', 'Raleigh', 'Salt Lake City', 'Kansas City', 'Pittsburgh', 'Cincinnati', 'Sacramento', 'St. Louis', 'Cleveland', 'Milwaukee', 'Baltimore', 'Detroit', 'Oklahoma City', 'Richmond'],
          'au': ['Sydney', 'Melbourne', 'Brisbane', 'Perth', 'Adelaide', 'Gold Coast', 'Canberra', 'Newcastle', 'Hobart', 'Sunshine Coast', 'Geelong', 'Wollongong']}
def title_name(t):
    t = clean(re.sub(r'<[^>]+>', '', t)); parts = [p.strip() for p in re.split(r'\s[|\-–—:]\s', t) if p.strip()]
    if not parts: return t[:60]
    cand = [p for p in parts if len(p) <= 40 and not re.search(r'\b(web|website|design|agency|company|best|top|services?)\b', p, re.I)]
    return (cand[-1] if cand else (parts[-1] if len(parts[-1]) <= 40 else parts[0]))[:60]
def src_search(store, market, max_pages, limit):
    kl = {'us': 'us-en', 'au': 'au-en'}[market]; mkt = {'us': 'en-US', 'au': 'en-AU'}[market]
    for niche, tag in NICHES:
        for city in CITIES[market]:
            q = f'{niche} website design agency {city}'; key = f'search|{market}|{q}'
            if state.get(key, {}).get('done'): continue
            n = 0
            try:
                _, h = get('https://lite.duckduckgo.com/lite/?q=' + urllib.parse.quote(q) + '&kl=' + kl, gap=3.0)
                for m in re.finditer(r'href="//duckduckgo\.com/l/\?uddg=([^&"]+)[^"]*"[^>]*class=\'result-link\'>(.*?)</a>', h, re.S):
                    u = urllib.parse.unquote(m.group(1))
                    if 'duckduckgo.com/y.js' in u or 'bing.com/aclick' in u: continue
                    if store.add(title_name(m.group(2)), u, market, 'search', tag, city=city): n += 1
            except Exception as e: print(f'  ddg {q}: {str(e)[:60]}')
            try:
                _, h = get(f'https://www.bing.com/search?q={urllib.parse.quote(q)}&mkt={mkt}&setlang=en&first=1', gap=3.0)
                for blk in re.findall(r'<li class="b_algo".*?</li>', h, re.S):
                    c = re.search(r'<cite>([^<]+)', blk); t = re.search(r'<h2[^>]*><a[^>]*>(.*?)</a>', blk, re.S)
                    if not c: continue
                    u = clean(c.group(1)).split(' ')[0]
                    if not u.startswith('http'): u = 'https://' + u
                    if store.add(title_name(t.group(1) if t else u), u, market, 'search', tag, city=city): n += 1
            except Exception as e: print(f'  bing {q}: {str(e)[:60]}')
            state[key] = {'done': True, 'n': n, 'at': now()}; state_save()
            print(f'  {q}: +{n}')
            if limit and store.added >= limit: return

SOURCES = {'selectedfirms': src_selectedfirms, 'techbehemoths': src_techbehemoths, 'shopify': src_shopify, 'sortlist': src_sortlist, 'wix': src_wix, 'semrush': src_semrush, 'search': src_search}
if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('source', choices=sorted(SOURCES) + ['merge']); ap.add_argument('--market', default='all'); ap.add_argument('--max-pages', type=int, default=600); ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    if a.source == 'merge':
        merge(); sys.exit(0)
    store = Store(); t0 = time.time()
    try:
        for mk in (['us', 'au'] if a.market == 'all' else [a.market]):
            print(f'== {a.source} / {mk}')
            SOURCES[a.source](store, mk, a.max_pages, a.limit)
            if a.limit and store.added >= a.limit: break
    except KeyboardInterrupt: print('interrupted')
    finally:
        store.save(); state_save()
        print(f'done in {int(time.time() - t0)}s')

# -*- coding: utf-8 -*-
"""Outreach board sync: one JSON of every prospect with what we know, pushed to
Supabase Storage (bucket `ops`, object `outreach/prospects.json`) for /admin/outreach.

Sources merged, in this order:
  data/outreach-agencies-*.csv           the lists (found / verified / email / tagline / sent / ref)
  data/outreach-sent-2026-09-20.jsonl    every send (Resend id, subject, body)
  Thunderbird                            replies (local 'Project Cost Estimator' Inbox + Gmail INBOX), read-only
  Supabase Storage `search-hits`         clicks on the per-agency link (?ref=out-<slug>) in the last 60 days
  Supabase `providers`                   an application whose website domain matches a prospect -> listed
  data/outreach-status.json              manual overrides written by the admin page (status, notes)

Status ladder (highest wins): found < sent < clicked < replied < listed; `declined` and `bounced`
are terminal. Runs from Task Scheduler every 30 min (PCE-OutreachSync) and after each send.
"""
import csv, io, os, re, sys, json, glob, email, datetime, urllib.request, urllib.error, urllib.parse
from email.header import decode_header, make_header
sys.stdout.reconfigure(encoding='utf-8')
D = 'C:/Users/Flo/Downloads/pce-ops/data/'
env = open('C:/Users/Flo/Downloads/scopebit/.env.vercel', encoding='utf-8').read()
URL = re.search(r'^SUPABASE_URL="?([^"\r\n]+)"?', env, re.M).group(1).rstrip('/')
KEY = re.search(r'^SUPABASE_SERVICE_ROLE_KEY="?([^"\r\n]+)"?', env, re.M).group(1)
H = {'Authorization': 'Bearer ' + KEY, 'apikey': KEY, 'Content-Type': 'application/json', 'User-Agent': 'pce-outreach-sync/1.0'}
NOW = datetime.datetime.now(datetime.timezone.utc)

def sb(method, path, body=None, raw=False, ctype=None):
    h = dict(H)
    if ctype: h['Content-Type'] = ctype
    data = body if isinstance(body, (bytes, bytearray)) else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(URL + path, data=data, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=60) as resp:
        d = resp.read(); return d if raw else (json.loads(d) if d else None)

def domain(u):
    m = re.match(r'https?://([^/]+)', (u or '').strip().lower()); return (m.group(1) if m else (u or '').lower()).replace('www.', '')

# 1. lists
prospects = {}
for f in sorted(glob.glob(D + 'outreach-agencies-*.csv')):
    for r in csv.DictReader(open(f, encoding='utf-8')):
        ref = r.get('ref') or ('out-' + re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', r['name'].lower())).strip('-')[:40])
        p = prospects.setdefault(ref, {'ref': ref, 'name': r['name'], 'website': r['website'], 'domain': domain(r['website']),
                                       'contact': r.get('contact', ''), 'email': r.get('email', ''), 'tagline': r.get('tagline', ''),
                                       'city': r.get('city', ''), 'market': r.get('market', ''), 'platforms': r.get('platforms', ''),
                                       'niche': r.get('niche', ''), 'site_status': r.get('status', ''), 'list': os.path.basename(f),
                                       'score': int(r.get('score') or 0), 'sources': r.get('sources', ''), 'signals': r.get('signals', ''),
                                       'status': 'found', 'sent_at': None, 'resend_id': None, 'clicks': 0, 'first_click': None, 'followup_at': None,
                                       'reply_at': None, 'reply_from': None, 'reply_excerpt': None, 'listed_at': None, 'notes': ''})
        if r.get('sent'): p['status'] = 'sent'; p['sent_at'] = r['sent']

# 2. send logs (one file per day; `ref` is in every entry since 21 Sep, older ones derive it from the name)
for sent_log in sorted(glob.glob(D + 'outreach-sent-*.jsonl')):
    for line in open(sent_log, encoding='utf-8'):
        try: e = json.loads(line)
        except Exception: continue
        if e.get('mode') not in ('send', 'daily', 'followup'): continue
        ref = e.get('ref') or ('out-' + re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', e['agency'].lower())).strip('-')[:40])
        p = prospects.get(ref)
        if not p: continue
        if e.get('mode') == 'followup':
            if e.get('resend'): p['followup_at'] = e['ts'][:19].replace('T', ' ') + 'Z'
            continue
        if e.get('resend'):
            p['resend_id'] = e['resend'].get('id'); p['sent_at'] = e['ts'][:19].replace('T', ' ') + 'Z'
            if p['status'] == 'found': p['status'] = 'sent'
        elif e.get('error') and p['status'] in ('found', 'sent'):
            p['status'] = 'bounced'; p['notes'] = (p['notes'] + ' send error: ' + str(e['error'])[:120]).strip()

# 2b. delivery state from Resend (delivered / bounced / complained) for every send id
try:
    RKEY = re.search(r'^RESEND_API_KEY="?([^"' + chr(13) + chr(10) + ']+)"?', env, re.M).group(1).strip()
    for p in prospects.values():
        if not p.get('resend_id'): continue
        try:
            r = urllib.request.Request('https://api.resend.com/emails/' + p['resend_id'], headers={'Authorization': 'Bearer ' + RKEY, 'User-Agent': 'pce-outreach-sync/1.0'})
            ev = json.load(urllib.request.urlopen(r, timeout=20)).get('last_event')
        except Exception:
            continue
        p['delivery'] = ev
        if ev in ('bounced', 'complained') and p['status'] in ('found', 'sent', 'clicked'):
            p['status'] = 'bounced'
except Exception as e:
    print('resend events: skipped —', str(e)[:120])

# 3. replies (Thunderbird, read-only)
PROF = os.path.join(os.environ['APPDATA'], 'Thunderbird', 'Profiles', '3vcu35zk.default-release')
by_domain = {p['domain']: p for p in prospects.values() if p['domain']}
by_email_domain = {p['email'].split('@')[1]: p for p in prospects.values() if p.get('email') and '@' in p['email']}
def dec(v):
    try: return str(make_header(decode_header(v))) if v else ''
    except Exception: return v or ''
for P in [os.path.join(PROF, 'Mail', 'ProjectCostEstimator', 'Inbox'), os.path.join(PROF, 'ImapMail', 'imap.gmail.com', 'INBOX-1')]:
    if not os.path.exists(P): continue
    size = os.path.getsize(P)
    with open(P, 'rb') as f:
        f.seek(max(0, size - 30 * 1024 * 1024)); data = f.read()
    for raw in re.split(rb'\r?\n(?=From - )', data)[1:]:
        try: m = email.message_from_bytes(raw)
        except Exception: continue
        addr = (email.utils.parseaddr(dec(m.get('From', '')))[1] or '').lower()
        dom = addr.split('@')[-1]
        p = by_email_domain.get(dom) or by_domain.get(dom)
        if not p or addr.endswith('projectcostestimator.com'): continue
        try:
            d = email.utils.parsedate_to_datetime(m.get('Date', ''))
            if d.tzinfo is None: d = d.replace(tzinfo=datetime.timezone.utc)
        except Exception: d = NOW
        if d < datetime.datetime(2026, 9, 20, 17, 0, tzinfo=datetime.timezone.utc): continue
        body = ''
        for part in m.walk():
            if part.get_content_type() == 'text/plain':
                try: body = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', 'replace'); break
                except Exception: pass
        excerpt = re.sub(r'\s+', ' ', body).strip()[:240]
        if p['status'] not in ('listed', 'declined'):
            p['status'] = 'declined' if re.match(r'^\W*(no|not interested|unsubscribe|remove)\b', excerpt.lower()) else 'replied'
        p['reply_at'] = d.isoformat(); p['reply_from'] = addr; p['reply_excerpt'] = excerpt

# 4. clicks on the per-agency link (search-hits bucket, q contains ref=out-)
try:
    since = (NOW - datetime.timedelta(days=60)).date()
    days = [o['name'] for o in sb('POST', '/storage/v1/object/list/search-hits', {'prefix': '', 'limit': 1000}) if o.get('id') is None and re.match(r'\d{4}-\d{2}-\d{2}$', o['name']) and o['name'] >= str(since)]
    for day in days:
        for sub in (day, day + '/nav'):
            objs = sb('POST', '/storage/v1/object/list/search-hits', {'prefix': sub, 'limit': 1000})
            for o in objs:
                if o.get('id') is None or not o['name'].endswith('-for-agencies.json'): continue
                try: body = json.loads(sb('GET', '/storage/v1/object/search-hits/' + urllib.parse.quote(sub + '/' + o['name']), raw=True))
                except Exception: continue
                m = re.search(r'ref=(out-[a-z0-9-]+)', body.get('q', ''))
                if not m or body.get('bot'): continue
                p = prospects.get(m.group(1))
                if not p: continue
                # mail scanners (Safe Links, Mimecast, ...) open every link within seconds of delivery: a hit
                # inside 5 minutes of the send is counted apart and does not make the row 'clicked'
                sent_ts = (p.get('sent_at') or '').replace(' ', 'T').rstrip('Z')
                fast = bool(sent_ts) and body['ts'][:19] < (datetime.datetime.fromisoformat(sent_ts[:19]) + datetime.timedelta(minutes=5)).isoformat()
                if fast:
                    p['scanner_clicks'] = p.get('scanner_clicks', 0) + 1
                    continue
                p['clicks'] += 1
                if not p['first_click'] or body['ts'] < p['first_click']: p['first_click'] = body['ts']
                if p['status'] in ('found', 'sent'): p['status'] = 'clicked'
except Exception as e:
    print('clicks: skipped —', str(e)[:120])

# 5. applications: providers whose website domain matches a prospect
try:
    for r in sb('GET', '/rest/v1/providers?select=name,website,application_status,active,created_at&order=created_at.desc&limit=500'):
        p = by_domain.get(domain(r.get('website', '')))
        if not p: continue
        p['status'] = 'listed'; p['listed_at'] = r.get('created_at'); p['application_status'] = r.get('application_status'); p['active'] = r.get('active')
except Exception as e:
    print('providers: skipped —', str(e)[:120])

# 6. manual overrides from the admin page
overrides = {}
try:
    overrides = json.loads(sb('GET', '/storage/v1/object/ops/outreach/overrides.json', raw=True)) or {}
except Exception:
    overrides = {}
ov_path = D + 'outreach-status.json'
if os.path.exists(ov_path):
    overrides.update(json.load(open(ov_path, encoding='utf-8')))
if overrides:
    for ref, ov in overrides.items():
        if ref in prospects:
            if ov.get('status'): prospects[ref]['status'] = ov['status']
            if ov.get('notes') is not None: prospects[ref]['notes'] = ov['notes']

ORDER = {'listed': 0, 'replied': 1, 'clicked': 2, 'sent': 3, 'found': 4, 'declined': 5, 'bounced': 6}
rows = sorted(prospects.values(), key=lambda p: (ORDER.get(p['status'], 9), -(p['clicks'] or 0), -(p.get('score') or 0), p['name'].lower()))
counts = {}
for p in rows: counts[p['status']] = counts.get(p['status'], 0) + 1
# 12k+ rows: keep the board under ~6 MB (the API reads it whole on every cache miss) — short taglines, no empty keys
for p in rows:
    if p.get('tagline') and len(p['tagline']) > 160: p['tagline'] = p['tagline'][:157].rsplit(' ', 1)[0] + '…'
    for k in [k for k, v in p.items() if v is None]:      # only nulls: the page does p.market.split etc. on strings
        del p[k]
doc = {'generated': NOW.isoformat(), 'counts': counts, 'total': len(rows), 'prospects': rows}
json.dump(doc, open(D + 'outreach-prospects.json', 'w', encoding='utf-8'), ensure_ascii=False)

# 7. upload (bucket `ops`, private)
try:
    buckets = [b['name'] for b in sb('GET', '/storage/v1/bucket')]
    if 'ops' not in buckets:
        sb('POST', '/storage/v1/bucket', {'id': 'ops', 'name': 'ops', 'public': False}); print('bucket ops created')
    payload = json.dumps(doc, ensure_ascii=False).encode('utf-8')
    r = urllib.request.Request(URL + '/storage/v1/object/ops/outreach/prospects.json', data=payload, method='POST',
                               headers={'Authorization': 'Bearer ' + KEY, 'apikey': KEY, 'Content-Type': 'application/json', 'x-upsert': 'true', 'User-Agent': 'pce-outreach-sync/1.0'})
    urllib.request.urlopen(r, timeout=60).read()
    print('uploaded ops/outreach/prospects.json', len(payload), 'bytes')
except urllib.error.HTTPError as e:
    print('upload failed', e.code, e.read()[:200])
print('prospects', len(rows), counts)

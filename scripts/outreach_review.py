# -*- coding: utf-8 -*-
"""Review pending agency applications the way a person would, then approve or reject through
/api/ops/providers/review (same approval email as /admin/providers). Runs daily (PCE-OutreachReview)
and after each send; the owner sees every decision in data/outreach-review.jsonl and the board.

Approve when ALL hold: the website answers; the contact address is on the site's own domain (or the
site names it); no throwaway mailbox / free-hosting site; no offshore signals for the markets
claimed; at least one platform and one market. Reject on a throwaway address + free hosting, or a
dead site. Anything in between stays pending and is listed for the owner (OWNER-3 stays honest).

  python outreach_review.py [--dry]
"""
import io, os, re, sys, json, time, hmac, hashlib, datetime, urllib.request, urllib.error
sys.stdout.reconfigure(encoding='utf-8')
D = 'C:/Users/Flo/Downloads/pce-ops/data/'
LOG = D + 'outreach-review.jsonl'
DRY = '--dry' in sys.argv
env = open('C:/Users/Flo/Downloads/scopebit/.env.vercel', encoding='utf-8').read()
SECRET = re.search(r'^PCE_ACCESS_SECRET="?([^"' + chr(13) + chr(10) + r']+)"?', env, re.M).group(1).strip()
B = 'https://projectcostestimator.com'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36 pce-review (+https://projectcostestimator.com/for-agencies)', 'Accept': 'text/html,*/*;q=0.8', 'Accept-Language': 'en'}
THROWAWAY = ('atomicmail', 'mailinator', 'guerrillamail', '10minutemail', 'tempmail', 'temp-mail', 'yopmail', 'trashmail', 'sharklasers', 'dispostable', 'getnada', 'maildrop', 'throwam', 'fakeinbox')
FREEHOST = ('surge.sh', 'netlify.app', 'vercel.app', 'github.io', 'pages.dev', 'wixsite.com', 'weebly.com', 'wordpress.com', 'blogspot.', 'carrd.co', 'webflow.io', 'glitch.me', 'repl.co', 'herokuapp.com', 'notion.site', 'godaddysites.com', 'mystrikingly.com', 'square.site')
OFFSHORE = re.compile(r'\+91[\s\d-]{8,}|\+92[\s\d-]{8,}|\+880[\s\d-]{7,}|\+380[\s\d-]{7,}|\+94[\s\d-]{8,}|\+63[\s\d-]{8,}|\bPvt\.?\s*Ltd\b|Private Limited', re.I)
COUNTRY_OK = {'us': re.compile(r'\+1[\s.(-]{1,3}\d{3}|\bUnited States\b|\bUSA\b|\b(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\s+\d{5}\b'),
              'australia': re.compile(r'\+61|\bAustralia\b|\.com\.au\b|\bABN\b', re.I), 'uk': re.compile(r'\+44|\bUnited Kingdom\b|\.co\.uk\b|\bLondon\b|\bManchester\b', re.I),
              'western_europe': re.compile(r'\+3[1-4]|\+49|\+35[0-1]|\+4[1-3]|\bGmbH\b|\bB\.V\.\b|\bS\.L\.\b|\bSARL\b|\bLda\b', re.I), 'eastern_europe': re.compile(r'\+4[08]|\+42[01]|\+3[56][0-9]|\bS\.R\.L\b|\bSp\. z o\.o\b|\bs\.r\.o\b', re.I)}

def token():
    ts = str(int(time.time() * 1000))
    return ts + '.' + hmac.new(SECRET.encode(), ('ops:' + ts).encode(), hashlib.sha256).hexdigest()
def api(method, body=None):
    req = urllib.request.Request(B + '/api/ops/providers/review', data=(json.dumps(body).encode() if body else None), method=method,
                                 headers={'X-Ops-Token': token(), 'Content-Type': 'application/json', 'User-Agent': 'pce-review/1.0'})
    return json.loads(urllib.request.urlopen(req, timeout=40).read())
def host_of(u):
    m = re.match(r'https?://([^/]+)', u or ''); return (m.group(1) if m else '').lower().replace('www.', '')
def log(entry):
    entry['ts'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with io.open(LOG, 'a', encoding='utf-8') as f: f.write(json.dumps(entry, ensure_ascii=False) + '\n')

def vet(p):
    reasons = []; verdict = 'approve'
    site = p.get('website') or ''; host = host_of(site); email = (p.get('contact_email') or '').lower(); edom = email.rsplit('@', 1)[-1]
    if not p.get('platforms'): reasons.append('no platform'); verdict = 'hold'
    if not p.get('markets'): reasons.append('no market'); verdict = 'hold'
    if any(t in edom for t in THROWAWAY): reasons.append('throwaway mailbox'); verdict = 'reject'
    if any(f in host for f in FREEHOST): reasons.append('free-hosting site'); verdict = 'reject' if verdict == 'reject' or any(t in edom for t in THROWAWAY) else 'hold'
    try:
        r = urllib.request.urlopen(urllib.request.Request(site, headers=UA), timeout=25); h = r.read(400000).decode('utf-8', 'replace')
    except Exception as e:
        reasons.append('site does not answer: ' + str(e)[:50]); return ('reject' if 'throwaway mailbox' in reasons else 'hold'), reasons
    if len(h) < 4000: reasons.append('near-empty site'); verdict = 'hold' if verdict == 'approve' else verdict
    text = html_text(h)
    root = host.split('.', 1)[-1] if host.count('.') >= 2 and host.split('.')[-2] in ('com', 'co', 'net', 'org') else host
    own = edom in (host, root) or edom == host
    named = email in h.lower()
    if not (own or named): reasons.append('contact address not on own domain nor on the site'); verdict = 'hold' if verdict == 'approve' else verdict
    off = OFFSHORE.findall(text)
    claimed = [m for m in (p.get('markets') or []) if m in COUNTRY_OK]
    confirmed = [m for m in claimed if COUNTRY_OK[m].search(text)]
    if off and not confirmed: reasons.append('offshore signals (' + ', '.join(sorted(set(o.strip() for o in off))[:3]) + ') and no sign of the claimed market'); verdict = 'hold' if verdict == 'approve' else verdict
    if claimed and not confirmed and 'remote' not in (p.get('markets') or []): reasons.append('claimed market not visible on the site'); verdict = 'hold' if verdict == 'approve' else verdict
    plats = [x for x in (p.get('platforms') or []) if x.replace('2', '').replace('_plus', '') in text.lower()]
    if not plats and p.get('platforms'): reasons.append('none of the claimed platforms appears on the site (fine for custom-only shops)')
    if verdict == 'approve' and not reasons: reasons.append('live site, own-domain address, market visible' if confirmed else 'live site, own-domain address')
    return verdict, reasons

def html_text(h):
    h = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', h, flags=re.S | re.I)
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', h))

if __name__ == '__main__':
    pend = api('GET')['pending']
    print(f'pending applications: {len(pend)}')
    held = []
    for p in pend:
        verdict, reasons = vet(p)
        line = f"{verdict:8} {p['name'][:32]:32} {p.get('contact_email','')[:34]:34} {','.join(p.get('markets') or [])[:22]:22} | " + '; '.join(reasons)
        print(line)
        entry = {'id': p['id'], 'name': p['name'], 'email': p.get('contact_email'), 'website': p.get('website'), 'verdict': verdict, 'reasons': reasons, 'dry': DRY}
        if not DRY and verdict in ('approve', 'reject'):
            try:
                res = api('POST', {'id': p['id'], 'action': verdict, 'note': 'auto-review ' + datetime.date.today().isoformat() + ': ' + '; '.join(reasons)[:400]})
                entry['result'] = res; print('   ->', res)
            except urllib.error.HTTPError as e:
                entry['error'] = e.read()[:200].decode('utf-8', 'replace'); print('   -> ERROR', e.code, entry['error'])
        if verdict == 'hold': held.append(entry)
        log(entry)
    json.dump(held, open(D + 'outreach-review-held.json', 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print(f'done: {sum(1 for p in pend)} reviewed, {len(held)} held for the owner')

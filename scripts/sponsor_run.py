# -*- coding: utf-8 -*-
"""Start the sponsor-offer send on Vercel by hand (the cron does it on weekdays at 14:10 UTC).
  python scripts/sponsor_run.py --dry              what would go, nothing sent
  python scripts/sponsor_run.py --test you@x.com   one sample offer to that address, no marker
  python scripts/sponsor_run.py [--limit N]        send now; repeats the call until the day's cap or the queue ends
Auth is the one-day operator token the route accepts: HMAC-SHA256(PCE_ACCESS_SECRET, "sponsor-run:<UTC date>").
"""
import datetime, hashlib, hmac, json, re, sys, urllib.parse, urllib.request
sys.stdout.reconfigure(encoding='utf-8')
env = open(r'C:\Users\Flo\Downloads\scopebit\.env.vercel', encoding='utf-8').read()
SECRET = re.search(r'^PCE_ACCESS_SECRET="?([^"\r\n]+)"?', env, re.M).group(1).strip()
TOKEN = hmac.new(SECRET.encode(), ('sponsor-run:' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')).encode(), hashlib.sha256).hexdigest()
BASE = 'https://projectcostestimator.com/api/sponsors/offers/run'


def call(params):
    url = BASE + ('?' + urllib.parse.urlencode(params) if params else '')
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + TOKEN, 'User-Agent': 'pce-ops/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {'error': e.read().decode('utf-8', 'replace')[:300]}


def main():
    a = sys.argv[1:]
    if '--test' in a:
        print(call({'test': a[a.index('--test') + 1]})); return
    params = {}
    if '--limit' in a:
        params['limit'] = a[a.index('--limit') + 1]
    if '--dry' in a:
        st, d = call({**params, 'dry': '1'})
        print(st, {k: d.get(k) for k in ('cap', 'sentToday', 'queue', 'pages', 'error')}, 'would send', len(d.get('sent') or []))
        for x in (d.get('sent') or [])[:10]:
            print('  ', x['name'], '|', x['email'], '|', x['page'])
        return
    total = 0
    for i in range(8):
        st, d = call(params)
        sent = d.get('sent') or []
        total += len(sent)
        print(f"call {i + 1}: http {st}, sent {len(sent)}, skipped {len(d.get('skipped') or [])}, sentToday before {d.get('sentToday')}, stopped: {d.get('stopped') or d.get('error') or '-'}")
        for x in sent:
            print('  ', x['name'], '|', x['email'], '|', x['page'])
        for x in (d.get('skipped') or []):
            print('   skipped', x['email'], '-', x['why'])
        if st != 200 or not sent or 'time budget' not in (d.get('stopped') or ''):
            break
    print('total sent now:', total)


if __name__ == '__main__':
    main()

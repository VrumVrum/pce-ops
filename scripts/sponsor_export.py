# -*- coding: utf-8 -*-
"""Export the sponsor send list for the Vercel cron and keep the two sides in step.
  python scripts/sponsor_export.py            write scopebit/src/data/sponsor-prospects.json, seed markers
  python scripts/sponsor_export.py --no-seed  only write the JSON

Since 12 Nov 2026 the daily sponsor offers are sent by /api/sponsors/offers/run on Vercel, not by this PC.
That route reads src/data/sponsor-prospects.json (bundled at deploy) and keeps its state as marker rows in the
Supabase `leads` table (context 'sponsor-offer'). This script:
  1. writes the JSON from data/sponsor-prospects.csv: every row with an address, in file order (highest partner
     tiers first), fields name, email, market, topic, page_slug, partner_status;
  2. seeds a marker for every company this PC already wrote to (csv `sent` set) that has none, so the cron
     never writes to them again;
  3. pulls the markers back into the csv (`sent` = the marker's date) so the reply desk, which reads the csv,
     knows who was written to by the cron.
After a run that changes the JSON, the site must be deployed for the cron to see the new companies.
"""
import csv, io, json, os, re, sys, urllib.request
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, '..', 'data') + os.sep
LIST = D + 'sponsor-prospects.csv'
REPO = r'C:\Users\Flo\Downloads\scopebit'
OUT = os.path.join(REPO, 'src', 'data', 'sponsor-prospects.json')


def supa():
    e = open(os.path.join(REPO, '.env.local'), encoding='utf-8').read()
    url = re.search(r'^SUPABASE_URL="?([^"\r\n]+)"?', e, re.M).group(1).strip().rstrip('/')
    key = re.search(r'^SUPABASE_SERVICE_ROLE_KEY="?([^"\r\n]+)"?', e, re.M).group(1).strip()
    return url, key


def markers():
    url, key = supa()
    out = {}
    start = 0
    while True:
        req = urllib.request.Request(url + '/rest/v1/leads?select=email,context,created_at&context=in.(sponsor-offer,sponsor-skip)&order=created_at.asc',
                                     headers={'apikey': key, 'Authorization': 'Bearer ' + key, 'Range-Unit': 'items', 'Range': f'{start}-{start + 999}'})
        with urllib.request.urlopen(req, timeout=30) as r:
            rows = json.loads(r.read())
        for x in rows:
            out[(x.get('email') or '').strip().lower()] = (x.get('context'), (x.get('created_at') or '')[:10])
        if len(rows) < 1000:
            break
        start += 1000
    return out


def seed(rows_to_seed):
    url, key = supa()
    payload = [{'email': r['email'].strip().lower(), 'context': 'sponsor-offer', 'source_page': r['page_slug'], 'platform': r['topic'], 'market': r['market'],
                'config_token': json.dumps({'name': r['name'], 'sent_from': 'pc', 'sent': r['sent']})} for r in rows_to_seed]
    if not payload:
        return 0
    req = urllib.request.Request(url + '/rest/v1/leads', data=json.dumps(payload).encode(),
                                 headers={'apikey': key, 'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json', 'Prefer': 'return=minimal'}, method='POST')
    urllib.request.urlopen(req, timeout=30).read()
    return len(payload)


def main():
    rows = list(csv.DictReader(open(LIST, encoding='utf-8', newline='')))
    fields = list(rows[0].keys())
    out = [{'name': r['name'], 'email': r['email'].strip(), 'market': r['market'], 'topic': r['topic'], 'page_slug': r['page_slug'],
            'partner_status': r.get('partner_status', '')} for r in rows if r.get('email')]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
    print(f'json: {len(out)} companies with an address -> {OUT}')
    if '--no-seed' in sys.argv:
        return
    have = markers()
    need = [r for r in rows if r.get('email') and r.get('sent') and r['email'].strip().lower() not in have]
    print('markers in Supabase:', len(have), '| seeded for companies this PC wrote to:', seed(need))
    have = markers()
    changed = 0
    for r in rows:
        m = have.get((r.get('email') or '').strip().lower())
        if m and m[0] == 'sponsor-offer' and not r.get('sent'):
            r['sent'] = m[1]; changed += 1
    if changed:
        with io.open(LIST + '.tmp', 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
        os.replace(LIST + '.tmp', LIST)
    print('csv rows marked sent from the cron markers:', changed)


if __name__ == '__main__':
    main()

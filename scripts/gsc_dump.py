"""Full GSC dump for agent analysis — 28d + 90d, all dimensions, save as JSON."""
import json, time, urllib.request, urllib.parse, base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from datetime import date, timedelta

import os
_k = os.environ.get('GSC_KEY_JSON')  # Actions: secret injected as env
if _k:
    sa = json.loads(_k)
else:  # desktop fallback
    with open(os.environ.get('GSC_KEY_PATH', 'C:/Users/Flo/Downloads/gsc-key.json')) as f:
        sa = json.load(f)
header = base64.urlsafe_b64encode(json.dumps({'alg':'RS256','typ':'JWT'}).encode()).rstrip(b'=')
now = int(time.time())
claims = {'iss': sa['client_email'], 'scope': 'https://www.googleapis.com/auth/webmasters', 'aud': sa['token_uri'], 'iat': now, 'exp': now + 3600}
pb = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b'=')
pk = serialization.load_pem_private_key(sa['private_key'].encode(), password=None)
sig = pk.sign(header + b'.' + pb, padding.PKCS1v15(), hashes.SHA256())
sb = base64.urlsafe_b64encode(sig).rstrip(b'=')
jwt_token = (header + b'.' + pb + b'.' + sb).decode()
data = urllib.parse.urlencode({'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': jwt_token}).encode()
TOKEN = json.loads(urllib.request.urlopen(urllib.request.Request(sa['token_uri'], data=data, method='POST')).read())['access_token']

SITE = urllib.parse.quote('sc-domain:projectcostestimator.com', safe='')
URL = f'https://www.googleapis.com/webmasters/v3/sites/{SITE}/searchAnalytics/query'

def q(body):
    req = urllib.request.Request(URL, method='POST', headers={'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, data=json.dumps(body).encode()).read())

today = date.today()
e = (today - timedelta(days=2)).isoformat()
s28 = (today - timedelta(days=30)).isoformat()
s90 = (today - timedelta(days=92)).isoformat()
s7 = (today - timedelta(days=9)).isoformat()

dump = {
    'generated': today.isoformat(),
    'site': 'sc-domain:projectcostestimator.com',
    'totals_28d': None,
    'totals_7d': None,
    'totals_90d': None,
    'queries_28d': [],
    'pages_28d': [],
    'page_query_28d': [],
    'queries_90d': [],
    'pages_90d': [],
    'countries_28d': [],
    'devices_28d': [],
    'search_appearance_28d': [],
    'daily_28d': [],
}

# Totals
for k, start, end in [('totals_28d', s28, e), ('totals_7d', s7, e), ('totals_90d', s90, e)]:
    r = q({'startDate': start, 'endDate': end, 'dimensions': []})
    if r.get('rows'):
        row = r['rows'][0]
        dump[k] = {'clicks': row['clicks'], 'impressions': row['impressions'], 'ctr': round(row['ctr']*100, 3), 'position': round(row['position'], 2)}

# Top 500 queries 28d
r = q({'startDate': s28, 'endDate': e, 'dimensions': ['query'], 'rowLimit': 500})
dump['queries_28d'] = [{'query': row['keys'][0], 'clicks': row['clicks'], 'impressions': row['impressions'], 'ctr': round(row['ctr']*100, 2), 'position': round(row['position'], 1)} for row in r.get('rows', [])]

# Top 500 pages 28d
r = q({'startDate': s28, 'endDate': e, 'dimensions': ['page'], 'rowLimit': 500})
dump['pages_28d'] = [{'page': row['keys'][0], 'clicks': row['clicks'], 'impressions': row['impressions'], 'ctr': round(row['ctr']*100, 2), 'position': round(row['position'], 1)} for row in r.get('rows', [])]

# Top 500 page+query 28d (for content gap analysis)
r = q({'startDate': s28, 'endDate': e, 'dimensions': ['page', 'query'], 'rowLimit': 500})
dump['page_query_28d'] = [{'page': row['keys'][0], 'query': row['keys'][1], 'clicks': row['clicks'], 'impressions': row['impressions'], 'ctr': round(row['ctr']*100, 2), 'position': round(row['position'], 1)} for row in r.get('rows', [])]

# Top 500 queries 90d (trend)
r = q({'startDate': s90, 'endDate': e, 'dimensions': ['query'], 'rowLimit': 500})
dump['queries_90d'] = [{'query': row['keys'][0], 'clicks': row['clicks'], 'impressions': row['impressions'], 'ctr': round(row['ctr']*100, 2), 'position': round(row['position'], 1)} for row in r.get('rows', [])]

# Top 500 pages 90d
r = q({'startDate': s90, 'endDate': e, 'dimensions': ['page'], 'rowLimit': 500})
dump['pages_90d'] = [{'page': row['keys'][0], 'clicks': row['clicks'], 'impressions': row['impressions'], 'ctr': round(row['ctr']*100, 2), 'position': round(row['position'], 1)} for row in r.get('rows', [])]

# Countries 28d
r = q({'startDate': s28, 'endDate': e, 'dimensions': ['country'], 'rowLimit': 50})
dump['countries_28d'] = [{'country': row['keys'][0], 'clicks': row['clicks'], 'impressions': row['impressions'], 'ctr': round(row['ctr']*100, 2), 'position': round(row['position'], 1)} for row in r.get('rows', [])]

# Devices 28d
r = q({'startDate': s28, 'endDate': e, 'dimensions': ['device'], 'rowLimit': 10})
dump['devices_28d'] = [{'device': row['keys'][0], 'clicks': row['clicks'], 'impressions': row['impressions'], 'ctr': round(row['ctr']*100, 2), 'position': round(row['position'], 1)} for row in r.get('rows', [])]

# Search appearance 28d
try:
    r = q({'startDate': s28, 'endDate': e, 'dimensions': ['searchAppearance'], 'rowLimit': 20})
    dump['search_appearance_28d'] = [{'appearance': row['keys'][0], 'clicks': row['clicks'], 'impressions': row['impressions'], 'ctr': round(row['ctr']*100, 2), 'position': round(row['position'], 1)} for row in r.get('rows', [])]
except Exception as ex:
    dump['search_appearance_28d'] = [{'error': str(ex)}]

# Daily 28d
r = q({'startDate': s28, 'endDate': e, 'dimensions': ['date'], 'rowLimit': 30})
dump['daily_28d'] = [{'date': row['keys'][0], 'clicks': row['clicks'], 'impressions': row['impressions'], 'ctr': round(row['ctr']*100, 2), 'position': round(row['position'], 1)} for row in r.get('rows', [])]

# Sitemap status
SM_URL = f'https://www.googleapis.com/webmasters/v3/sites/{SITE}/sitemaps'
try:
    sm_req = urllib.request.Request(SM_URL, headers={'Authorization': f'Bearer {TOKEN}'})
    sm = json.loads(urllib.request.urlopen(sm_req).read())
    dump['sitemaps'] = sm.get('sitemap', [])
except Exception as ex:
    dump['sitemaps'] = [{'error': str(ex)}]

out = os.environ.get('GSC_OUT', 'C:/Users/Flo/Downloads/scopebit/_gsc_dump.json')
with open(out, 'w', encoding='utf-8') as f:
    json.dump(dump, f, indent=2)
print(f'[OK] Dump saved: {out}')
print(f'   queries_28d: {len(dump["queries_28d"])}')
print(f'   pages_28d: {len(dump["pages_28d"])}')
print(f'   page_query_28d: {len(dump["page_query_28d"])}')
print(f'   queries_90d: {len(dump["queries_90d"])}')
print(f'   pages_90d: {len(dump["pages_90d"])}')
print(f'   totals_28d: {dump["totals_28d"]}')
print(f'   totals_90d: {dump["totals_90d"]}')

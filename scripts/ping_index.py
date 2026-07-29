# -*- coding: utf-8 -*-
"""
Ping search engines to crawl the new pages. Reads the LIVE sitemap-cost.xml,
extracts every /cost/industry/ URL, then:
  1. Google Indexing API urlNotifications:publish (URL_UPDATED) per URL
  2. IndexNow batch (Bing + Yandex) — instant
  3. Resubmit the master sitemap to GSC

Run AFTER deploy: python automation/_ping_index.py
Needs the local GSC service-account key. Quota-safe (Indexing API ~200/day).
"""
import json, time, urllib.request, urllib.parse, base64, re, sys, os
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

KEY = os.environ.get('GSC_KEY_PATH', 'C:/Users/Flo/Downloads/gsc-key.json')
SITE = 'sc-domain:projectcostestimator.com'
INDEXNOW_KEY = 'a8f3e92d4c1b7e6f5a9d2c8b4e1f6a3d'
HOST = 'projectcostestimator.com'
UA = 'Mozilla/5.0 (compatible; pce-indexer/1.0)'


def token():
    _k = os.environ.get('GSC_KEY_JSON')   # Actions secret
    if _k:
        sa = json.loads(_k)
    else:
        with open(KEY) as f:
            sa = json.load(f)
    hdr = base64.urlsafe_b64encode(json.dumps({'alg': 'RS256', 'typ': 'JWT'}).encode()).rstrip(b'=')
    now = int(time.time())
    claims = {'iss': sa['client_email'],
              'scope': 'https://www.googleapis.com/auth/webmasters https://www.googleapis.com/auth/indexing',
              'aud': sa['token_uri'], 'iat': now, 'exp': now + 3600}
    pb = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b'=')
    pk = serialization.load_pem_private_key(sa['private_key'].encode(), password=None)
    sig = pk.sign(hdr + b'.' + pb, padding.PKCS1v15(), hashes.SHA256())
    jwt = (hdr + b'.' + pb + b'.' + base64.urlsafe_b64encode(sig).rstrip(b'=')).decode()
    data = urllib.parse.urlencode({'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': jwt}).encode()
    return json.loads(urllib.request.urlopen(urllib.request.Request(sa['token_uri'], data=data, method='POST')).read())['access_token']


def fetch_industry_urls():
    req = urllib.request.Request('https://projectcostestimator.com/sitemap-cost.xml', headers={'User-Agent': UA})
    xml = urllib.request.urlopen(req, timeout=20).read().decode('utf-8', 'ignore')
    urls = re.findall(r'<loc>([^<]+)</loc>', xml)
    return [u for u in urls if '/cost/industry/' in u or '/cost/app-like/' in u or '/cost/ai/' in u or '/tools/' in u]


def google_index(tok, urls):
    ok = 0
    for u in urls:
        try:
            req = urllib.request.Request(
                'https://indexing.googleapis.com/v3/urlNotifications:publish',
                data=json.dumps({'url': u, 'type': 'URL_UPDATED'}).encode(),
                headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'}, method='POST')
            urllib.request.urlopen(req, timeout=15)
            ok += 1
        except Exception as e:
            print('  google fail', u.split('/cost/industry/')[-1], str(e)[:50])
        time.sleep(0.15)
    print(f'[Google Indexing API] notified {ok}/{len(urls)} URLs')


def indexnow(urls):
    body = {'host': HOST, 'key': INDEXNOW_KEY,
            'keyLocation': f'https://{HOST}/{INDEXNOW_KEY}.txt', 'urlList': urls}
    try:
        req = urllib.request.Request('https://api.indexnow.org/IndexNow',
                                     data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST')
        r = urllib.request.urlopen(req, timeout=20)
        print(f'[IndexNow Bing/Yandex] batch {len(urls)} URLs -> HTTP {r.status}')
    except Exception as e:
        print('[IndexNow] error', str(e)[:80])


def resubmit_sitemaps(tok):
    for sm in ['sitemap.xml', 'sitemap-cost.xml']:
        try:
            url = f'https://www.googleapis.com/webmasters/v3/sites/{urllib.parse.quote(SITE, safe="")}/sitemaps/{urllib.parse.quote("https://projectcostestimator.com/" + sm, safe="")}'
            urllib.request.urlopen(urllib.request.Request(url, headers={'Authorization': f'Bearer {tok}'}, method='PUT'), timeout=15)
            print(f'[GSC] resubmitted {sm}')
        except Exception as e:
            print(f'[GSC] {sm} error', str(e)[:60])


if __name__ == '__main__':
    urls = fetch_industry_urls()
    print(f'Found {len(urls)} /cost/industry/ URLs live in sitemap-cost.xml')
    if not urls:
        print('No industry URLs yet — deploy first.'); sys.exit(0)
    tok = token()
    indexnow(urls)              # instant, unlimited
    resubmit_sitemaps(tok)      # tells Google to recrawl the whole set
    google_index(tok, urls)     # per-URL nudge (quota ~200/day)
    print('Done.')

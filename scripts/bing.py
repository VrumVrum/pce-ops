# -*- coding: utf-8 -*-
"""
Bing Webmaster API pull — the eyes on the index ChatGPT actually cites from.

The 08-06 forensic audit proved the AI-session decline was ChatGPT-only and
Bing-side (site thin/unmonitored there). IndexNow now PUSHES 493 URLs daily;
this script READS back what Bing holds: crawl stats, query/page stats, and
per-URL status for the llms.txt citation pages + the July-consolidated URLs
(the decline-correlation test). Alerts when a citation page is unknown to Bing.

Output: data/BING.json  (committed by the workflow like the other data files)
Requires: BING_API_KEY env (GitHub secret).
"""
import json, os, re, urllib.request, urllib.parse, datetime

KEY = os.environ.get('BING_API_KEY')
SITE = 'https://projectcostestimator.com'
BASE = 'https://ssl.bing.com/webmaster/api.svc/json'
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'BING.json')

# llms.txt-designated citation pages + money pages (mirror of metrics.py tripwire)
CITATION_PAGES = ['/', '/website-costs-2026-report', '/website-cost', '/cost-index',
                  '/rate-database', '/website-cost-calculator', '/freelance-website-cost',
                  '/calculator']
# URLs 301-consolidated in July — if Bing still holds/crawled them, the
# decline-correlation hypothesis (audit 08-06 #4) gains evidence.
CONSOLIDATED = ['/blog/nonprofit-website-cost-2026', '/blog/restaurant-website-cost-2026',
                '/blog/mvp-cost-2026', '/blog/landing-page-cost-2026',
                '/blog/website-migration-cost-2026']


def fix_dates(o):
    """Convert .NET /Date(ms)/ strings to ISO dates, recursively."""
    if isinstance(o, dict):
        return {k: fix_dates(v) for k, v in o.items()}
    if isinstance(o, list):
        return [fix_dates(x) for x in o]
    if isinstance(o, str):
        m = re.match(r'/Date\((-?\d+)', o)
        if m:
            ms = int(m.group(1))
            if ms <= 0:
                return None  # Bing's null-date sentinel
            return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).date().isoformat()
    return o


def call(method, **params):
    params = {'apikey': KEY, 'siteUrl': SITE, **params}
    url = f"{BASE}/{method}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return fix_dates(json.load(r).get('d'))
    except Exception as e:
        return {'error': str(e)[:200]}


def main():
    if not KEY:
        print('bing.py: no BING_API_KEY, skipping')
        return
    out = {'generated_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}
    out['quota'] = call('GetUrlSubmissionQuota')
    crawl = call('GetCrawlStats')
    # keep only the last 14 days of the crawl series (it can be long)
    out['crawl_stats_recent'] = crawl[-14:] if isinstance(crawl, list) else crawl
    out['query_stats'] = call('GetQueryStats')
    out['page_stats'] = call('GetPageStats')
    url_info = {}
    for path in CITATION_PAGES + CONSOLIDATED:
        info = call('GetUrlInfo', url=SITE + path)
        if isinstance(info, dict) and 'error' not in info:
            url_info[path] = {k: info.get(k) for k in
                              ('LastCrawledDate', 'IsPage', 'DocumentSize', 'HttpStatus')
                              if k in info}
        else:
            url_info[path] = info  # error or null = Bing doesn't know it
    out['url_info'] = url_info
    # Alert: citation pages Bing has never crawled (null/None/error)
    out['citation_alerts'] = [p for p in CITATION_PAGES
                              if not isinstance(url_info.get(p), dict)
                              or 'error' in url_info[p]
                              or not url_info[p].get('LastCrawledDate')]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=1)
    n_alerts = len(out['citation_alerts'])
    print(f"BING.json written — {n_alerts} citation page(s) unknown to Bing: {out['citation_alerts']}")


if __name__ == '__main__':
    main()

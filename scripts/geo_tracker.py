# -*- coding: utf-8 -*-
"""
GEO / AI-citation tracker — is projectcostestimator.com surfaced for the
commercial "how much does X cost / website cost calculator" queries that
Copilot / ChatGPT / Perplexity answer from?

HONESTY CONTRACT (the whole point of this file)
-----------------------------------------------
This repo has NO LLM API keys (no OpenAI/Anthropic/Perplexity/Gemini). We
therefore CANNOT query those engines directly, and we NEVER pretend to. Every
engine reports a `coverage` of either "measured" (real data was pulled) or
"not_measured" (no key / API unavailable). A missing key is ALWAYS
"not_measured" — it is NEVER silently counted as "not cited", and results are
NEVER fabricated. This mirrors routine-heartbeat's rule: a BLIND guard must
never read green — UNKNOWN is never a pass.

What is actually reachable today (real, keyed signals):

  bing_webmaster : Bing Webmaster Tools GetQueryStats with BING_API_KEY (the
                   key this repo owns — see scripts/bing.py, labelled "BWT API"
                   in daily-ops.yml). This returns the REAL queries for which
                   projectcostestimator.com earned Bing impressions and the avg
                   position it held. Bing's index is what Copilot and ChatGPT
                   web-search lean on, so "does PCE surface in Bing for a query
                   containing this phrase" is a real, measurable AI-surface
                   proxy. Downside: the Webmaster API only reports on our own
                   site, so it cannot list competitor domains.

  bing_web       : Bing Web Search API v7 (api.bing.microsoft.com). Gives
                   per-query rank AND competitor domains. Requires a Cognitive-
                   Services subscription key (env BING_WEBSEARCH_KEY). It is
                   also probed with BING_API_KEY as a fallback in case that key
                   doubles as a search key. If neither key authenticates, the
                   engine is honestly reported "not_measured" (with the real
                   error) and NO per-query rows are faked.

Wiring for the future: adding any of OPENAI_API_KEY / PERPLEXITY_API_KEY /
GEMINI_API_KEY / ANTHROPIC_API_KEY lights up a direct-citation check for that
engine (real request code below, gated behind the key). Until the key exists,
that engine is "not_measured" — full stop.

Output: data/GEO-STATE.json (committed by the workflow like the other data
files). The workflow FAILS LOUD only when the run is FULLY BLIND (0 engines
measured) — a healthy run with real data exits 0.

Requires: BING_API_KEY (GitHub secret). Optional: BING_WEBSEARCH_KEY and any
LLM key above.
"""
import json, os, re, sys, time, urllib.request, urllib.parse, urllib.error, datetime

SITE_DOMAIN = 'projectcostestimator.com'
BWT_KEY = os.environ.get('BING_API_KEY')
BWT_BASE = 'https://ssl.bing.com/webmaster/api.svc/json'
WEBSEARCH_KEY = os.environ.get('BING_WEBSEARCH_KEY') or os.environ.get('BING_API_KEY')
WEBSEARCH_URL = 'https://api.bing.microsoft.com/v7.0/search'
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'GEO-STATE.json')

# ~36 real commercial queries in PCE's niche (website-cost calculator).
QUERIES = [
    'how much does a website cost',
    'website cost calculator',
    'how much does a website cost to build',
    'small business website cost',
    'ecommerce website cost',
    'shopify website cost',
    'wordpress website cost',
    'how much does web design cost',
    'freelance web developer rates',
    'web development cost estimate',
    'restaurant website cost',
    'real estate website cost',
    'how much does a website cost per month',
    'website maintenance cost',
    'how much does it cost to build an app',
    'mobile app development cost',
    'website redesign cost',
    'custom website cost',
    'how much does a landing page cost',
    'web design pricing',
    'how much does it cost to hire a web developer',
    'saas website cost',
    'nonprofit website cost',
    'how much does a wix website cost',
    'squarespace website cost',
    'website cost estimator',
    'how much does an ecommerce store cost to build',
    'average cost of a website for small business',
    'web developer hourly rate',
    'how much does a business website cost',
    'website design cost breakdown',
    'how much does a website cost 2026',
    'dental website cost',
    'law firm website cost',
    'how much does a portfolio website cost',
    'mvp development cost',
]

# Surfaced-but-not-a-competitor: social / aggregators / reference. Kept OUT of
# the competitor list so "competitors" means actual cost/quote/agency sites.
NON_COMPETITORS = {
    'reddit.com', 'quora.com', 'youtube.com', 'facebook.com', 'linkedin.com',
    'twitter.com', 'x.com', 'pinterest.com', 'instagram.com', 'medium.com',
    'wikipedia.org', 'en.wikipedia.org', 'bing.com', 'microsoft.com',
    'google.com', 'apple.com', 'tiktok.com',
}


def normalize(q):
    """lowercase, strip smart quotes / trailing punctuation, collapse spaces."""
    q = q.lower().replace('”', '"').replace('“', '"').strip()
    q = re.sub(r'[?!.,"’\']+$', '', q)
    q = re.sub(r'\s+', ' ', q)
    return q.strip()


def domain_of(url):
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ''
    if host.startswith('www.'):
        host = host[4:]
    return host


# ---------------------------------------------------------------------------
# Engine 1: Bing Webmaster Tools GetQueryStats (the key we actually own)
# ---------------------------------------------------------------------------
def bwt_call(method, **params):
    params = {'apikey': BWT_KEY, 'siteUrl': f'https://{SITE_DOMAIN}', **params}
    url = f"{BWT_BASE}/{method}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r).get('d')


def run_bing_webmaster():
    """Return (engine_status, per_query dict keyed by original query)."""
    per_q = {}
    if not BWT_KEY:
        return {'coverage': 'not_measured', 'reason': 'no BING_API_KEY'}, per_q
    try:
        rows = bwt_call('GetQueryStats')
    except Exception as e:
        return {'coverage': 'not_measured', 'reason': f'GetQueryStats failed: {str(e)[:160]}'}, per_q
    if not isinstance(rows, list):
        return {'coverage': 'not_measured', 'reason': 'GetQueryStats returned no list'}, per_q

    # Aggregate daily rows -> per normalized query: best (min) impression position
    # + total impressions. AvgImpressionPosition is 1-based; -1 means "none".
    agg = {}
    for row in rows:
        nq = normalize(str(row.get('Query', '')))
        if not nq:
            continue
        pos = row.get('AvgImpressionPosition')
        imp = row.get('Impressions') or 0
        cur = agg.setdefault(nq, {'pos': None, 'imp': 0, 'clicks': 0})
        cur['imp'] += imp
        cur['clicks'] += row.get('Clicks') or 0
        if isinstance(pos, (int, float)) and pos > 0:
            cur['pos'] = pos if cur['pos'] is None else min(cur['pos'], pos)

    bwt_queries = list(agg.items())
    measured_n = 0
    for q in QUERIES:
        nq = normalize(q)
        # PCE surfaces in Bing if it earned impressions for a query that IS,
        # or CONTAINS, this phrase. (Real impression data — never inferred.)
        best_pos, tot_imp, matches = None, 0, 0
        for bq, stats in bwt_queries:
            if bq == nq or nq in bq:
                matches += 1
                tot_imp += stats['imp']
                if stats['pos'] is not None:
                    best_pos = stats['pos'] if best_pos is None else min(best_pos, stats['pos'])
        present = matches > 0
        per_q[q] = {
            'coverage': 'measured',
            'pce_present': present,
            'pce_rank': int(round(best_pos)) if present and best_pos is not None else None,
            'competitors': [],  # Webmaster API reports only our own site
            'bing_impressions': tot_imp,
            'matched_bing_queries': matches,
        }
        measured_n += 1
    return {'coverage': 'measured', 'queries_measured': measured_n,
            'note': 'presence = PCE earned Bing impressions for a query equal to or containing the phrase; no competitor data available from Webmaster API'}, per_q


# ---------------------------------------------------------------------------
# Engine 2: Bing Web Search API v7 (needs a Cognitive-Services key)
# ---------------------------------------------------------------------------
def bing_web_search(key, q):
    """Return (result_urls list, error str-or-None)."""
    qs = urllib.parse.urlencode({'q': q, 'count': 15, 'mkt': 'en-US',
                                 'responseFilter': 'Webpages', 'textDecorations': 'false'})
    req = urllib.request.Request(f"{WEBSEARCH_URL}?{qs}",
                                 headers={'Ocp-Apim-Subscription-Key': key})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = e.read().decode('utf-8', 'replace')[:200]
        except Exception:
            pass
        return None, f'HTTP {e.code}: {body or e.reason}'
    except Exception as e:
        return None, str(e)[:200]
    pages = (data.get('webPages') or {}).get('value') or []
    return [p.get('url', '') for p in pages], None


def run_bing_web():
    per_q = {}
    if not WEBSEARCH_KEY:
        return {'coverage': 'not_measured', 'reason': 'no BING_WEBSEARCH_KEY / BING_API_KEY'}, per_q

    # Probe once. If the key can't authenticate against Web Search (the repo's
    # BING_API_KEY is a Webmaster key, a different product), report the whole
    # engine not_measured with the real error — do NOT fake 36 rows.
    urls, err = bing_web_search(WEBSEARCH_KEY, QUERIES[0])
    if err is not None:
        return {'coverage': 'not_measured',
                'reason': f'Web Search API not authenticated: {err}'}, per_q

    def record(q, urls):
        doms, rank, comps = [], None, []
        for i, u in enumerate(urls or [], start=1):
            d = domain_of(u)
            if not d:
                continue
            doms.append(d)
            if d == SITE_DOMAIN and rank is None:
                rank = i
            elif d != SITE_DOMAIN and d not in NON_COMPETITORS and d not in comps:
                comps.append(d)
        per_q[q] = {'coverage': 'measured', 'pce_present': SITE_DOMAIN in doms,
                    'pce_rank': rank, 'competitors': comps[:8]}

    record(QUERIES[0], urls)
    for q in QUERIES[1:]:
        u, e = bing_web_search(WEBSEARCH_KEY, q)
        if e is not None:
            per_q[q] = {'coverage': 'not_measured', 'reason': e}
        else:
            record(q, u)
        time.sleep(0.3)
    measured_n = sum(1 for v in per_q.values() if v.get('coverage') == 'measured')
    return {'coverage': 'measured' if measured_n else 'not_measured',
            'queries_measured': measured_n}, per_q


# ---------------------------------------------------------------------------
# Engine 3..N: direct LLM citation checks — DARK until a key is added.
# Real request code lives here so a future key lights it up; with no key each
# engine is honestly "not_measured" and executes nothing.
# ---------------------------------------------------------------------------
def run_perplexity():
    key = os.environ.get('PERPLEXITY_API_KEY')
    if not key:
        return {'coverage': 'not_measured', 'reason': 'no PERPLEXITY_API_KEY'}, {}
    per_q = {}
    for q in QUERIES:
        try:
            body = json.dumps({
                'model': 'sonar',
                'messages': [{'role': 'user', 'content': q}],
            }).encode()
            req = urllib.request.Request(
                'https://api.perplexity.ai/chat/completions', data=body,
                headers={'Authorization': f'Bearer {key}',
                         'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=45) as r:
                data = json.load(r)
            cites = data.get('citations') or []
            answer = json.dumps(data.get('choices', ''))
            present = any(SITE_DOMAIN in str(c) for c in cites) or SITE_DOMAIN in answer
            comps = sorted({domain_of(c) for c in cites
                            if domain_of(c) and domain_of(c) != SITE_DOMAIN
                            and domain_of(c) not in NON_COMPETITORS})
            per_q[q] = {'coverage': 'measured', 'pce_present': present,
                        'pce_rank': None, 'competitors': comps[:8]}
        except Exception as e:
            per_q[q] = {'coverage': 'not_measured', 'reason': str(e)[:160]}
        time.sleep(0.5)
    measured_n = sum(1 for v in per_q.values() if v.get('coverage') == 'measured')
    return {'coverage': 'measured' if measured_n else 'not_measured',
            'queries_measured': measured_n}, per_q


def run_openai():
    key = os.environ.get('OPENAI_API_KEY')
    if not key:
        return {'coverage': 'not_measured', 'reason': 'no OPENAI_API_KEY'}, {}
    per_q = {}
    for q in QUERIES:
        try:
            body = json.dumps({
                'model': 'gpt-4o-mini-search-preview',
                'messages': [{'role': 'user', 'content': q}],
            }).encode()
            req = urllib.request.Request(
                'https://api.openai.com/v1/chat/completions', data=body,
                headers={'Authorization': f'Bearer {key}',
                         'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=45) as r:
                data = json.load(r)
            blob = json.dumps(data)
            present = SITE_DOMAIN in blob
            per_q[q] = {'coverage': 'measured', 'pce_present': present,
                        'pce_rank': None, 'competitors': []}
        except Exception as e:
            per_q[q] = {'coverage': 'not_measured', 'reason': str(e)[:160]}
        time.sleep(0.5)
    measured_n = sum(1 for v in per_q.values() if v.get('coverage') == 'measured')
    return {'coverage': 'measured' if measured_n else 'not_measured',
            'queries_measured': measured_n}, per_q


def run_gemini():
    if not (os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')):
        return {'coverage': 'not_measured', 'reason': 'no GEMINI_API_KEY'}, {}
    # Scaffolded; wire the grounded-generation call when a key is added.
    return {'coverage': 'not_measured', 'reason': 'gemini check not implemented (add GEMINI_API_KEY + wire call)'}, {}


def run_anthropic():
    if not os.environ.get('ANTHROPIC_API_KEY'):
        return {'coverage': 'not_measured', 'reason': 'no ANTHROPIC_API_KEY'}, {}
    # Claude has no first-party web-search-with-citations REST surface here.
    return {'coverage': 'not_measured', 'reason': 'anthropic web-citation check not implemented'}, {}


# Engine registry. Flat per-query fields are taken from the first engine in this
# order that "measured" that query (bing_web first — it carries competitors).
ENGINES = [
    ('bing_web', run_bing_web),
    ('perplexity', run_perplexity),
    ('openai', run_openai),
    ('gemini', run_gemini),
    ('anthropic', run_anthropic),
    ('bing_webmaster', run_bing_webmaster),
]
FLAT_PRIORITY = ['bing_web', 'perplexity', 'openai', 'bing_webmaster']


def main():
    engine_status = {}
    engine_rows = {}
    for name, fn in ENGINES:
        try:
            status, rows = fn()
        except Exception as e:
            status, rows = {'coverage': 'not_measured', 'reason': f'engine crashed: {str(e)[:160]}'}, {}
        engine_status[name] = status
        engine_rows[name] = rows

    engines_measured = [n for n, s in engine_status.items() if s.get('coverage') == 'measured']
    engines_unmeasured = [n for n in engine_status if n not in engines_measured]

    queries_out = []
    measured_queries = 0
    surfaced = 0
    for q in QUERIES:
        engines_block = {}
        for name in engine_status:
            row = engine_rows.get(name, {}).get(q)
            if row is not None:
                engines_block[name] = row
            else:
                # engine didn't produce a row for this query -> carry its reason
                engines_block[name] = {'coverage': 'not_measured',
                                       'reason': engine_status[name].get('reason', 'not_measured')}
        # Flat convenience fields from the best measured engine for this query.
        flat = {'pce_present': None, 'pce_rank': None, 'competitors': [],
                'engine': None, 'coverage': 'not_measured'}
        for name in FLAT_PRIORITY:
            r = engines_block.get(name)
            if r and r.get('coverage') == 'measured':
                flat = {'pce_present': r.get('pce_present'), 'pce_rank': r.get('pce_rank'),
                        'competitors': r.get('competitors', []), 'engine': name,
                        'coverage': 'measured'}
                break
        if flat['coverage'] == 'measured':
            measured_queries += 1
            if flat['pce_present']:
                surfaced += 1
        queries_out.append({'query': q, **flat, 'engines': engines_block})

    surface_rate = round(surfaced / measured_queries, 3) if measured_queries else None
    all_comps = {}
    for row in queries_out:
        for c in row['competitors']:
            all_comps[c] = all_comps.get(c, 0) + 1
    top_comps = sorted(all_comps.items(), key=lambda kv: -kv[1])[:15]

    out = {
        'generated_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
        'site': SITE_DOMAIN,
        'summary': {
            'queries_checked': len(QUERIES),
            'measured_queries': measured_queries,
            'pce_surface_rate': surface_rate,
            'pce_surfaced_count': surfaced,
            'engines_measured': engines_measured,
            'engines_unmeasured': engines_unmeasured,
            'top_competitors': [{'domain': d, 'seen_in_queries': n} for d, n in top_comps],
        },
        'engine_status': engine_status,
        'queries': queries_out,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=1)

    print(f"GEO-STATE.json written — engines measured: {engines_measured or 'NONE'}; "
          f"unmeasured: {engines_unmeasured}")
    if surface_rate is not None:
        print(f"  measured queries: {measured_queries}/{len(QUERIES)}  "
              f"pce_surface_rate: {surface_rate}  (surfaced {surfaced})")

    # FAIL LOUD only if fully blind (0 engines measured). A blind guard must
    # never read green — same rule as routine-heartbeat.
    if not engines_measured:
        print('::error::GEO tracker is FULLY BLIND — 0 engines measured. '
              'Check BING_API_KEY (Webmaster) and any LLM key. '
              'This run measured nothing and must not be counted as a pass.')
        for n, s in engine_status.items():
            print(f'  {n}: {s.get("reason", s.get("coverage"))}')
        sys.exit(2)


if __name__ == '__main__':
    main()

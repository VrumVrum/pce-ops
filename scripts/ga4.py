# -*- coding: utf-8 -*-
"""GA4 pulse for projectcostestimator.com (property 532207725) — server edition.

Why this exists: AI-assistant traffic is the site's highest-quality channel
(64.7% engagement, 128s dwell per the 2026-07-28 audits) and the whole GEO
strategy bets on growing it — but it was NOT in the automated data, so the
autonomous loop could not see whether the bet was working. This runs on the
free GitHub-Actions runner and writes data/GA4.json.

Key is injected as the GSC_KEY_JSON secret (same service account as GSC).
"""
import json, os, io, time, base64, datetime, urllib.request

PROPERTY = os.environ.get('GA4_PROPERTY', '532207725')
OUT = os.environ.get('GA4_OUT', 'data/GA4.json')
HISTORY = os.environ.get('AI_HISTORY_OUT', 'data/AI_HISTORY.jsonl')

# Source substrings that mean "an AI assistant sent this visitor"
AI_KEYS = ('chatgpt', 'openai', 'perplexity', 'claude', 'anthropic', 'gemini', 'bard',
           'copilot', 'bing.com/chat', 'you.com', 'phind')

# Engine buckets for the per-run history line ({date, per_engine:{chatgpt:N,…}})
ENGINES = {'chatgpt': ('chatgpt', 'openai'), 'perplexity': ('perplexity',),
           'claude': ('claude', 'anthropic'), 'gemini': ('gemini', 'bard'),
           'copilot': ('copilot', 'bing.com/chat'), 'other': ('you.com', 'phind')}


def token():
    k = os.environ.get('GSC_KEY_JSON')
    if k:
        sa = json.loads(k)
    else:
        with open(os.environ.get('GSC_KEY_PATH', 'C:/Users/Flo/Downloads/gsc-key.json')) as f:
            sa = json.load(f)
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    hdr = base64.urlsafe_b64encode(json.dumps({'alg': 'RS256', 'typ': 'JWT'}).encode()).rstrip(b'=')
    now = int(time.time())
    claims = {'iss': sa['client_email'],
              'scope': 'https://www.googleapis.com/auth/analytics.readonly',
              'aud': sa['token_uri'], 'iat': now, 'exp': now + 3600}
    pb = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b'=')
    pk = serialization.load_pem_private_key(sa['private_key'].encode(), password=None)
    sig = pk.sign(hdr + b'.' + pb, padding.PKCS1v15(), hashes.SHA256())
    jwt = (hdr + b'.' + pb + b'.' + base64.urlsafe_b64encode(sig).rstrip(b'=')).decode()
    data = urllib.parse.urlencode({'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                                   'assertion': jwt}).encode()
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(sa['token_uri'], data=data, method='POST')).read())['access_token']


def run(tok, body):
    req = urllib.request.Request(
        f'https://analyticsdata.googleapis.com/v1beta/properties/{PROPERTY}:runReport',
        method='POST', headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'},
        data=json.dumps(body).encode())
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def rows(res, dims, mets):
    out = []
    for r in res.get('rows', []):
        d = {dims[i]: v.get('value') for i, v in enumerate(r.get('dimensionValues', []))}
        m = {mets[i]: v.get('value') for i, v in enumerate(r.get('metricValues', []))}
        out.append({**d, **m})
    return out


def engine_of(source):
    s = (source or '').lower()
    for eng, keys in ENGINES.items():
        if any(k in s for k in keys):
            return eng
    return 'other'


def wow_alerts(per_engine, hist):
    """Engines whose 28d sessions fell >=30% vs the history line closest to 7
    days ago. Silent ([]) until there are 7 days of history to compare against."""
    day = lambda s: datetime.datetime.strptime(s, '%Y-%m-%d')
    today = datetime.datetime.utcnow()
    if not hist or (today - day(hist[0]['date'])).days < 7:
        return []
    target = today - datetime.timedelta(days=7)
    ref = min(hist, key=lambda h: abs((day(h['date']) - target).total_seconds()))
    alerts = []
    for eng, old in (ref.get('per_engine') or {}).items():
        now = per_engine.get(eng, 0)
        if old and now <= old * 0.7:
            alerts.append({'engine': eng, 'sessions_then': old, 'sessions_now': now,
                           'ref_date': ref['date'], 'drop_pct': round((old - now) / old * 100, 1)})
    return alerts


import urllib.parse  # noqa: E402 (used in token())

if __name__ == '__main__':
    t = token()
    snap = {'property': PROPERTY, 'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}

    # 1) Channels last 7d + 28d — THE key read: is AI-assistant traffic growing?
    for days, label in ((7, 'channels_7d'), (28, 'channels_28d')):
        try:
            res = run(t, {'dateRanges': [{'startDate': f'{days}daysAgo', 'endDate': 'yesterday'}],
                          'dimensions': [{'name': 'sessionDefaultChannelGroup'}],
                          'metrics': [{'name': 'sessions'}, {'name': 'totalUsers'},
                                      {'name': 'engagementRate'}, {'name': 'averageSessionDuration'}],
                          'orderBys': [{'metric': {'metricName': 'sessions'}, 'desc': True}]})
            snap[label] = rows(res, ['channel'], ['sessions', 'users', 'engagementRate', 'avgDuration'])
        except Exception as e:
            snap[label] = {'error': str(e)[:120]}

    # 2) AI referrers explicitly (chatgpt/perplexity/claude/gemini/copilot) — the citation proxy
    try:
        res = run(t, {'dateRanges': [{'startDate': '28daysAgo', 'endDate': 'yesterday'}],
                      'dimensions': [{'name': 'sessionSource'}],
                      'metrics': [{'name': 'sessions'}, {'name': 'engagementRate'}],
                      'orderBys': [{'metric': {'metricName': 'sessions'}, 'desc': True}],
                      'limit': 60})
        allsrc = rows(res, ['source'], ['sessions', 'engagementRate'])
        ai = [r for r in allsrc if any(k in (r['source'] or '').lower() for k in AI_KEYS)]
        snap['ai_sources_28d'] = ai
        snap['ai_sessions_28d'] = sum(int(float(r.get('sessions', 0))) for r in ai)
        snap['top_sources_28d'] = allsrc[:12]
    except Exception as e:
        snap['ai_sources_28d'] = {'error': str(e)[:120]}

    # 2b) Engine x landing page — WHICH page each AI engine sends people to.
    # Without this the system can see AI traffic fall but not WHERE it fell.
    try:
        res = run(t, {'dateRanges': [{'startDate': '28daysAgo', 'endDate': 'yesterday'}],
                      'dimensions': [{'name': 'sessionSource'}, {'name': 'landingPagePlusQueryString'}],
                      'metrics': [{'name': 'sessions'}],
                      'dimensionFilter': {'orGroup': {'expressions': [
                          {'filter': {'fieldName': 'sessionSource',
                                      'stringFilter': {'matchType': 'CONTAINS', 'value': k}}}
                          for k in AI_KEYS]}},
                      'orderBys': [{'metric': {'metricName': 'sessions'}, 'desc': True}],
                      'limit': 25})
        snap['ai_landings_28d'] = rows(res, ['source', 'landing'], ['sessions'])
    except Exception as e:
        snap['ai_landings_28d'] = {'error': str(e)[:120]}

    # 3) Landing pages that AI traffic actually hits — tells GEO where to double down
    try:
        res = run(t, {'dateRanges': [{'startDate': '28daysAgo', 'endDate': 'yesterday'}],
                      'dimensions': [{'name': 'landingPagePlusQueryString'}],
                      'metrics': [{'name': 'sessions'}, {'name': 'engagementRate'}],
                      'orderBys': [{'metric': {'metricName': 'sessions'}, 'desc': True}],
                      'limit': 20})
        snap['top_landing_28d'] = rows(res, ['landing'], ['sessions', 'engagementRate'])
    except Exception as e:
        snap['top_landing_28d'] = {'error': str(e)[:120]}

    # 4) Per-engine history + week-over-week alarm — answers "WHICH engine fell?"
    try:
        ai = snap.get('ai_sources_28d')
        per_engine = {}
        for r in (ai if isinstance(ai, list) else []):
            eng = engine_of(r.get('source'))
            per_engine[eng] = per_engine.get(eng, 0) + int(float(r.get('sessions', 0)))
        hist = []
        if os.path.exists(HISTORY):
            hist = [json.loads(l) for l in io.open(HISTORY, encoding='utf-8') if l.strip()]
        snap['ai_wow_alerts'] = wow_alerts(per_engine, hist)
        os.makedirs(os.path.dirname(HISTORY) or '.', exist_ok=True)
        io.open(HISTORY, 'a', encoding='utf-8').write(json.dumps(
            {'date': time.strftime('%Y-%m-%d', time.gmtime()), 'per_engine': per_engine}) + '\n')
    except Exception as e:
        snap['ai_wow_alerts'] = {'error': str(e)[:120]}

    os.makedirs(os.path.dirname(OUT) or '.', exist_ok=True)
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(snap, indent=2) + '\n')
    print('wrote', OUT, '| AI sessions 28d:', snap.get('ai_sessions_28d'),
          '| WoW alerts:', snap.get('ai_wow_alerts'))

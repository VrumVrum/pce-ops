# -*- coding: utf-8 -*-
"""
Anomaly watch — the self-questioning layer.

WHY THIS EXISTS
---------------
On 2026-08-13 the owner personally noticed three separate problems that the
system should have found on its own:

  1. All 9 cloud routines had been dead ~29h (403 after a subscription lapse).
  2. Iran was 27.6% of traffic, ~200/208 sessions "Direct" at 92% engagement
     (a bot signature), while 25 API keys were harvested in 4 days against
     exactly ONE real API call.
  3. Sitewide CTR is 0.36% where 2-4% is normal.

Every guard already in this repo checks something a human once thought to ask
about (routine silence, citation floor, visual diffs, smoke tests). Nothing
scanned for "what looks WRONG that nobody asked about". This does.

It asks the same eight questions EVERY day and answers them from live data:
geo anomaly, CTR-vs-expected-by-position, junk-query share, growth plateau,
revenue silence, signup-vs-usage ratio, funnel break, bot-KPI contamination.

The last two were added on 2026-08-13 after an audit found the same failure a
level up: the system was not only missing anomalies, it was OPTIMISING numbers
that measured bots. "26 real human leads" was 23 rows from one user_agent across
45 IPs, and nothing anywhere measured the path from opening the calculator to
paying (316 users started it in 28 days; 31 saw a result; 0 bought). A watchdog
that guards the inputs but never questions the KPI itself is guarding the wrong
thing.

WHY IT LIVES IN pce-ops AND NOT IN A ROUTINE PROMPT
---------------------------------------------------
Same reason as routine_heartbeat.py: GitHub Actions kept running perfectly
through the Anthropic outage. A watchdog that runs on the platform it must
watch shares the failure it is supposed to detect.

ALERT CHANNEL: any HIGH-severity finding => exit 1 => the workflow fails =>
GitHub emails the repo owner. That path does not depend on Anthropic.

HONEST NULLS (§3): every check is wrapped. A check whose data cannot be
reached emits a finding with answer=None and the error text. It is NEVER
silently dropped and NEVER estimated, because a watchdog that quietly reports
"all clear" when it is blind is worse than no watchdog.

Output: data/ANOMALIES.json
Env: GSC_KEY_JSON (or GSC_KEY_PATH), SUPABASE_URL, SUPABASE_SERVICE_ROLE
"""
import base64
import datetime
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metrics import detect_junk   # noqa: E402  — 5-signature AI-fanout detector, reused verbatim
from metrics import (             # noqa: E402  — one definition of "is this a person"
    BOT_UA_MIN_IPS, TEST_EMAIL, split_human_leads)
from ga4 import FUNNEL_STEPS      # noqa: E402  — one definition of the funnel, shared with the pull

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get('ANOMALY_OUT', os.path.join(ROOT, 'data', 'ANOMALIES.json'))
SITE = 'sc-domain:projectcostestimator.com'
GA4_PROPERTY = os.environ.get('GA4_PROPERTY', '532207725')
API_PROVIDER_ID = '8f3b107d-53b5-4e20-93c6-dfce70c3793d'   # usageLane __api_usage__ system row

NOW = datetime.datetime.now(datetime.timezone.utc)
TODAY = NOW.date()
# GSC finalises data ~3 days late. Ending a range any later silently mixes
# a partial day into every comparison and manufactures a fake "decline".
GSC_END = TODAY - datetime.timedelta(days=3)

# Expected organic CTR by SERP position. Public aggregate curves (Advanced Web
# Ranking / Backlinko / Sistrix all land within a point or two of these); the
# absolute values matter far less than the shape, and everything downstream is
# expressed as a RATIO to expectation, so a 20% error in the curve moves a
# ratio of 0.26 to 0.31 — it does not flip a verdict.
EXPECTED_CTR = {1: .28, 2: .15, 3: .11, 4: .08, 5: .07,
                6: .05, 7: .045, 8: .04, 9: .035, 10: .03}


def expected_ctr(pos):
    if pos is None:
        return None
    p = int(round(pos))
    if p <= 0:
        p = 1
    if p <= 10:
        return EXPECTED_CTR[p]
    if p <= 20:
        return .015
    if p <= 50:
        return .003
    return .001


# ---------------------------------------------------------------------------
# Known, DATED mitigations.
#
# Suppressing a country by name forever is how a detector goes blind: if the
# firewall rule is ever dropped the alarm never comes back. Instead a mitigation
# is recorded with the date it went live, and the check then does the OPPOSITE
# of suppressing — it VERIFIES the fix. Before the block lands in the data the
# finding is downgraded to `low` (it is already handled); once the traffic
# should have decayed out of the 7-day window and has not, it escalates back to
# `high` with "the mitigation is NOT working" as the answer.
# ---------------------------------------------------------------------------
MITIGATED_COUNTRIES = {
    'Iran': {'blocked_utc': '2026-08-13', 'via': 'Vercel firewall deny rule'},
}

# --- thresholds (tuned against real 2026-08-13 data; see the tuning notes at
#     the bottom of this file for why each number is where it is) -------------
GEO_MIN_SHARE = 12.0        # % of 7d sessions before a country is worth judging
GEO_MIN_SESSIONS = 30       # below this, engagement rate is coin-flip noise
GEO_ENG_DEVIATION = 20.0    # percentage POINTS from the site average
CTR_RATIO_ALERT = 0.40      # actual CTR below 40% of expected-by-position
CTR_PAGE_MIN_IMPR = 300     # per-page floor: fewer impressions => not a signal
CTR_PAGE_MIN_EXPECTED = 3.0 # ... and at least 3 clicks should have been expected
CTR_PAGE_MAX_POSITION = 20.5  # past page 2 the curve is a flat guess and a miss is
                              # a RANKING problem, not a click-through problem
JUNK_SHARE_ALERT = 25.0     # % of visible query impressions that are AI fanout
JUNK_GOOD_POS_ALERT = 30.0  # % of position 1-10 impressions that are junk
JUNK_GOOD_POS_HIGH = 50.0
PLATEAU_WEEKS = 3           # consecutive flat/declining weeks
PLATEAU_FLAT_PCT = 8.0      # within +/-8% week-over-week counts as "flat"
PLATEAU_IMPR_RISE = 15.0    # ... while impressions rose at least this much
API_KEY_MIN_ISSUED = 5      # below this the ratio is meaningless
API_USAGE_RATIO_ALERT = 0.20
FUNNEL_MIN_CONVERSION = 20.0   # % of users who must survive each step-to-step hop
FUNNEL_MIN_TOP = 10            # below this many wizard starts in 7d, rates are noise
BOT_LEAD_SHARE_ALERT = 50.0    # % of the headline lead count supplied by bot fleets
STRICT_LEAD_SILENCE_DAYS = 7   # days with zero de-botted human leads before alarm


def finding(fid, severity, question, answer, why, **extra):
    f = {'id': fid, 'severity': severity, 'question': question,
         'answer': answer, 'why_it_matters': why}
    f.update(extra)
    return f


def blind(fid, question, why, err):
    """A check that could not run. Reported, never dropped, never guessed."""
    return finding(fid, 'medium', question, None,
                   why + ' -- this question could NOT be answered today, so the '
                         'absence of a finding here is NOT evidence of health.',
                   error=str(err)[:300])


# --------------------------------------------------------------------------- auth
def _sa():
    k = os.environ.get('GSC_KEY_JSON')
    if k:
        return json.loads(k)
    with open(os.environ.get('GSC_KEY_PATH', 'C:/Users/Flo/Downloads/gsc-key.json')) as f:
        return json.load(f)


def token(scope):
    """Service-account JWT -> access token. Same pattern as gsc_dump.py / ga4.py."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    sa = _sa()
    hdr = base64.urlsafe_b64encode(json.dumps({'alg': 'RS256', 'typ': 'JWT'}).encode()).rstrip(b'=')
    now = int(time.time())
    claims = {'iss': sa['client_email'], 'scope': scope,
              'aud': sa['token_uri'], 'iat': now, 'exp': now + 3600}
    pb = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b'=')
    pk = serialization.load_pem_private_key(sa['private_key'].encode(), password=None)
    sig = pk.sign(hdr + b'.' + pb, padding.PKCS1v15(), hashes.SHA256())
    jwt = (hdr + b'.' + pb + b'.' + base64.urlsafe_b64encode(sig).rstrip(b'=')).decode()
    data = urllib.parse.urlencode({'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                                   'assertion': jwt}).encode()
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(sa['token_uri'], data=data, method='POST'), timeout=30
    ).read())['access_token']


class Google(object):
    """Lazily-authenticated GSC + GA4 clients (one token per scope, reused)."""

    def __init__(self):
        self._gsc = None
        self._ga4 = None

    def gsc(self, body):
        if self._gsc is None:
            self._gsc = token('https://www.googleapis.com/auth/webmasters')
        site = urllib.parse.quote(SITE, safe='')
        req = urllib.request.Request(
            f'https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query',
            method='POST', headers={'Authorization': f'Bearer {self._gsc}',
                                    'Content-Type': 'application/json'},
            data=json.dumps(body).encode())
        return json.loads(urllib.request.urlopen(req, timeout=90).read()).get('rows', [])

    def ga4(self, body):
        if self._ga4 is None:
            self._ga4 = token('https://www.googleapis.com/auth/analytics.readonly')
        req = urllib.request.Request(
            f'https://analyticsdata.googleapis.com/v1beta/properties/{GA4_PROPERTY}:runReport',
            method='POST', headers={'Authorization': f'Bearer {self._ga4}',
                                    'Content-Type': 'application/json'},
            data=json.dumps(body).encode())
        res = json.loads(urllib.request.urlopen(req, timeout=60).read())
        dims = [d['name'] for d in body.get('dimensions', [])]
        mets = [m['name'] for m in body.get('metrics', [])]
        out = []
        for r in res.get('rows', []):
            row = {dims[i]: v.get('value') for i, v in enumerate(r.get('dimensionValues', []))}
            row.update({mets[i]: v.get('value') for i, v in enumerate(r.get('metricValues', []))})
            out.append(row)
        return out


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------- supabase
def sb_env(*names):
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    envf = os.environ.get('ENV_FILE')
    if envf and os.path.exists(envf):
        t = io.open(envf, encoding='utf-8', errors='ignore').read()
        for n in names:
            m = re.search(rf'^{n}="?([^"\n]+)"?$', t, re.M)
            if m:
                return m.group(1).strip()
    return None


def sb(path, prefer=None):
    url = sb_env('SUPABASE_URL', 'NEXT_PUBLIC_SUPABASE_URL')
    key = sb_env('SUPABASE_SERVICE_ROLE', 'SUPABASE_SERVICE_ROLE_KEY', 'SERVICE_ROLE_KEY')
    if not url or not key:
        raise RuntimeError('no Supabase credentials (SUPABASE_URL / SUPABASE_SERVICE_ROLE)')
    req = urllib.request.Request(f'{url}/rest/v1/{path}', headers={
        'apikey': key, 'Authorization': f'Bearer {key}',
        **({'Prefer': prefer} if prefer else {})})
    r = urllib.request.urlopen(req, timeout=30)
    body = r.read().decode('utf-8', 'replace')
    return r, (json.loads(body) if body.strip() else [])


def iso(dt):
    """PostgREST filter value — the '+' in an offset would decode as a space."""
    return urllib.parse.quote(dt.strftime('%Y-%m-%dT%H:%M:%SZ'))


# =========================================================================== 1
def check_geo(g):
    """Q: is any country over-represented AND behaving unlike a human audience?"""
    q = ('Is any single country more than %.0f%% of the last 7 days of sessions '
         'while engaging with the site in a way that does not look human?' % GEO_MIN_SHARE)
    why = ('A bot farm shows up as one country dominating traffic on Direct/Unassigned '
           'with engagement far off the site average -- abnormally HIGH engagement is the '
           'giveaway, because real Direct traffic engages LESS than organic, not more. '
           'It poisons every metric downstream and can be a scrape/harvest campaign.')
    rows = g.ga4({'dateRanges': [{'startDate': '7daysAgo', 'endDate': 'yesterday'}],
                  'dimensions': [{'name': 'country'}],
                  'metrics': [{'name': 'sessions'}, {'name': 'engagementRate'}],
                  'orderBys': [{'metric': {'metricName': 'sessions'}, 'desc': True}],
                  'limit': 50})
    total = sum(num(r['sessions']) for r in rows)
    if total < 50:
        return [finding('geo_anomaly', 'low', q,
                        'Only %d sessions in the last 7 days -- too few for any country '
                        'share to mean anything. No judgement made.' % total, why)]
    site_eng = (sum(num(r['sessions']) * num(r['engagementRate']) for r in rows)
                / max(total, 1) * 100)

    ch = g.ga4({'dateRanges': [{'startDate': '7daysAgo', 'endDate': 'yesterday'}],
                'dimensions': [{'name': 'country'}, {'name': 'sessionDefaultChannelGroup'}],
                'metrics': [{'name': 'sessions'}],
                'orderBys': [{'metric': {'metricName': 'sessions'}, 'desc': True}],
                'limit': 200})
    by_country = {}
    for r in ch:
        d = by_country.setdefault(r['country'], {'total': 0.0, 'nonref': 0.0})
        d['total'] += num(r['sessions'])
        if r['sessionDefaultChannelGroup'] in ('Direct', 'Unassigned'):
            d['nonref'] += num(r['sessions'])

    # a 2-day tail, to tell "still happening" from "already decaying out of the window"
    recent = g.ga4({'dateRanges': [{'startDate': '2daysAgo', 'endDate': 'yesterday'}],
                    'dimensions': [{'name': 'country'}], 'metrics': [{'name': 'sessions'}],
                    'limit': 50})
    rtot = sum(num(r['sessions']) for r in recent)
    rshare = {r['country']: num(r['sessions']) / max(rtot, 1) * 100 for r in recent}

    out = []
    for r in rows:
        s = num(r['sessions'])
        share = s / total * 100
        eng = num(r['engagementRate']) * 100
        dev = eng - site_eng
        if share < GEO_MIN_SHARE or s < GEO_MIN_SESSIONS or abs(dev) < GEO_ENG_DEVIATION:
            continue
        country = r['country']
        c = by_country.get(country, {'total': 0.0, 'nonref': 0.0})
        direct_pct = c['nonref'] / max(c['total'], 1) * 100
        ans = ('%s = %.1f%% of 7d sessions (%d of %d) at %.1f%% engagement vs the site '
               'average of %.1f%% (%+.1f points). %.0f%% of those sessions are '
               'Direct/Unassigned. Last 2 days: %.1f%% of sessions.'
               % (country, share, int(s), int(total), eng, site_eng, dev,
                  direct_pct, rshare.get(country, 0.0)))
        sev = 'high' if dev > 0 else 'medium'
        mit = MITIGATED_COUNTRIES.get(country)
        if mit:
            blocked = datetime.date.fromisoformat(mit['blocked_utc'])
            days_since = (TODAY - blocked).days
            if days_since < 7:
                # The block cannot have washed out of a 7-day window yet.
                sev = 'low'
                ans += (' KNOWN + MITIGATED: blocked %s via %s, %d day(s) ago -- the 7d '
                        'window still contains pre-block traffic, so this is expected to '
                        'decay. Re-check: if it has not fallen below %.0f%% by %s, the '
                        'rule is not working.'
                        % (mit['blocked_utc'], mit['via'], days_since, GEO_MIN_SHARE,
                           (blocked + datetime.timedelta(days=7)).isoformat()))
            else:
                sev = 'high'
                ans += (' MITIGATION FAILED: %s was blocked %s via %s, %d days ago, and it '
                        'is STILL above the threshold. The rule is not doing anything.'
                        % (country, mit['blocked_utc'], mit['via'], days_since))
        out.append(finding('geo_anomaly:' + country.lower().replace(' ', '_'), sev, q, ans, why,
                           country=country, share_pct_7d=round(share, 1), sessions_7d=int(s),
                           engagement_pct=round(eng, 1), site_engagement_pct=round(site_eng, 1),
                           deviation_points=round(dev, 1),
                           direct_unassigned_pct=round(direct_pct, 1),
                           share_pct_last2d=round(rshare.get(country, 0.0), 1)))
    if not out:
        out.append(finding('geo_anomaly', 'low', q,
                           'No country clears all three bars (>=%.0f%% share, >=%d sessions, '
                           '>=%.0f point engagement deviation). Site average engagement '
                           '%.1f%% over %d sessions.'
                           % (GEO_MIN_SHARE, GEO_MIN_SESSIONS, GEO_ENG_DEVIATION,
                              site_eng, int(total)), why))
    return out


# =========================================================================== 2
def check_ctr(g):
    """Q: are we earning the clicks our RANKINGS should already be earning?"""
    q = ('For the positions we already hold, are we getting the clicks those '
         'positions should produce?')
    why = ('Impressions without clicks means the ranking is real but the result is not '
           'worth clicking -- title, meta, SERP feature theft, or a query the page does '
           'not actually answer. It is the cheapest growth lever on the site and it is '
           'invisible unless you compare CTR against what the POSITION predicts, which '
           'is exactly the comparison nobody was making.')
    out = []
    s28 = (GSC_END - datetime.timedelta(days=27)).isoformat()
    s7 = (GSC_END - datetime.timedelta(days=6)).isoformat()
    end = GSC_END.isoformat()

    # Pages, not queries: GSC anonymises rare queries, so the query dimension
    # holds ~47% of impressions but almost none of the clicks. Page rows carry
    # essentially 100% of both, which is the only honest denominator for CTR.
    pages = g.gsc({'startDate': s28, 'endDate': end, 'dimensions': ['page'], 'rowLimit': 2000})
    if not pages:
        raise RuntimeError('GSC returned no page rows for %s..%s' % (s28, end))
    impr = sum(p['impressions'] for p in pages)
    clicks = sum(p['clicks'] for p in pages)
    exp_clicks = sum(p['impressions'] * expected_ctr(p['position']) for p in pages)
    ratio = clicks / max(exp_clicks, 1e-9)

    p7 = g.gsc({'startDate': s7, 'endDate': end, 'dimensions': ['page'], 'rowLimit': 2000})
    i7 = sum(p['impressions'] for p in p7)
    c7 = sum(p['clicks'] for p in p7)
    e7 = sum(p['impressions'] * expected_ctr(p['position']) for p in p7)

    ans = ('Sitewide 28d: %d clicks on %d impressions = %.2f%% CTR. Weighting every page '
           'by its own average position, that traffic should have produced ~%.0f clicks '
           '(%.2f%% CTR). Actual is %.0f%% of expected. Last 7d: %d clicks vs ~%.0f '
           'expected (%.0f%% of expected, %.2f%% CTR).'
           % (clicks, impr, clicks / max(impr, 1) * 100, exp_clicks,
              exp_clicks / max(impr, 1) * 100, ratio * 100,
              c7, e7, c7 / max(e7, 1e-9) * 100, c7 / max(i7, 1) * 100))
    out.append(finding('ctr_vs_expected_sitewide',
                       'high' if ratio < CTR_RATIO_ALERT else 'low', q, ans, why,
                       window='%s..%s' % (s28, end),
                       clicks=clicks, impressions=impr,
                       actual_ctr_pct=round(clicks / max(impr, 1) * 100, 3),
                       expected_clicks=round(exp_clicks),
                       expected_ctr_pct=round(exp_clicks / max(impr, 1) * 100, 3),
                       ratio_of_expected=round(ratio, 3),
                       ratio_of_expected_7d=round(c7 / max(e7, 1e-9), 3)))

    # per-page offenders among the 15 biggest impression earners
    pages.sort(key=lambda p: -p['impressions'])
    bad = []
    for p in pages[:15]:
        e = p['impressions'] * expected_ctr(p['position'])
        if (p['impressions'] < CTR_PAGE_MIN_IMPR or e < CTR_PAGE_MIN_EXPECTED
                or p['position'] > CTR_PAGE_MAX_POSITION):
            continue
        r = p['clicks'] / max(e, 1e-9)
        if r < CTR_RATIO_ALERT:
            bad.append({'page': p['keys'][0].replace('https://projectcostestimator.com', '') or '/',
                        'impressions': p['impressions'], 'clicks': p['clicks'],
                        'avg_position': round(p['position'], 1),
                        'actual_ctr_pct': round(p['clicks'] / p['impressions'] * 100, 2),
                        'expected_ctr_pct': round(expected_ctr(p['position']) * 100, 2),
                        'expected_clicks': round(e, 1),
                        'ratio_of_expected': round(r, 2)})
    pq = 'Which specific pages rank but do not get clicked?'
    if bad:
        bad.sort(key=lambda b: -(b['expected_clicks'] - b['clicks']))
        lead = bad[0]
        ans = ('%d of the top 15 pages by impressions (judged only where avg position is '
               'inside %.0f, so this is a click problem and not a ranking problem) earn '
               'under %.0f%% of the clicks their position predicts. Worst by lost clicks: '
               '%s -- %d impressions at avg position %.1f, %d clicks where ~%.0f were '
               'expected (%.2f%% vs %.2f%% CTR). Total missing clicks across the %d '
               'flagged pages: ~%.0f in 28 days.'
               % (len(bad), CTR_PAGE_MAX_POSITION, CTR_RATIO_ALERT * 100, lead['page'],
                  lead['impressions'], lead['avg_position'], lead['clicks'],
                  lead['expected_clicks'], lead['actual_ctr_pct'],
                  lead['expected_ctr_pct'], len(bad),
                  sum(b['expected_clicks'] - b['clicks'] for b in bad)))
        out.append(finding('ctr_vs_expected_pages', 'high' if len(bad) >= 3 else 'medium',
                           pq, ans, why, pages=bad))
    else:
        out.append(finding('ctr_vs_expected_pages', 'low', pq,
                           'No page in the top 15 by impressions that ranks inside position '
                           '%.0f is under %.0f%% of its position-expected CTR.'
                           % (CTR_PAGE_MAX_POSITION, CTR_RATIO_ALERT * 100), why))
    return out


# =========================================================================== 3
def check_junk(g):
    """Q: how much of what we 'rank for' is machine noise nobody will ever click?"""
    q = ('What share of our impressions comes from queries that are AI/LLM fanout '
         'rather than human searches -- and how much of that sits in the GOOD '
         'positions we congratulate ourselves for?')
    why = ('Junk impressions inflate every visibility number while producing exactly zero '
           'clicks, which drags sitewide CTR down and makes rank tracking lie. Junk sitting '
           'in positions 1-10 is the worst case: it looks like we won, and it converts '
           'nothing. It also explains a chunk of the CTR gap above, so the two findings '
           'must be read together.')
    s28 = (GSC_END - datetime.timedelta(days=27)).isoformat()
    end = GSC_END.isoformat()
    rows = g.gsc({'startDate': s28, 'endDate': end, 'dimensions': ['query'], 'rowLimit': 25000})
    if not rows:
        raise RuntimeError('GSC returned no query rows for %s..%s' % (s28, end))
    site = g.gsc({'startDate': s28, 'endDate': end, 'dimensions': []})
    site_impr = site[0]['impressions'] if site else 0
    visible = sum(r['impressions'] for r in rows)
    coverage = visible / max(site_impr, 1) * 100

    junk_impr, junk_n, sample = detect_junk(rows)
    share = junk_impr / max(visible, 1) * 100

    good = [r for r in rows if r['position'] <= 10.5]
    good_impr = sum(r['impressions'] for r in good)
    gj_impr, gj_n, _ = detect_junk(good)
    gshare = gj_impr / max(good_impr, 1) * 100

    out = []
    ans = ('%.1f%% of visible query impressions are AI-fanout junk (%d impressions across '
           '%d queries, all with zero clicks). Denominator is the %d impressions GSC '
           'exposes at query level = %.0f%% of the %d sitewide (the rest are anonymised '
           'and cannot be judged). Sample: %s'
           % (share, junk_impr, junk_n, visible, coverage, site_impr,
              '; '.join(sample) if sample else '(none)'))
    out.append(finding('junk_query_share',
                       'medium' if share > JUNK_SHARE_ALERT else 'low', q, ans, why,
                       junk_impressions=junk_impr, junk_queries=junk_n,
                       visible_query_impressions=visible, sitewide_impressions=site_impr,
                       query_dimension_coverage_pct=round(coverage, 1),
                       junk_share_pct=round(share, 1), sample=sample))

    gq = 'How much of our position 1-10 visibility is junk?'
    sev = ('high' if gshare > JUNK_GOOD_POS_HIGH else
           'medium' if gshare > JUNK_GOOD_POS_ALERT else 'low')
    gans = ('%.1f%% of position 1-10 impressions are junk queries (%d of %d impressions, '
            '%d of %d queries). Those rankings produce no clicks by construction, so the '
            'top-10 footprint is %.0f%% smaller than it looks.'
            % (gshare, gj_impr, good_impr, gj_n, len(good), gshare))
    out.append(finding('junk_in_good_positions', sev, gq, gans, why,
                       good_position_impressions=good_impr, junk_impressions=gj_impr,
                       junk_share_pct=round(gshare, 1)))
    return out


# =========================================================================== 4
def check_plateau(g):
    """Q: are we becoming more visible without becoming more visited?"""
    q = ('Have organic sessions been flat or falling for %d weeks or more WHILE '
         'search impressions rose?' % PLATEAU_WEEKS)
    why = ('Rising impressions with flat sessions is the signature of "visible but not '
           'clicked": more content is indexed, more queries match, and none of it converts '
           'into a visit. Chasing more content in that state makes the divergence worse. '
           'It is only detectable by looking at the two curves TOGETHER, which no existing '
           'guard did.')
    weeks = PLATEAU_WEEKS + 2
    # Both series end on the same day (GSC_END) or the comparison is meaningless.
    start = GSC_END - datetime.timedelta(days=weeks * 7 - 1)
    daily = g.gsc({'startDate': start.isoformat(), 'endDate': GSC_END.isoformat(),
                   'dimensions': ['date'], 'rowLimit': 200})
    impr_w = [0] * weeks
    for r in daily:
        b = (GSC_END - datetime.date.fromisoformat(r['keys'][0])).days // 7
        if 0 <= b < weeks:
            impr_w[b] += r['impressions']

    ga = g.ga4({'dateRanges': [{'startDate': start.isoformat(), 'endDate': GSC_END.isoformat()}],
                'dimensions': [{'name': 'date'}, {'name': 'sessionDefaultChannelGroup'}],
                'metrics': [{'name': 'sessions'}], 'limit': 5000})
    sess_w = [0] * weeks
    for r in ga:
        if r['sessionDefaultChannelGroup'] != 'Organic Search':
            continue
        d = r['date']
        dt = datetime.date(int(d[:4]), int(d[4:6]), int(d[6:8]))
        b = (GSC_END - dt).days // 7
        if 0 <= b < weeks:
            sess_w[b] += int(num(r['sessions']))

    # index 0 = most recent completed week; flip to chronological for reading
    sess = list(reversed(sess_w))
    impr = list(reversed(impr_w))
    labels = [(GSC_END - datetime.timedelta(days=(weeks - 1 - i) * 7)).isoformat()
              for i in range(weeks)]

    tail = sess[-PLATEAU_WEEKS:]
    flat = all(tail[i + 1] <= tail[i] * (1 + PLATEAU_FLAT_PCT / 100)
               for i in range(len(tail) - 1))
    itail = impr[-PLATEAU_WEEKS:]
    rise = (itail[-1] - itail[0]) / max(itail[0], 1) * 100
    srise = (tail[-1] - tail[0]) / max(tail[0], 1) * 100

    series = ' | '.join('w/e %s: %d sessions, %d impressions' % (labels[i], sess[i], impr[i])
                        for i in range(weeks))
    if flat and rise >= PLATEAU_IMPR_RISE:
        sev = 'high'
        ans = ('Yes. Organic sessions %s over the last %d weeks (no week gained more than '
               '%.0f%%) while impressions rose %.0f%% over the same weeks. Full series: %s'
               % (' -> '.join(str(x) for x in tail), PLATEAU_WEEKS, PLATEAU_FLAT_PCT,
                  rise, series))
    elif flat:
        sev = 'medium'
        ans = ('Sessions are flat (%s over %d weeks) but impressions are NOT rising '
               '(%+.0f%%), so this is a visibility problem rather than a click problem. '
               'Full series: %s'
               % (' -> '.join(str(x) for x in tail), PLATEAU_WEEKS, rise, series))
    else:
        sev = 'low'
        ans = ('No plateau. Over the last %d weeks organic sessions moved %+.0f%% (%s) '
               'against %+.0f%% on impressions -- sessions are keeping up with visibility, '
               'which is the healthy side of this divergence. Full series: %s'
               % (PLATEAU_WEEKS, srise, ' -> '.join(str(x) for x in tail), rise, series))
    return [finding('growth_plateau', sev, q, ans, why,
                    weeks_ending=labels, organic_sessions_by_week=sess,
                    impressions_by_week=impr, impressions_change_pct=round(rise, 1),
                    sessions_change_pct=round(srise, 1), sessions_flat=flat,
                    note=('Both series are cut to the same days and end on the GSC window '
                          'end (%s), because comparing a fresh GA4 week against a '
                          '3-day-lagged GSC week manufactures a fake divergence.'
                          % GSC_END.isoformat()))]


# =========================================================================== 5
def check_revenue(g):
    """Q: has anyone paid us, ever, recently -- and how much traffic went unmonetised?"""
    q = 'How many days since the last sale, and how much traffic arrived in that time?'
    why = ('Rule #1 is revenue. Traffic that produces no sale for weeks is not a marketing '
           'problem to optimise around the edges -- it is the whole business failing, and '
           'it must be stated plainly instead of being buried under impression charts.')
    r, _ = sb('sales?select=count', 'count=exact')
    total = int(r.headers.get('content-range', '/0').split('/')[-1])

    # Total sessions include the bot country, so organic is quoted alongside it:
    # organic is the hardest number for a bot farm to fake and is the honest
    # floor for "real humans who could have bought something".
    sessions_28d = organic_28d = None
    try:
        rows = g.ga4({'dateRanges': [{'startDate': '28daysAgo', 'endDate': 'yesterday'}],
                      'dimensions': [{'name': 'sessionDefaultChannelGroup'}],
                      'metrics': [{'name': 'sessions'}]})
        sessions_28d = int(sum(num(r['sessions']) for r in rows))
        organic_28d = int(sum(num(r['sessions']) for r in rows
                              if r['sessionDefaultChannelGroup'] == 'Organic Search'))
    except Exception:
        sessions_28d = organic_28d = None      # honest null; never invented

    ctx = ('%s sessions in the last 28 days (%s of them organic)'
           % (sessions_28d if sessions_28d is not None else 'an unknown number of',
              organic_28d if organic_28d is not None else 'an unknown number'))
    if total == 0:
        return [finding('revenue_silence', 'high', q,
                        'The `sales` table has NEVER contained a row -- 0 sales, all time. '
                        'Days since last sale is therefore undefined (null), not a large '
                        'number. Against that: %s. Every visitor so far has been free.' % ctx,
                        why, sales_total=0, days_since_last_sale=None,
                        sessions_28d=sessions_28d, organic_sessions_28d=organic_28d)]

    _, rows = sb('sales?select=created_at&order=created_at.desc&limit=1')
    last = rows[0]['created_at'] if rows else None
    if not last:
        return [finding('revenue_silence', 'medium', q,
                        'The `sales` table reports %d rows but no readable created_at on '
                        'the newest one -- cannot compute the gap. Not guessing.' % total,
                        why, sales_total=total, days_since_last_sale=None,
                        sessions_28d=sessions_28d)]
    dt = datetime.datetime.fromisoformat(last.replace('Z', '+00:00'))
    days = (NOW - dt).days
    sev = 'high' if days >= 14 else 'medium' if days >= 7 else 'low'
    return [finding('revenue_silence', sev, q,
                    '%d days since the last sale (%s). %d sales all time. Against that: %s.'
                    % (days, last[:19], total, ctx), why,
                    sales_total=total, days_since_last_sale=days,
                    last_sale_utc=last[:19], sessions_28d=sessions_28d,
                    organic_sessions_28d=organic_28d)]


# =========================================================================== 6
def check_api_harvest(g):
    """Q: are the API keys we hand out ever actually used?"""
    q = ('How many API keys were issued in the last 7 days, and how many API calls '
         'were actually made with them?')
    why = ('Keys issued but never used are not signups -- they are email harvesting or '
           'credential scraping against a free endpoint. It inflates the lead count, '
           'poisons the drip list, and hands an unauthenticated scraper a free quota. '
           'A real signup uses the key within hours.')
    cut = iso(NOW - datetime.timedelta(days=7))
    _, leads = sb('leads?select=created_at,email,context&context=eq.api_key'
                  f'&created_at=gte.{cut}&order=created_at.desc&limit=500')
    # Owner/agent test rows are not signups (F18).
    TEST = re.compile(r'florin\.florea84|\+(test|apilive|probe)@')
    issued = [x for x in leads if not TEST.search(x.get('email') or '')]

    _, clicks = sb('provider_clicks?select=created_at,user_inputs'
                   f'&provider_id=eq.{API_PROVIDER_ID}&created_at=gte.{cut}'
                   '&order=created_at.desc&limit=1000')
    used = len(clicks)
    ok = sum(1 for c in clicks
             if (c.get('user_inputs') or {}).get('status') not in ('bad_key', 'no_key', 'rate_limited'))
    ratio = used / max(len(issued), 1)

    if len(issued) < API_KEY_MIN_ISSUED:
        return [finding('signup_vs_usage', 'low', q,
                        '%d API keys issued in the last 7 days and %d usage events -- '
                        'too few issues to judge a ratio.' % (len(issued), used), why,
                        keys_issued_7d=len(issued), usage_events_7d=used)]
    sev = 'high' if ratio <= API_USAGE_RATIO_ALERT else 'low'
    ans = ('%d API keys issued in the last 7 days against %d recorded API usage event(s) '
           '-- %d of which were valid calls. Usage/issue ratio %.2f. Distinct signup '
           'domains: %d.'
           % (len(issued), used, ok, ratio,
              len({(x.get('email') or '@').split('@')[-1] for x in issued})))
    if sev == 'high':
        ans += (' A key that is never called is not a user. This is the harvesting '
                'signature: the endpoint is handing out quota to something that only '
                'wants the key.')
    return [finding('signup_vs_usage', sev, q, ans, why,
                    keys_issued_7d=len(issued), usage_events_7d=used,
                    valid_usage_events_7d=ok, usage_per_issue=round(ratio, 3))]


# =========================================================================== 7
def _funnel_users(g, days):
    """Distinct users + events per funnel step over `days`. One undated query:
    summing a per-day user count would count the same person once per day."""
    rows = g.ga4({'dateRanges': [{'startDate': '%ddaysAgo' % days, 'endDate': 'yesterday'}],
                  'dimensions': [{'name': 'eventName'}],
                  'metrics': [{'name': 'eventCount'}, {'name': 'totalUsers'}],
                  'dimensionFilter': {'andGroup': {'expressions': [
                      {'filter': {'fieldName': 'eventName',
                                  'inListFilter': {'values': [n for n, _ in FUNNEL_STEPS]}}},
                      # HUMANS ONLY. The all-traffic funnel reads 316 entrants at 10.1%
                      # engagement and looks like a catastrophic leak; 247 of those 316
                      # are the Macintosh-desktop bot fleet engaging at 4%, while real
                      # mobile visitors engage at 52.4%. Judging the product on a
                      # bot-contaminated denominator would be FAILURE CLASS F30 repeating
                      # inside the guard built to catch F30. Conservative on purpose: this
                      # also drops genuine macOS visitors, so it is a FLOOR on human
                      # behaviour, never a headcount -- and it must never be quoted as one.
                      {'notExpression': {'filter': {'fieldName': 'country',
                                                    'stringFilter': {'value': 'Iran'}}}},
                      {'notExpression': {'andGroup': {'expressions': [
                          {'filter': {'fieldName': 'deviceCategory',
                                      'stringFilter': {'value': 'desktop'}}},
                          {'filter': {'fieldName': 'operatingSystem',
                                      'stringFilter': {'value': 'Macintosh'}}}]}}}]}},
                  'limit': 50})
    by = {r['eventName']: r for r in rows}
    # An event GA4 has never recorded returns NO ROW. The query succeeded, so
    # that is a true zero, not an unknown -- and saying so is the whole point of
    # this check. A query that FAILS raises, and main() converts it to a null.
    return [{'event': n, 'means': m,
             'users': int(num((by.get(n) or {}).get('totalUsers'))),
             'events': int(num((by.get(n) or {}).get('eventCount')))}
            for n, m in FUNNEL_STEPS]


def check_funnel(g):
    """Q: of the people who open the calculator, how many reach an answer and pay?"""
    q = ('Of the REAL people (bot fleet excluded) who open the calculator in the last 7 days, how many reach a '
         'result screen, leave an email, and pay -- and at which step do they vanish?')
    why = ('This is the question that answers "why is revenue zero", and until 2026-08-13 '
           'no file in either repo contained the number. Everything the system optimised -- '
           'impressions, sessions, lead counts -- measures the TOP of a funnel whose middle '
           'is falling out. A step that drops below %.0f%% of the step above it, or a step '
           'sitting at zero while the one above it is not, is a broken product path: more '
           'traffic poured into it changes nothing, and shipping more content is the wrong '
           'response.' % FUNNEL_MIN_CONVERSION)
    seven = _funnel_users(g, 7)
    try:
        month = _funnel_users(g, 28)
    except Exception:
        month = None        # context only; the verdict is a 7d verdict

    ladder = ' -> '.join('%s %d users' % (s['event'], s['users']) for s in seven)
    top = seven[0]['users']

    # A funnel whose TOP is zero is not "no breaks found" -- it is either nobody
    # opening the product or GA4 tracking that stopped firing. Both are HIGH, and
    # without this branch the loop below would find nothing and report health.
    if top == 0:
        return [finding('funnel_break', 'high', q,
                        'ZERO users fired %s in the last 7 days. Either nobody opened the '
                        'calculator at all, or the analytics that measure the product '
                        'stopped reporting. Both are emergencies and they are not '
                        'distinguishable from inside GA4 -- check the live site before '
                        'reading any other number in this file. Full ladder: %s'
                        % (FUNNEL_STEPS[0][0], ladder), why,
                        window_days=7, steps=seven, steps_28d=month,
                        breaks=None, weak_steps=None)]

    breaks, weak, rates = [], [], []
    for i in range(1, len(seven)):
        above, below = seven[i - 1], seven[i]
        if above['users'] == 0:
            rates.append({'from': above['event'], 'to': below['event'],
                          'users_pct': None,
                          'note': 'undefined: the step above is itself zero'})
            continue
        pct = round(below['users'] / above['users'] * 100, 1)
        rates.append({'from': above['event'], 'to': below['event'], 'users_pct': pct})
        if below['users'] == 0:
            breaks.append({'from': above['event'], 'from_users': above['users'],
                           'to': below['event'], 'means': below['means']})
        elif pct < FUNNEL_MIN_CONVERSION:
            weak.append({'from': above['event'], 'to': below['event'], 'users_pct': pct,
                         'from_users': above['users'], 'to_users': below['users']})

    thin = top < FUNNEL_MIN_TOP
    sev = 'high' if (breaks or weak) and not thin else 'low' if not (breaks or weak) else 'medium'
    parts = ['Last 7 days: %s.' % ladder]
    if month:
        parts.append('Last 28 days: %s.'
                     % ' -> '.join('%s %d users' % (s['event'], s['users']) for s in month))
    for b in breaks:
        parts.append('BROKEN: %d users reached %s and %d went on to %s (%s) -- the step is '
                     'at zero while the one above it is not.'
                     % (b['from_users'], b['from'], 0, b['to'], b['means']))
    for w in weak:
        parts.append('WEAK: only %.1f%% of %s users (%d of %d) survive to %s, against a %.0f%% floor.'
                     % (w['users_pct'], w['from'], w['to_users'], w['from_users'],
                        w['to'], FUNNEL_MIN_CONVERSION))
    if thin and (breaks or weak):
        parts.append('Downgraded to medium: only %d users entered the funnel this week '
                     '(floor %d), so these rates are small-sample noise as much as signal.'
                     % (top, FUNNEL_MIN_TOP))
    if not breaks and not weak:
        parts.append('No step lost more than %.0f%% of the step above it and no step is at '
                     'zero below a live one.' % (100 - FUNNEL_MIN_CONVERSION))
    return [finding('funnel_break', sev, q, ' '.join(parts), why,
                    window_days=7, steps=seven, steps_28d=month,
                    step_to_step_users_pct=rates, breaks=breaks, weak_steps=weak,
                    note=('Users are distinct per window (undated GA4 query). A ratio above '
                          '100%% is not a bug: GA4 de-duplicates users per event, and a '
                          'visitor can reach a result from a shared config link without '
                          'firing the step above it.'))]


# =========================================================================== 8
def check_bot_kpi_contamination(g):
    """Q: are the rows we call "real human leads" people, or one bot fleet?"""
    q = ('Are the rows counted as "real human leads" actually people -- or is a single '
         'bot fleet supplying the headline conversion KPI?')
    why = ('On 2026-08-13 the headline "26 real human leads" turned out to be 23 rows from '
           'ONE byte-identical user_agent seen across 45 distinct ip_hash values, plus 3 '
           'genuine captures. The system had even run a three-fire investigation into why '
           'the number was STUCK at 26 without ever asking whether the 26 were people. A '
           'KPI that measures a bot sends every downstream decision -- content, pricing, '
           'drip, roadmap -- chasing an audience that will never buy anything, and it does '
           'it silently, because the number looks healthy.')
    _, raw = sb('leads?select=created_at,email,context,user_agent,ip_hash'
                '&order=created_at.desc&limit=5000')
    rows = [x for x in raw if not TEST_EMAIL.search(x.get('email') or '')]
    human, strict, fleets = split_human_leads(rows)

    if not human:
        return [finding('bot_kpi_contamination', 'high', q,
                        'There are ZERO lead-context rows in the table at all (%d rows total '
                        'after test-row exclusion). The conversion KPI is not contaminated; '
                        'it is empty.' % len(rows), why,
                        headline_leads=0, strict_human_leads=0, bot_lead_share_pct=None,
                        last_strict_human_lead_utc=None)]

    bot_leads = len(human) - len(strict)
    share = round(bot_leads / len(human) * 100, 1)
    cut = NOW - datetime.timedelta(days=STRICT_LEAD_SILENCE_DAYS)
    recent = [x for x in strict
              if (x.get('created_at') or '') >= cut.strftime('%Y-%m-%dT%H:%M:%S')]
    last = strict[0]['created_at'][:19] if strict else None
    days_since = None
    if last:
        try:
            days_since = (NOW - datetime.datetime.fromisoformat(
                last).replace(tzinfo=datetime.timezone.utc)).days
        except ValueError:
            days_since = None

    silent = len(recent) == 0
    sev = 'high' if (silent or share > BOT_LEAD_SHARE_ALERT) else 'low'
    fleet_txt = '; '.join('%d distinct ip_hash / %d lead rows: %s'
                          % (n, sum(1 for x in human if (x.get('user_agent') or '') == ua),
                             (ua or '(empty)')[:90])
                          for ua, n in sorted(fleets.items(), key=lambda kv: -kv[1])[:3])
    ans = ('%d leads carry a human context. %d of them come from %d bot fleet(s) -- a '
           'user_agent shared across >=%d distinct ip_hash values -- leaving %d genuine '
           'capture(s), %.1f%% bot. %s'
           % (len(human), bot_leads, len(fleets), BOT_UA_MIN_IPS, len(strict), share,
              ('Fleets: ' + fleet_txt) if fleets else 'No fleet detected.'))
    if silent:
        ans += (' No de-botted human lead in the last %d days (last was %s%s). The lead KPI '
                'has been moving on bot traffic alone.'
                % (STRICT_LEAD_SILENCE_DAYS, last or 'never',
                   '' if days_since is None else ', %d days ago' % days_since))
    else:
        ans += (' %d genuine capture(s) in the last %d days.'
                % (len(recent), STRICT_LEAD_SILENCE_DAYS))
    if share > BOT_LEAD_SHARE_ALERT:
        ans += (' Above the %.0f%% contamination bar: the headline number is majority bot '
                'and must not be quoted as conversion.' % BOT_LEAD_SHARE_ALERT)
    return [finding('bot_kpi_contamination', sev, q, ans, why,
                    headline_leads=len(human), strict_human_leads=len(strict),
                    bot_leads=bot_leads, bot_lead_share_pct=share,
                    strict_human_leads_7d=len(recent),
                    last_strict_human_lead_utc=last,
                    days_since_last_strict_human_lead=days_since,
                    fleets=[{'distinct_ip_hashes': n, 'user_agent': (ua or '(empty)')[:160]}
                            for ua, n in sorted(fleets.items(), key=lambda kv: -kv[1])])]


RECON_MAX_GAP_PCT = 35.0


def check_reconciliation(g):
    """Q: do two independent sources agree on how many people Google sent us?"""
    q = ('Does Search Console agree with Analytics on how many people Google actually '
         'sent us, and does Analytics claim MORE visitors than Google says it sent?')
    why = ('These are independent systems: GSC counts clicks at the search result, GA4 '
           'counts sessions on the page. GA4 should land slightly BELOW GSC (consent '
           'banners, people who leave before the tag loads). GA4 reading ABOVE GSC is '
           'structurally impossible for real organic traffic and means the number is '
           'inflated. On 2026-08-13 the raw figure was +33% over GSC and the excess was '
           'exactly the bot fleet arriving with a google referrer, while the '
           'human-filtered figure landed at -4%. So this is two guards in one: it catches '
           'a broken analytics tag AND it re-validates the bot filter every day against a '
           'source the bots do not control. The owner spotted this reconciliation by hand; '
           'it should never have needed a human to notice.')
    end = GSC_END
    start = end - datetime.timedelta(days=27)
    gr = g.gsc({'startDate': str(start), 'endDate': str(end),
                'dimensions': [], 'dataState': 'all'})
    clicks = int(num((gr[0] if gr else {}).get('clicks')))
    rng = [{'startDate': str(start), 'endDate': str(end)}]
    goog_org = [{'filter': {'fieldName': 'sessionSource',
                            'stringFilter': {'value': 'google'}}},
                {'filter': {'fieldName': 'sessionDefaultChannelGroup',
                            'stringFilter': {'value': 'Organic Search'}}}]
    human = goog_org + [
        {'notExpression': {'filter': {'fieldName': 'country',
                                      'stringFilter': {'value': 'Iran'}}}},
        {'notExpression': {'andGroup': {'expressions': [
            {'filter': {'fieldName': 'deviceCategory',
                        'stringFilter': {'value': 'desktop'}}},
            {'filter': {'fieldName': 'operatingSystem',
                        'stringFilter': {'value': 'Macintosh'}}}]}}}]

    def sess(exprs):
        rr = g.ga4({'dateRanges': rng, 'metrics': [{'name': 'sessions'}],
                    'dimensionFilter': {'andGroup': {'expressions': exprs}}, 'limit': 1})
        return int(num(rr[0].get('sessions'))) if rr else 0

    raw, hum = sess(goog_org), sess(human)
    if not clicks:
        return [finding('tracking_reconciliation', 'low', q,
                        'GSC reported 0 Google clicks in the window - nothing to '
                        'reconcile against.', why,
                        gsc_clicks=0, ga4_raw=raw, ga4_human=hum)]
    gap_raw = (raw - clicks) / clicks * 100.0
    gap_hum = (hum - clicks) / clicks * 100.0
    sev = 'high' if abs(gap_hum) > RECON_MAX_GAP_PCT else 'low'
    a = ('Search Console: %d Google clicks (28d). Analytics google/organic: %d raw '
         '(%+.0f%% vs GSC), %d after removing the bot slice (%+.0f%%). '
         % (clicks, raw, gap_raw, hum, gap_hum))
    if sev == 'high':
        a += ('The HUMAN figure is more than %.0f%% away from GSC - either the analytics '
              'tag is broken or double-firing, or the bot filter has stopped matching what '
              'the bots now look like. Every human-traffic number on the site is suspect '
              'until this is explained.' % RECON_MAX_GAP_PCT)
    else:
        a += ('Within normal drift, so the human-traffic numbers are corroborated by a '
              'source the bots do not control.')
        if gap_raw > RECON_MAX_GAP_PCT:
            a += (' Note: the RAW figure is %+.0f%% over GSC, which is impossible for real '
                  'organic traffic - the excess of %d sessions is the bot fleet arriving '
                  'with a google referrer.' % (gap_raw, raw - hum))
    return [finding('tracking_reconciliation', sev, q, a, why,
                    gsc_clicks=clicks, ga4_raw=raw, ga4_human=hum,
                    gap_raw_pct=round(gap_raw, 1), gap_human_pct=round(gap_hum, 1))]


CHECKS = [
    ('tracking_reconciliation', check_reconciliation,
     'Do Search Console and Analytics agree on how many people Google sent us?',
     'Two independent sources disagreeing means either the analytics tag is broken or the bot filter has gone stale, and every human number depends on both.'),
    ('geo_anomaly', check_geo,
     'Is any single country over-represented and behaving unlike a human audience?',
     'A bot farm poisons every downstream metric and can be a scrape/harvest campaign.'),
    ('ctr_vs_expected', check_ctr,
     'Are we earning the clicks our existing rankings should already produce?',
     'Impressions without clicks is the cheapest growth lever on the site.'),
    ('junk_query_share', check_junk,
     'What share of our impressions is AI-fanout junk rather than human search?',
     'Junk impressions inflate visibility while converting nothing.'),
    ('growth_plateau', check_plateau,
     'Are we becoming more visible without becoming more visited?',
     'Rising impressions with flat sessions means more content will not help.'),
    ('revenue_silence', check_revenue,
     'How long has it been since anyone paid us?',
     'Rule #1 is revenue; traffic without sales is the whole business failing.'),
    ('signup_vs_usage', check_api_harvest,
     'Are the API keys we hand out ever actually used?',
     'Keys issued but never used are harvesting, not signups.'),
    ('funnel_break', check_funnel,
     'Of the people who open the calculator, how many reach a result, leave an email, and pay?',
     'This is the number that answers "why is revenue zero"; before 2026-08-13 it existed nowhere.'),
    ('bot_kpi_contamination', check_bot_kpi_contamination,
     'Are the rows we call "real human leads" actually people?',
     'A conversion KPI made of bot traffic sends every downstream decision chasing an audience that cannot buy.'),
]


# --- alert state: signal without fatigue -------------------------------------
# The first live run mailed the owner 4 HIGH findings. Every one is real, and
# every one will still be true tomorrow (revenue silence lasts until the first
# sale; a CTR gap lasts until the rewrites land). Mailing the same four every
# morning would train the owner to delete the mail unread, which costs more than
# the guard is worth. So: findings persist in the JSON (the operating loop still
# reads them and STEP 0A-bis still binds it to act), but the ALERT fires only on a
# real change of state -- something new, something worse, or a weekly reminder so
# nothing quietly rots forever.
REMIND_AFTER_DAYS = 7
RANK = {'high': 0, 'medium': 1, 'low': 2}


def load_prev():
    try:
        return json.loads(io.open(OUT, encoding='utf-8').read())
    except Exception:
        return {}


def apply_state(findings, prev):
    """Carry first_seen/last_alerted forward; classify each HIGH vs the last run."""
    prev_by_id = {f['id']: f for f in prev.get('findings', [])}
    now_s = NOW.strftime('%Y-%m-%dT%H:%M:%SZ')
    new, escalated, persisting, due = [], [], [], []
    for f in findings:
        p = prev_by_id.get(f['id'])
        f['first_seen_utc'] = (p or {}).get('first_seen_utc') or now_s
        f['last_alerted_utc'] = (p or {}).get('last_alerted_utc')
        if f['severity'] != 'high':
            continue
        if p is None:
            f['state'] = 'new'
            new.append(f)
        elif RANK.get(p.get('severity'), 3) > RANK['high']:
            f['state'] = 'escalated'
            escalated.append(f)
        else:
            f['state'] = 'persisting'
            persisting.append(f)
            la = f['last_alerted_utc']
            stale = True
            if la:
                try:
                    d = datetime.datetime.strptime(la, '%Y-%m-%dT%H:%M:%SZ')
                    d = d.replace(tzinfo=datetime.timezone.utc)
                    stale = (NOW - d).days >= REMIND_AFTER_DAYS
                except ValueError:
                    stale = True
            if stale:
                due.append(f)
    cur = {f['id']: f['severity'] for f in findings}
    resolved = [pid for pid, pf in prev_by_id.items()
                if pf.get('severity') == 'high'
                and RANK.get(cur.get(pid, 'gone'), 3) > 0]
    return {'new': new, 'escalated': escalated, 'persisting': persisting,
            'due_reminder': due, 'resolved': resolved}


def main():
    g = Google()
    findings = []
    for fid, fn, q, why in CHECKS:
        try:
            findings.extend(fn(g))
        except Exception as e:
            findings.append(blind(fid, q, why, e))

    rank = RANK
    findings.sort(key=lambda f: (rank.get(f['severity'], 3), f['id']))
    high = [f for f in findings if f['severity'] == 'high']
    prev = load_prev()
    st = apply_state(findings, prev)
    # A single unreachable API is not an emergency, but a watchdog that cannot
    # see anything must never look like a quiet, healthy day (the F29 lesson).
    unanswered = [f for f in findings if f['answer'] is None]
    mostly_blind = len(unanswered) >= max(3, len(CHECKS) // 2)

    snap = {
        'generated_utc': NOW.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'gsc_window_end': GSC_END.isoformat(),
        'all_clear': not high and not unanswered,
        'unanswered_questions': [f['id'] for f in unanswered],
        'counts': {s: sum(1 for f in findings if f['severity'] == s)
                   for s in ('high', 'medium', 'low')},
        'alert': {
            'firing': bool(st['new'] or st['escalated'] or st['due_reminder']),
            'new': [f['id'] for f in st['new']],
            'escalated': [f['id'] for f in st['escalated']],
            'weekly_reminder': [f['id'] for f in st['due_reminder']],
            'persisting_silently': [f['id'] for f in st['persisting']
                                    if f not in st['due_reminder']],
            'resolved_since_last_run': st['resolved'],
            'policy': ('Mail fires on NEW, ESCALATED, or once every %d days while a HIGH stays open. Persisting findings remain in this file and remain binding on pce-operating-loop STEP 0A-bis; they simply stop re-mailing daily, because an alert that arrives every morning stops being read.' % REMIND_AFTER_DAYS),
        },
        'findings': findings,
        'note': ('The self-questioning layer. Every other guard in this repo checks '
                 'something a human once thought to ask about; this one asks the same %d '
                 'open questions every day and answers them from live data, so a problem '
                 'nobody anticipated still surfaces. Runs on GitHub Actions so it survives '
                 'an Anthropic-side outage. Any HIGH finding exits 1 -> the workflow fails '
                 '-> GitHub emails the owner. A check that cannot reach its data reports '
                 'answer=null and says so; it is never silently counted as healthy.'
                 % len(CHECKS)),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(snap, indent=1) + '\n')

    print('ANOMALY WATCH  %s   (GSC window ends %s)'
          % (snap['generated_utc'], snap['gsc_window_end']))
    print('=' * 78)
    for f in findings:
        print('[%-6s] %s' % (f['severity'].upper(), f['id']))
        print('   Q: %s' % f['question'])
        print('   A: %s' % (f['answer'] if f['answer'] is not None else
                            'NO ANSWER -- %s' % f.get('error', 'data unavailable')))
        for p in f.get('pages', [])[:6]:
            print('      - %-46s %5d impr  pos %4.1f  %5.2f%% vs %4.2f%% expected (%.0f%%)'
                  % (p['page'], p['impressions'], p['avg_position'],
                     p['actual_ctr_pct'], p['expected_ctr_pct'],
                     p['ratio_of_expected'] * 100))
        print('')
    print('=' * 78)
    print('high=%d  medium=%d  low=%d  unanswered=%d   -> %s'
          % (snap['counts']['high'], snap['counts']['medium'], snap['counts']['low'],
             len(unanswered), 'wrote ' + OUT))
    firing = st['new'] or st['escalated'] or st['due_reminder']
    if st['resolved']:
        print('RESOLVED since last run: %s' % ', '.join(st['resolved']))
    if firing:
        for f in st['new'] + st['escalated'] + st['due_reminder']:
            f['last_alerted_utc'] = snap['generated_utc']
        io.open(OUT, 'w', encoding='utf-8').write(json.dumps(snap, indent=1) + chr(10))
        bits = []
        if st['new']:
            bits.append('NEW: ' + ', '.join(f['id'] for f in st['new']))
        if st['escalated']:
            bits.append('WORSE: ' + ', '.join(f['id'] for f in st['escalated']))
        if st['due_reminder']:
            bits.append('STILL OPEN after %dd: %s' % (REMIND_AFTER_DAYS, ', '.join(f['id'] for f in st['due_reminder'])))
        print('ANOMALY ALERT -- ' + ' | '.join(bits), file=sys.stderr)
        return 1
    if high:
        print('%d high-severity finding(s) still open (%s) -- no mail sent: unchanged since the last alert. They stay binding on the operating loop; next reminder in <=%d days.' % (len(high), ', '.join(f['id'] for f in high), REMIND_AFTER_DAYS))
    if mostly_blind:
        print('\nANOMALY WATCH IS BLIND: %d of %d questions could not be answered (%s). '
              'Reporting this as a failure on purpose -- a watchdog that cannot see must '
              'not look like a healthy day.'
              % (len(unanswered), len(CHECKS), ', '.join(f['id'] for f in unanswered)),
              file=sys.stderr)
        return 1
    if not high:
        print('no high-severity anomalies')
    return 0


if __name__ == '__main__':
    sys.exit(main())

# ---------------------------------------------------------------------------
# THRESHOLD TUNING NOTES (2026-08-13, against real data)
#
# A detector that cries wolf is worse than none, so every number above was set
# by running the checks against the live site and asking "would this fire on
# normal variation?".
#
#  * GEO_MIN_SHARE 12% + GEO_MIN_SESSIONS 30 + 25-point deviation: on today's
#    data the US (34.5% share, 40.4% engagement, 10 points off) does NOT fire,
#    and Singapore (-45 points off, but only 6.3% share / 18 sessions) does NOT
#    fire. Only the actual bot country clears all three bars. Dropping the share
#    bar to 5% would have fired on Singapore, Germany and Luxembourg -- noise.
#
#  * CTR is measured on the PAGE dimension, not the query dimension. GSC
#    anonymises rare queries: on 28d the query dimension held 12,976 of 27,473
#    impressions (47%) but only 6 of 113 clicks, which would have understated
#    CTR by ~9x and produced a spectacular false alarm. Page rows carry 27,910
#    impressions and 115 clicks -- effectively complete.
#
#  * CTR_RATIO_ALERT 0.40 with a 300-impression / 3-expected-click floor: the
#    floor is what stops a page sitting at position 45 with 40 impressions and
#    0 clicks from being "0% of expected" every single day.
#
#  * JUNK_SHARE_ALERT 25%: today's overall junk share is 22.1%, deliberately
#    just UNDER the bar -- the overall number is not yet the problem. The real
#    signal is junk concentrated in positions 1-10 (37.1%), which gets its own
#    threshold at 30% (medium) / 50% (high). Junk is a contributing explanation
#    for the CTR finding, not an independent emergency, so it is capped at
#    medium unless it passes half of all top-10 impressions.
#
#  * PLATEAU_FLAT_PCT 8%: organic weeks ran 41 -> 54 -> 55 -> 55. A stricter 0%
#    bar would miss the 54->55 step; a looser 20% would call genuine growth a
#    plateau.
#
#  * FUNNEL_MIN_CONVERSION 20%: on 28d live data the real ladder is
#    begin_checkout 316 users -> step_completed 32 -> view_item 31 ->
#    generate_lead 22 -> purchase 0. The only hop under 20% is the first one
#    (10.1%), which is precisely the defect: 90% of the people who open the
#    calculator never advance a step. view_item->generate_lead at 71% and
#    step_completed->view_item at 97% stay quiet, so the bar is not a blanket
#    alarm on a small funnel -- it isolates the one hop that is actually broken.
#    FUNNEL_MIN_TOP 10 downgrades the verdict to medium on a week too thin to
#    judge, so a quiet holiday week cannot manufacture a HIGH.
#
#  * BOT_LEAD_SHARE_ALERT 50%: today the share is 88.5% (23 of 26 leads from one
#    fleet). Any bar between ~30% and ~85% fires on this data; 50% is chosen
#    because "the majority of our customers are not people" is the point at
#    which the KPI stops being usable at all, which is the actual claim being
#    made. STRICT_LEAD_SILENCE_DAYS 7 matches the drip cadence -- the last
#    genuine capture was 2026-08-01, twelve days before this check existed.
#
#  * BOT_UA_MIN_IPS lives in metrics.py (5) so the de-botting has ONE definition
#    shared by the KPI and the watchdog. A watchdog using a different rule than
#    the metric it audits will eventually disagree with it and be believed less.
# ---------------------------------------------------------------------------

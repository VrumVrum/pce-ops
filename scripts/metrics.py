# -*- coding: utf-8 -*-
"""
DESKTOP metrics snapshot — un-blinds the cloud loop.

The cloud loop CANNOT reach production/Supabase/GA4 (sandbox 403). It only sees
what is committed to the repo. This script (run on the desktop, which CAN reach
them) pulls the REAL numbers and commits them to docs/OS/ledger/METRICS.json so
the loop reads ground truth instead of failing live pulls every cycle.

Run: python automation/_metrics_snapshot.py   (scheduled every ~12h on the desktop)
Reads Supabase creds from .env.vercel (produced by `vercel env pull`).
"""
import json, io, os, re, urllib.request, subprocess, datetime

ROOT = os.environ.get('OPS_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV = os.environ.get('ENV_FILE', os.path.join(ROOT, '.env.vercel'))
GSC = os.environ.get('GSC_OUT', os.path.join(ROOT, '_gsc_dump.json'))
OUT = os.environ.get('METRICS_OUT', os.path.join(ROOT, 'docs', 'OS', 'ledger', 'METRICS.json'))

# system-bookkeeping contexts that are NOT real human leads
NON_LEAD = {'sys:lastrun', 'unsub'}
DRIP = re.compile(r'^drip:')

# Owner/agent test rows never count as leads (F18 — 14 test rows polluted the
# human-lead count until the 2026-08-08 purge).
# Known non-customers, permanently excluded from every lead count (F18).
# 2026-08-14: the owner identified the last two 'real' leads in the database as
# friends who tried the site. That took the all-time genuine-lead count from 3 to
# ZERO. Their rows were deleted, but the pattern stays here so a re-submission or a
# restored backup can never re-inflate the number: the counter's job is to be true,
# not to be comforting. Add to this list whenever a non-customer is identified.
TEST_EMAIL = re.compile(
    r'florin\.florea84|\+(test|apilive|probe)@'
    r'|^luc328371@gmail\.com$|^john_mamutel@yahoo\.com$', re.I)

# Gmail dot-alias spam (2026-08-19). Gmail ignores dots, so one mailbox can mint
# unlimited unique-looking addresses: t.hea.k.i.r.a.ti@, b.ill..c.l.em.e.nt.sc.lan@,
# ja.c.k.s.onjhar.t15@ — eight of these signed up for free API keys in four days
# and every one landed in the lead count the owner reads. The source hole is now
# closed in /api/keys and /api/email-capture, but the counter must be able to
# reject the shape on its own: a restored backup or a new vector must never
# re-inflate the number. Four+ dots (or any '..', which Gmail does not even
# accept) in a gmail local part is a generated alias, not a person who typed
# their own address.
SPAM_ALIAS = re.compile(r'^(?=[^@]*\.[^@]*\.[^@]*\.[^@]*\.)[^@]+@(gmail|googlemail)\.com$'
                        r'|^[^@]*\.\.[^@]*@(gmail|googlemail)\.com$', re.I)


def is_junk_lead(email: str) -> bool:
    """True for a row that must never count as a lead (test, friend, or spam alias)."""
    e = email or ''
    return bool(TEST_EMAIL.search(e) or SPAM_ALIAS.match(e))

# --- bot-fleet fingerprint (F30, 2026-08-13) --------------------------------
# Every `leads` row carries the submitter's user_agent AND ip_hash, in the same
# row, and `real_human_leads` looked at NEITHER: it filtered on context name and
# a test-email regex only. The result was a headline KPI of "26 real human
# leads" of which 23 came from ONE byte-identical user_agent seen across 45
# distinct ip_hash values — a single bot fleet — leaving 3 genuine captures.
# The fleet was invisible for weeks and the system even ran a three-fire
# investigation into why the number was STUCK at 26, never asking whether the
# 26 were people.
#
# Threshold: a user_agent shared across >= 5 distinct ip_hash values is a fleet,
# not a person. Measured on live data 2026-08-13: the fleet spans 45 IPs, the
# busiest genuine user_agent spans 2 (3 across the two iPhone UA variants). The
# bar sits an order of magnitude away from both sides, so it is not a knife edge.
#
# `real_human_leads` is NEVER overwritten by this — a metric that silently
# changes meaning is its own failure mode. Both numbers are emitted side by side
# with the bot share between them, and the ledger has to state which it means.
BOT_UA_MIN_IPS = 5


def is_lead_context(ctx):
    """True for contexts that represent a person leaving an email."""
    ctx = ctx or '?'
    return ctx not in NON_LEAD and not DRIP.match(ctx) and ctx != 'api_key'


def bot_user_agents(rows, min_ips=BOT_UA_MIN_IPS):
    """{user_agent: distinct_ip_count} for UAs spanning >= min_ips ip_hash values.

    Only non-null ip_hash values count. A NULL ip is not evidence of a new
    device, and treating it as one would invent a fleet out of missing data.
    The map is built from ALL rows (including drip/system contexts) because a
    fleet that also touched a non-lead endpoint is still the same fleet.
    """
    from collections import defaultdict
    seen = defaultdict(set)
    for x in rows:
        if x.get('ip_hash'):
            seen[x.get('user_agent') or ''].add(x['ip_hash'])
    return {ua: len(ips) for ua, ips in seen.items() if len(ips) >= min_ips}


def split_human_leads(rows, min_ips=BOT_UA_MIN_IPS):
    """(human_rows, strict_rows, fleets) — shared with scripts/anomaly_watch.py.

    `human_rows` is the OLD definition (context filter only). `strict_rows` is
    the same set minus every row submitted by a bot-fleet user_agent.
    """
    fleets = bot_user_agents(rows, min_ips)
    human = [x for x in rows if is_lead_context(x.get('context'))]
    strict = [x for x in human if (x.get('user_agent') or '') not in fleets]
    return human, strict, fleets

# Affiliate /go/[slug] clicks live in provider_clicks against 4 SYSTEM provider
# rows (no DDL access — see scopebit src/lib/affiliateLane.ts, checked-in truth,
# ids stable in production). usageLane.ts system rows (__api_usage__/__embed_usage__)
# are distribution events, NOT affiliate clicks — excluded by the id filter.
AFFILIATE_PROVIDER_IDS = {
    'a7255fb7-cb58-4b8c-a5f3-ff6eaa04967d': 'fiverr',
    'fb5103d9-4583-4bdc-a318-e1dde707280d': 'hostinger',
    '3f81c793-e1b3-4d00-aae0-12724cdac3db': 'wix',
    '0a66e383-7088-42d1-ada9-d26502bd34b2': 'shopify',
}

# The site's llms.txt designated citation pages (/api/cost-data excluded — no GSC
# footprint). If any drops under 10 impressions/28d the AI-citation funnel is
# decaying and the loop must react (audit 08-06 tripwire).
CITATION_PAGES = ['/website-costs-2026-report', '/website-cost', '/cost-index',
                  '/rate-database', '/website-cost-calculator', '/freelance-website-cost']


def env(*names):
    for n in names:                      # Actions: secrets injected as env vars
        if os.environ.get(n):
            return os.environ[n]
    if not os.path.exists(ENV):
        return None
    t = io.open(ENV, encoding='utf-8', errors='ignore').read()
    for n in names:
        m = re.search(rf'^{n}=(.+)$', t, re.M)
        if m:
            return m.group(1).strip().strip('"')
    return None


def sb_get(url, key, prefer=None):
    req = urllib.request.Request(url, headers={
        'apikey': key, 'Authorization': f'Bearer {key}',
        **({'Prefer': prefer} if prefer else {})})
    r = urllib.request.urlopen(req, timeout=25)
    return r, r.read()


def supabase():
    url = env('SUPABASE_URL', 'NEXT_PUBLIC_SUPABASE_URL')
    key = env('SUPABASE_SERVICE_ROLE', 'SERVICE_ROLE_KEY', 'SUPABASE_SERVICE_ROLE_KEY')
    if not url or not key:
        return {'error': 'no supabase creds in .env.vercel'}
    out = {}
    # total leads
    r, _ = sb_get(f'{url}/rest/v1/leads?select=count', key, 'count=exact')
    out['leads_total'] = int(r.headers.get('content-range', '/0').split('/')[-1])
    # by context — user_agent and ip_hash come along now, because the bot-fleet
    # test below needs them and they were sitting in the same row all along.
    _, body = sb_get(f'{url}/rest/v1/leads'
                     f'?select=created_at,context,email,user_agent,ip_hash'
                     f'&order=created_at.desc&limit=5000', key)
    rows = json.loads(body)
    from collections import Counter
    rows = [x for x in rows if not is_junk_lead(x.get('email'))]
    c = Counter((x.get('context') or '?') for x in rows)
    out['leads_by_context'] = dict(c)
    out['real_human_leads'] = sum(v for k, v in c.items()
                                  if k not in NON_LEAD and not DRIP.match(k) and k != 'api_key')
    out['api_keys'] = c.get('api_key', 0)

    # --- strict human leads: the same set, minus the bot fleet (F30) --------
    # real_human_leads above is left EXACTLY as it was. It is now knowingly a
    # gross number; the net is beside it and the share between them says how
    # much of the headline was never a person.
    try:
        human, strict, fleets = split_human_leads(rows)
        bot_leads = len(human) - len(strict)
        out['real_human_leads_strict'] = len(strict)
        out['bot_lead_share'] = round(bot_leads / max(len(human), 1) * 100, 1)
        out['bot_leads'] = bot_leads
        out['last_strict_human_lead_utc'] = (strict[0]['created_at'][:19] if strict else None)
        for days, key_ in ((7, 'real_human_leads_strict_7d'), (28, 'real_human_leads_strict_28d')):
            cut = (datetime.datetime.now(datetime.timezone.utc)
                   - datetime.timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S')
            out[key_] = sum(1 for x in strict if (x.get('created_at') or '') >= cut)
        out['bot_lead_fleets'] = [
            {'distinct_ip_hashes': n,
             'lead_rows': sum(1 for x in human if (x.get('user_agent') or '') == ua),
             'rows_all_contexts': sum(1 for x in rows if (x.get('user_agent') or '') == ua),
             'user_agent': (ua or '(empty)')[:160]}
            for ua, n in sorted(fleets.items(), key=lambda kv: -kv[1])]
        out['real_human_leads_note'] = (
            'real_human_leads (%d) is the ORIGINAL field and still counts every '
            'lead-context row regardless of who sent it. real_human_leads_strict '
            '(%d) additionally drops every row whose user_agent is shared across '
            '>=%d distinct ip_hash values, i.e. a bot fleet. %s%% of the headline '
            'was that fleet. Quote the strict number as the conversion KPI; the '
            'gross number is kept only so the two can be compared over time.'
            % (out['real_human_leads'], out['real_human_leads_strict'],
               BOT_UA_MIN_IPS, out['bot_lead_share']))
    except Exception as e:
        # Honest null (§3): a failed de-botting must never look like a clean run.
        out['real_human_leads_strict'] = None
        out['bot_lead_share'] = None
        out['last_strict_human_lead_utc'] = None
        out['real_human_leads_note'] = 'strict de-botting FAILED: %s' % str(e)[:200]
    # build-intent leads: the R2 tripwire counts contexts ending ':build'
    # (active-buyer checkbox, live since 2026-08-10) — test rows already excluded
    out['build_intent_count'] = sum(v for k, v in c.items() if k.endswith(':build'))
    # drip funnel visibility: how many leads sit at each drip:N stage
    out['drip_stages'] = {k: v for k, v in sorted(c.items()) if DRIP.match(k)}
    # affiliate /go/[slug] clicks (same REST pattern; human-only per is_bot flag
    # the /go route stamps on every insert — same filter affiliate-stats uses)
    try:
        ids = ','.join(AFFILIATE_PROVIDER_IDS)
        _, body = sb_get(
            f'{url}/rest/v1/provider_clicks'
            f'?select=provider_id,user_inputs,created_at,user_agent,user_ip_hash'
            f'&provider_id=in.({ids})&order=created_at.desc&limit=10000', key)
        raw = json.loads(body)
        clicks = [x for x in raw
                  if not (x.get('user_inputs') or {}).get('is_bot')]
        # Second layer: a self-declaring non-browser user_agent is a click by
        # nothing. The /go route's is_bot flag catches these today, but it is one
        # regex on one code path — if it ever regresses, the KPI must not quietly
        # absorb curl and aiohttp as customers again.
        UA_BOT = re.compile(r'curl/|wget|python|aiohttp|httpx|okhttp|go-http|java/|libwww|'
                            r'bot|spider|crawler|headless|scrapy|axios|node-fetch', re.I)
        residual = [x for x in clicks if UA_BOT.search(x.get('user_agent') or '')]
        cutoff7 = (datetime.datetime.now(datetime.timezone.utc)
                   .replace(tzinfo=None) - datetime.timedelta(days=7)).isoformat()
        by_slug = {}
        for x in clicks:
            slug = ((x.get('user_inputs') or {}).get('slug')
                    or AFFILIATE_PROVIDER_IDS.get(x.get('provider_id'), '?'))
            by_slug[slug] = by_slug.get(slug, 0) + 1
        with_ip = sum(1 for x in raw if x.get('user_ip_hash'))
        out['affiliate_clicks'] = {
            'total': len(clicks),
            'last7d': sum(1 for x in clicks
                          if (x.get('created_at') or '') >= cutoff7),
            'by_slug': dict(sorted(by_slug.items(),
                                   key=lambda kv: -kv[1])),
            'rows_before_bot_filter': len(raw),
            'excluded_by_is_bot_flag': len(raw) - len(clicks),
            'residual_bot_ua_after_filter': len(residual),
            'distinct_ip_hashes': (None if not with_ip else
                                   len({x['user_ip_hash'] for x in raw if x.get('user_ip_hash')})),
            'ip_hash_coverage_pct': round(with_ip / max(len(raw), 1) * 100, 1),
            'note': (
                'user_ip_hash is NULL on %d of %d rows (%.0f%% coverage), so these '
                'clicks CANNOT be de-duplicated per visitor: "total" is click '
                'events, never unique people, and no unique-clicker number can '
                'honestly be derived until the /go route starts stamping the hash. '
                'is_bot excluded %d row(s); %d row(s) still carry a non-browser '
                'user_agent after that filter.'
                % (len(raw) - with_ip, len(raw),
                   with_ip / max(len(raw), 1) * 100,
                   len(raw) - len(clicks), len(residual))),
        }
    except Exception as e:
        out['affiliate_clicks'] = {'error': str(e)[:200]}
    # sales
    try:
        r, _ = sb_get(f'{url}/rest/v1/sales?select=count', key, 'count=exact')
        out['sales_total'] = int(r.headers.get('content-range', '/0').split('/')[-1])
    except Exception:
        out['sales_total'] = 0
    return out


def detect_junk(queries):
    """AI-fanout junk detector (KPIS.md 'junk impressions' — nemin.io / vercel /
    freelance-rate permutation clusters). Five signatures, all requiring 0 clicks:
    (1) >=3 queries whose word SETS are identical (pure word-order permutations);
    (2) queries containing quoted strings ("december 2021"-style scraper probes);
    (3) competitor-brand suffix ('… on nemin io' — 820 imps, audit 08-06);
    (4) dual-year ('… 2025 2026 hourly');
    (5) 'official' + year ('official 2026 …').
    Returns (junk_impressions, junk_query_count, sample)."""
    from collections import defaultdict
    FANOUT = (re.compile(r'\bon [a-z0-9-]+ ?(io|com|net|app)\b'),
              re.compile(r'\b20\d\d 20\d\d\b'),
              re.compile(r'\bofficial 20\d\d\b'))
    groups = defaultdict(list)
    quoted = []
    fanout = []
    for q in queries or []:
        text = (q.get('keys') or [q.get('query', '')])[0]
        clicks = q.get('clicks', 0)
        if clicks:
            continue
        if '"' in text:
            quoted.append(q)
            continue
        if any(p.search(text.lower()) for p in FANOUT):
            fanout.append(q)
            continue
        # Normalize so permutation-variants collapse to one signature:
        # drop digits/years, singularize, drop glue words.
        STOP = {'a', 'the', 'in', 'for', 'per', 'to', 'of', 'and', 'or',
                'how', 'much', 'does', 'what', 'is', 'are', 'on', 'an', 'my'}
        words = []
        for w in text.lower().split():
            w = ''.join(c for c in w if not c.isdigit())
            w = w.rstrip('s') if len(w) > 3 else w
            if w and w not in STOP:
                words.append(w)
        groups[frozenset(words)].append(q)
    junk = quoted + fanout
    for members in groups.values():
        if len(members) >= 4:
            junk.extend(members)
    impr = sum(q.get('impressions', 0) for q in junk)
    sample = [(q.get('keys') or [q.get('query', '')])[0] for q in junk[:3]]
    return impr, len(junk), sample


def gsc():
    if not os.path.exists(GSC):
        return {'error': 'no _gsc_dump.json'}
    d = json.load(io.open(GSC, encoding='utf-8'))
    out = {'generated': d.get('generated'),
           'totals_28d': d.get('totals_28d'),
           'totals_7d': d.get('totals_7d'),
           'totals_90d': d.get('totals_90d')}
    # Clean totals: junk carries 0 clicks, so only impressions/CTR change.
    # Position is left as-is (recomputing it without per-query weighting would lie).
    try:
        impr, n, sample = detect_junk(d.get('queries_28d'))
        t = d.get('totals_28d') or {}
        clean_impr = max((t.get('impressions') or 0) - impr, 1)
        out['junk_28d'] = {'impressions': impr, 'queries': n, 'sample': sample}
        out['totals_28d_clean'] = {
            'clicks': t.get('clicks'),
            'impressions': clean_impr,
            'ctr': round((t.get('clicks') or 0) / clean_impr * 100, 3),
        }
    except Exception as e:
        out['junk_28d'] = {'error': str(e)}
    # Citation-floor tripwire: exact-path impressions for every llms.txt
    # citation page; empty list = healthy.
    try:
        by_path = {}
        for p in d.get('pages_28d') or []:
            path = (p.get('page') or '').replace('https://projectcostestimator.com', '').rstrip('/') or '/'
            by_path[path] = by_path.get(path, 0) + (p.get('impressions') or 0)
        out['citation_floor_alerts'] = [
            {'page': pg, 'impressions': by_path.get(pg, 0)}
            for pg in CITATION_PAGES if by_path.get(pg, 0) < 10]
    except Exception as e:
        out['citation_floor_alerts'] = {'error': str(e)}
    return out


def shipped_asset_performance():
    """Per-asset GSC performance for everything the loop has shipped.

    The cloud loop cannot pull GSC, so it could never verify its own experiments —
    a 13-item verification debt built up before the 2026-07-29 desktop batch.
    This puts the per-asset numbers in the repo so the loop can self-score.
    """
    if not os.path.exists(GSC):
        return {'error': 'no _gsc_dump.json'}
    d = json.load(io.open(GSC, encoding='utf-8'))
    pages = d.get('pages_28d', []) or []
    tracked = ['/tools/rfp-generator', '/tools/freelancer-quote-generator',
               '/tools/fixed-price-vs-time-and-materials', '/cost/ai/', '/cost/hire/',
               '/cost/app-like/', '/cost/industry/', '/software-development-budget-2027',
               '/freelance-website-cost', '/restaurant-website-cost', '/nonprofit-website-cost']
    out = {}
    for t in tracked:
        hits = [p for p in pages if t in (p.get('page') or '')]
        out[t] = {'pages_with_data': len(hits),
                  'impressions': sum(p.get('impressions', 0) for p in hits),
                  'clicks': sum(p.get('clicks', 0) for p in hits)}
    return out


def main():
    # NOTE: argless datetime.now() is fine on the desktop (this is not a workflow script)
    snap = {
        'generated_utc': datetime.datetime.utcnow().isoformat() + 'Z',
        'note': 'REAL numbers pulled by the desktop for the blind cloud loop. See docs/OS/ledger/KPIS.md for interpretation.',
        'gsc': gsc(),
        'supabase': supabase(),
        'shipped_asset_performance': shipped_asset_performance(),
    }
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(snap, indent=2) + '\n')
    print('wrote', OUT)
    print(json.dumps(snap, indent=2)[:600])


if __name__ == '__main__':
    main()

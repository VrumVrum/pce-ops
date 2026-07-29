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
    # by context (all rows, context only)
    _, body = sb_get(f'{url}/rest/v1/leads?select=context&limit=2000', key)
    rows = json.loads(body)
    from collections import Counter
    c = Counter((x.get('context') or '?') for x in rows)
    out['leads_by_context'] = dict(c)
    out['real_human_leads'] = sum(v for k, v in c.items()
                                  if k not in NON_LEAD and not DRIP.match(k) and k != 'api_key')
    out['api_keys'] = c.get('api_key', 0)
    # sales
    try:
        r, _ = sb_get(f'{url}/rest/v1/sales?select=count', key, 'count=exact')
        out['sales_total'] = int(r.headers.get('content-range', '/0').split('/')[-1])
    except Exception:
        out['sales_total'] = 0
    return out


def gsc():
    if not os.path.exists(GSC):
        return {'error': 'no _gsc_dump.json'}
    d = json.load(io.open(GSC, encoding='utf-8'))
    return {'generated': d.get('generated'),
            'totals_28d': d.get('totals_28d'),
            'totals_7d': d.get('totals_7d'),
            'totals_90d': d.get('totals_90d')}


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

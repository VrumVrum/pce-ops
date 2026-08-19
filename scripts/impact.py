# -*- coding: utf-8 -*-
"""
Impact.com partner API pull — the affiliate money the rest of the system is blind to.

WHY: `provider_clicks` in Supabase counts clicks LEAVING our site; whether any of
them ever earned a cent lives only in Impact's dashboard. The morning report's
"Bani" section had to say so explicitly. This closes that: approved programs,
their contract status, and real conversions/commission come back as data the
loop and the report can read.

It also watches for APPROVALS. `src/lib/partners.ts` carries `affiliateUrl: null`
for programs not yet approved (Wix today) — when Impact flips one to Active, the
tracking link exists and the site is still sending untracked traffic. This
surfaces that within a day instead of whenever someone remembers to check.

Auth: HTTP Basic, AccountSID as user + AuthToken as password (Impact's own
scheme). Both from env — never in code, never logged.
Output: data/IMPACT.json. No creds -> coverage "not_measured" with the reason;
an API error is never written as "0 earned" (a blind read must not read as a
healthy zero — the F29 discipline).
"""
import base64
import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://api.impact.com'
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'data', 'IMPACT.json')
SID = os.environ.get('IMPACT_ACCOUNT_SID', '').strip()
TOKEN = os.environ.get('IMPACT_AUTH_TOKEN', '').strip()


def call(path, **params):
    url = f'{BASE}/Mediapartners/{SID}{path}'
    if params:
        url += '?' + urllib.parse.urlencode(params)
    auth = base64.b64encode(f'{SID}:{TOKEN}'.encode()).decode()
    req = urllib.request.Request(url, headers={
        'Authorization': f'Basic {auth}',
        'Accept': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)


def main():
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    if not (SID and TOKEN):
        json.dump({'generated_utc': stamp, 'coverage': 'not_measured',
                   'reason': 'IMPACT_ACCOUNT_SID / IMPACT_AUTH_TOKEN not set'},
                  open(OUT, 'w', encoding='utf-8'), indent=1)
        print('BLIND: no Impact credentials — wrote not_measured, exiting 2', file=sys.stderr)
        return 2

    out = {'generated_utc': stamp, 'coverage': 'measured'}
    try:
        acct = call('')
        out['account'] = {k: acct.get(k) for k in ('Id', 'Name', 'Status', 'Currency')}

        camps = call('/Campaigns', PageSize=100).get('Campaigns', []) or []
        programs = []
        for c in camps:
            programs.append({
                'name': c.get('CampaignName'),
                'id': c.get('CampaignId'),
                'status': c.get('ContractStatus') or c.get('Status'),
                'tracking_link': c.get('TrackingLink'),
            })
        out['programs'] = programs
        out['programs_active'] = [p['name'] for p in programs
                                  if str(p.get('status', '')).lower() == 'active']

        # All-time conversions. NO date parameters on purpose: Impact rejects any
        # StartDate/EndDate pair more than 45 days apart ("Number of days between
        # them cannot be more than 45 days"), and the un-dated call returns the
        # full history in one page. Learned the hard way — the first version
        # passed a 4-month window, got an error body back, and the parser read
        # its missing 'Actions' key as "0 conversions". A failed call must never
        # render as a healthy zero, which is why every failure path below writes
        # coverage=not_measured instead of a number.
        acts = call('/Actions')
        rows = acts.get('Actions', []) or []
        total_payout = 0.0
        by_program = {}
        for a in rows:
            try:
                p = float(a.get('Payout') or 0)
            except (TypeError, ValueError):
                p = 0.0
            total_payout += p
            name = a.get('CampaignName') or '?'
            by_program[name] = round(by_program.get(name, 0.0) + p, 2)
        out['conversions'] = {
            'count': int(acts.get('@total', len(rows))),
            'total_payout': round(total_payout, 2),
            'currency': acct.get('Currency'),
            'by_program': by_program,
            'window': 'all time (Impact caps dated queries at 45 days; undated returns full history)',
        }
    except urllib.error.HTTPError as e:
        json.dump({'generated_utc': stamp, 'coverage': 'not_measured',
                   'reason': f'HTTP {e.code} from Impact API'},
                  open(OUT, 'w', encoding='utf-8'), indent=1)
        print(f'BLIND: Impact API returned HTTP {e.code}', file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 — any failure must read as blind, not zero
        json.dump({'generated_utc': stamp, 'coverage': 'not_measured',
                   'reason': str(e)[:200]},
                  open(OUT, 'w', encoding='utf-8'), indent=1)
        print(f'BLIND: {e}', file=sys.stderr)
        return 2

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=1)
        f.write('\n')

    print(f"programs: {len(out['programs'])} "
          f"(active: {', '.join(out['programs_active']) or 'none'}) | "
          f"conversions: {out['conversions']['count']} | "
          f"earned: {out['conversions']['total_payout']} {out['conversions']['currency']}")
    for p in out['programs']:
        print(f"  {p['name']}: {p['status']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

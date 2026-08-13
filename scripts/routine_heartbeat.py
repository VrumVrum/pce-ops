# -*- coding: utf-8 -*-
"""
Routine heartbeat — the guard for FAILURE CLASS F29 (silent fleet death).

WHY THIS LIVES IN pce-ops AND NOT IN A ROUTINE PROMPT
-----------------------------------------------------
On 2026-08-12/13 the Anthropic subscription lapsed. Every cloud routine kept
firing on schedule, spun up its sandbox, cloned the repo — and then died in
~14 seconds on `403 authentication_failed` ("organization has disabled Claude
subscription access"), before writing a single byte. Nothing alerted:

  * SCORECARD.json counts report HEADERS, so a run that dies before reporting
    is invisible to it BY DESIGN (F10 honest-nulls rule).
  * pce-supervisor is itself a routine — it was dead too.
  * The owner found out by noticing the silence, ~2 days later.

Any watchdog that runs ON the Anthropic platform shares the failure it is
supposed to detect. This script runs on GitHub Actions, which kept running
perfectly through the entire outage — so it can see what the fleet cannot see
about itself.

ALERT CHANNEL: when a routine is silent past its threshold this script exits 1.
A failed GitHub Actions run emails the repo owner. That mail path does not
depend on Anthropic being up, which is the whole point.

Honest-nulls (§3): a routine with no parsable report is reported as
last_report_utc=None + silent=true. Nothing is estimated or back-filled.

Output: data/ROUTINE-HEARTBEAT.json
Requires: GH_PAT (read access to the private VrumVrum/scopebit).
"""
import json, os, re, sys, urllib.request, urllib.error, datetime

PAT = os.environ.get('GH_PAT')
REPO = 'VrumVrum/scopebit'
RAW = f'https://raw.githubusercontent.com/{REPO}/master'
API_COMMITS = f'https://api.github.com/repos/{REPO}/commits'
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'data', 'ROUTINE-HEARTBEAT.json')

# Alert threshold per routine, in hours. Deliberately ~2.2x the scheduled
# interval so one skipped fire is never an alarm — only a real stall is.
# (cron shown for review against docs/OS/TRIGGERS.md)
ROUTINES = {
    # 26h, not 30h. The blackout this guard was built for reached 29.7h before the
    # OWNER caught it, and a 30h bar would have sat 0.3h under it — the guard would
    # have missed the exact incident that motivated it. 26h still tolerates one
    # missed fire (a 12-24h gap) and trips on two consecutive misses, which is the
    # real signal. Caught by the OS audit, 2026-08-13; thresholds set by intuition
    # rather than against the incident they must catch is its own failure mode.
    'pce-operating-loop':    {'cron': '23 */12 * * *',  'every_h': 12,  'alert_h': 26},
    'pce-supervisor':        {'cron': '0 3 * * *',      'every_h': 24,  'alert_h': 54},
    'pce-content-engine':    {'cron': '20 8 * * *',     'every_h': 24,  'alert_h': 54},
    # RETIRED 2026-08-13 (0 product output in 30 days) — kept in the roster because
    # each still files a minimal report; a silent retired routine would look like a
    # dead one. Remove the row entirely once its trigger is disabled.
    'pce-authority-traffic': {'cron': '0 13 */2 * *',   'every_h': 48,  'alert_h': 108},
    # RETIRED 2026-08-13 (0 product output in 30 days) — kept in the roster because
    # each still files a minimal report; a silent retired routine would look like a
    # dead one. Remove the row entirely once its trigger is disabled.
    'pce-morning-brief':     {'cron': '30 5 * * 1,4',   'every_h': 96,  'alert_h': 192},
    'pce-revenue-executor':  {'cron': '0 9 * * 1,4',    'every_h': 96,  'alert_h': 192},
    'pce-deep-verify':       {'cron': '0 4 * * 3,6',    'every_h': 96,  'alert_h': 192},
    # RETIRED 2026-08-13 (0 product output in 30 days) — kept in the roster because
    # each still files a minimal report; a silent retired routine would look like a
    # dead one. Remove the row entirely once its trigger is disabled.
    'pce-keyword-scout':     {'cron': '40 6 * * 2',     'every_h': 168, 'alert_h': 204},
    'pce-seo-audit':         {'cron': '0 5 * * 1',      'every_h': 168, 'alert_h': 204},
}
# Some routines commit under a different display name than their trigger name.
ALIASES = {'pce-revenue-executor': ['pce-money-hunt', 'revenue executor'],
           'pce-morning-brief': ['growth morning brief'],
           'pce-seo-audit': ['pce-seo-audit-3day']}

NOW = datetime.datetime.now(datetime.timezone.utc)
TS = re.compile(r'(20\d{2}-\d{2}-\d{2})[T ](\d{2}):(\d{2})')


def norm(s):
    """Fold hyphen/underscore/space so 'GROWTH MORNING BRIEF' matches
    'growth-morning-brief'. Routines have historically reported under both
    spellings; matching one spelling only makes the guard cry wolf forever."""
    return re.sub(r'[-_\s]+', ' ', s.lower()).strip()


def fetch(url, accept=None):
    h = {'User-Agent': 'pce-ops-heartbeat'}
    if PAT:
        h['Authorization'] = f'token {PAT}'
    if accept:
        h['Accept'] = accept
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
            return r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def parse_dt(s):
    m = TS.search(s)
    if not m:
        return None
    try:
        return datetime.datetime(int(m.group(1)[:4]), int(m.group(1)[5:7]), int(m.group(1)[8:10]),
                                 int(m.group(2)), int(m.group(3)), tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def report_ledger():
    """Current + previous monthly report file (handles month rollover)."""
    text = ''
    for delta in (0, 1):
        y, mth = NOW.year, NOW.month - delta
        if mth <= 0:
            y, mth = y - 1, mth + 12
        body = fetch(f'{RAW}/docs/OS/ledger/routine-reports-{y}-{mth:02d}.md')
        if body:
            text += '\n' + body
    # legacy single-file ledger, still read so a rollback cannot blind the guard
    legacy = fetch(f'{RAW}/docs/OS/ledger/routine-reports.md')
    if legacy and len(legacy) > 400:      # the pointer stub is tiny; a real ledger is not
        text += '\n' + legacy
    return text


def newest_report(text, names):
    """Newest '## <routine> — <utc>' header for any of the routine's names."""
    best = None
    for line in text.splitlines():
        if not line.startswith('## '):
            continue
        low = norm(line)
        if not any(n in low for n in names):
            continue
        dt = parse_dt(line)
        if dt and (best is None or dt > best):
            best = dt
    return best


def newest_commit(commits, names):
    best = None
    for c in commits:
        msg = norm(c.get('commit', {}).get('message') or '')
        if not any(n in msg for n in names):
            continue
        dt = parse_dt(c.get('commit', {}).get('committer', {}).get('date', ''))
        if dt and (best is None or dt > best):
            best = dt
    return best


def main():
    ledger = report_ledger()
    if not ledger.strip():
        # Cannot see the ledger at all — fail loudly rather than report "all green".
        print('FATAL: no routine-reports ledger readable (GH_PAT missing or repo moved)',
              file=sys.stderr)
        json.dump({'generated_utc': NOW.strftime('%Y-%m-%dT%H:%M:%SZ'),
                   'error': 'ledger_unreadable', 'routines': {}, 'silent': ['(unknown)']},
                  open(OUT, 'w'), indent=1)
        return 1

    since = (NOW - datetime.timedelta(days=14)).strftime('%Y-%m-%dT%H:%M:%SZ')
    commits = []
    try:
        commits = json.loads(fetch(f'{API_COMMITS}?since={since}&per_page=100') or '[]')
    except Exception as e:                                   # commits are corroboration only
        print(f'warn: commit list unavailable ({e})', file=sys.stderr)

    out, silent = {}, []
    for name, cfg in ROUTINES.items():
        names = [norm(name)] + [norm(a) for a in ALIASES.get(name, [])]
        rep = newest_report(ledger, names)
        com = newest_commit(commits, names)
        last = max([d for d in (rep, com) if d], default=None)
        age = round((NOW - last).total_seconds() / 3600, 1) if last else None
        is_silent = (age is None) or (age > cfg['alert_h'])
        if is_silent:
            silent.append(name)
        out[name] = {
            'cron': cfg['cron'],
            'expected_every_h': cfg['every_h'],
            'alert_after_h': cfg['alert_h'],
            'last_report_utc': rep.strftime('%Y-%m-%dT%H:%M:%SZ') if rep else None,
            'last_commit_utc': com.strftime('%Y-%m-%dT%H:%M:%SZ') if com else None,
            'hours_since': age,
            'silent': is_silent,
        }

    snap = {
        'generated_utc': NOW.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'all_alive': not silent,
        'silent': silent,
        'routines': out,
        'note': ('Guard for F29 (silent fleet death). Runs on GitHub Actions so it survives '
                 'the Anthropic-side outage it exists to detect. A run that dies before '
                 'writing its report leaves no trace in SCORECARD.json — this file is the '
                 'only place that absence becomes visible. Exit 1 = owner email.'),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(snap, open(OUT, 'w', encoding='utf-8'), indent=1)

    for n, r in out.items():
        print(f"{'SILENT ' if r['silent'] else 'alive  '} {n:<24} "
              f"{r['hours_since']}h ago (alert >{r['alert_after_h']}h)")
    if silent:
        print(f'\nFLEET ALERT: {len(silent)} routine(s) silent past threshold: '
              f'{", ".join(silent)}', file=sys.stderr)
        print('Check the Anthropic subscription/billing first — a lapsed subscription kills '
              'every routine at once with 403 authentication_failed (F29).', file=sys.stderr)
        return 1
    print('\nall routines alive')
    return 0


if __name__ == '__main__':
    sys.exit(main())

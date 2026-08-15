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
import io, json, os, re, sys, urllib.request, urllib.error, datetime

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
    # New fleet members, created 2026-08-13 on owner order (docs/OS/TRIGGERS.md).
    # Absent from this roster until 2026-08-15 — the guard was blind to both.
    'pce-growth-engine':     {'cron': '0 6 * * *',      'every_h': 24,  'alert_h': 54},
    'pce-tech-scan':         {'cron': '0 15 * * *',     'every_h': 24,  'alert_h': 54},
    'pce-revenue-executor':  {'cron': '0 9 * * 1,4',    'every_h': 96,  'alert_h': 192},
    'pce-deep-verify':       {'cron': '0 4 * * 3,6',    'every_h': 96,  'alert_h': 192},
    'pce-seo-audit':         {'cron': '0 5 * * 1',      'every_h': 168, 'alert_h': 204},
    # pce-authority-traffic / pce-morning-brief / pce-keyword-scout: RETIRED
    # 2026-08-13 and DROPPED from this roster 2026-08-15 per the owner action
    # recorded in docs/OS/TRIGGERS.md ("disable trigger + drop from
    # routine-heartbeat roster"). Evidence at drop time: zero run-status rows,
    # zero report headers, zero commits from any of the three since the
    # retirement commit (scopebit c6a18ba, 2026-08-13T21:03Z) — their roster
    # rows read "alive" only because that OWNER commit's message name-checks
    # them (the F32 mention-vs-activity class, different authorship). Keeping
    # the rows would start mailing the owner about deliberately-retired
    # routines from ~2026-08-18 onward.
}
# Some routines commit under a different display name than their trigger name.
ALIASES = {'pce-revenue-executor': ['pce-money-hunt', 'revenue executor'],
           'pce-seo-audit': ['pce-seo-audit-3day']}

NOW = datetime.datetime.now(datetime.timezone.utc)
TS = re.compile(r'(20\d{2}-\d{2}-\d{2})[T ](\d{2}):(\d{2})')
# Date with no time-of-day. Real ledger headers ship without one — e.g.
# '## pce-seo-audit (Adversarial Recurring Audit) — 2026-08-10 (weekly Mon...'.
# Before 2026-08-15 such headers parsed as None, so a routine whose only
# recent trace was a date-only header read as never-seen ('Noneh ago') and
# false-alarmed SILENT (live instance: pce-seo-audit, run 31871189129).
DATE_ONLY = re.compile(r'(20\d{2})-(\d{2})-(\d{2})')


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
    if m:
        try:
            return datetime.datetime(int(m.group(1)[:4]), int(m.group(1)[5:7]), int(m.group(1)[8:10]),
                                     int(m.group(2)), int(m.group(3)), tzinfo=datetime.timezone.utc)
        except ValueError:
            return None
    # Date-only fallback: midnight UTC. Conservative — it makes the entry look
    # OLDER than it probably is (never fresher), so it can only delay an
    # all-clear, never fake one.
    m = DATE_ONLY.search(s)
    if not m:
        return None
    try:
        return datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                 tzinfo=datetime.timezone.utc)
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


def is_supervisor_audit_commit(raw_msg):
    """pce-supervisor's own verification-pass commits systematically name-check OTHER
    routines by way of auditing them, in the commit's own subject line — e.g.
    'filed 2 new non-severe findings (pce-content-engine stall, ...)' or
    'false-positived on pce-revenue-executor'. Bare substring matching in
    newest_commit() then misreads that MENTION as the named routine's own fresh
    activity. Caught live 2026-08-14 (pce-tech-scan 2nd fire): pce-content-engine's
    true last commit was ~72h old (2026-08-11T~08:20Z, already past its own 54h
    alert_after_h - a genuine, currently-active F29 condition, independently also
    flagged by pce-supervisor itself the same day) but the heartbeat read it as
    5.3h old because pce-supervisor's own commit happened to say 'pce-content-engine
    stall' - the exact silent-routine incident this guard exists to catch, masked by
    its own matching logic. Same class hit pce-revenue-executor's displayed
    last_commit_utc via a different pce-supervisor commit the same way.
    Scoped narrowly to the 'supervisor:' subject prefix (not a general stopword
    filter) so it does not touch pce-seo-audit's genuine self-mention ('audit:
    recurring adversarial SEO audit ... pce-seo-audit.md v1.2's first confirmed
    fire...') or any other routine's own commits - verified against 50 real commits
    spanning 2026-07-25..08-14, only the two known false positives changed."""
    first_line = raw_msg.strip().splitlines()[0] if raw_msg.strip() else ''
    m = re.match(r'\s*([a-zA-Z][a-zA-Z0-9]*)\s*:', first_line)
    return bool(m) and m.group(1).lower() == 'supervisor'


def newest_commit(commits, names, routine_key):
    best = None
    for c in commits:
        raw_msg = c.get('commit', {}).get('message') or ''
        # Don't let pce-supervisor's audit commentary about OTHER routines count as
        # those routines' own activity (see is_supervisor_audit_commit docstring).
        if routine_key != 'pce-supervisor' and is_supervisor_audit_commit(raw_msg):
            continue
        msg = norm(raw_msg)
        if not any(n in msg for n in names):
            continue
        dt = parse_dt(c.get('commit', {}).get('committer', {}).get('date', ''))
        if dt and (best is None or dt > best):
            best = dt
    return best


# Remind at most once a day while a routine stays silent. The FIRST version of this
# guard mailed on every run - every 6 hours, forever, for as long as the condition
# held. The owner got the same alert repeatedly within hours and asked why. An alert
# that arrives four times a day is deleted unread, which costs more than the guard is
# worth; the anomaly layer had already learned this and this file had not. A dead
# routine is more urgent than a slow business problem, so the reminder is 24h here
# rather than the 7 days used for anomalies.
REMIND_AFTER_H = 24


def load_prev():
    try:
        return json.loads(io.open(OUT, encoding='utf-8').read())
    except Exception:
        return {}


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
    # Commits corroborate the report ledger. If that fetch fails the guard is PARTIALLY
    # BLIND: a routine that committed but whose report header the parser missed then
    # looks dead. Observed for real - a truncated GitHub response (IncompleteRead) made
    # pce-seo-audit read as silent when it was not. Alerting on that trains the owner to
    # ignore the mail, so a blind run reports the state and withholds the alarm.
    # Paginate: a single per_page=100 call silently shrinks the "14-day" window
    # to the ~100 newest commits (3-4 days on this repo). That aged
    # pce-seo-audit's Aug-10 commits out of view between the 02:00 and 07:08
    # runs of 2026-08-15 and helped fire the false SILENT alarm.
    commits, commits_ok = [], True
    try:
        for page in range(1, 11):
            batch = json.loads(
                fetch(f'{API_COMMITS}?since={since}&per_page=100&page={page}') or '[]')
            commits.extend(batch)
            if len(batch) < 100:
                break
    except Exception as e:
        commits_ok = False
        print(f'warn: commit list unavailable ({e}) - alert withheld this run',
              file=sys.stderr)

    out, silent = {}, []
    for name, cfg in ROUTINES.items():
        names = [norm(name)] + [norm(a) for a in ALIASES.get(name, [])]
        rep = newest_report(ledger, names)
        com = newest_commit(commits, names, name)
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
    # Alert on a CHANGE of state, not on repetition of one.
    prev = load_prev()
    prev_r = prev.get('routines', {})
    new_silent, due, still = [], [], []
    for n in silent:
        was = prev_r.get(n, {})
        la = was.get('last_alerted_utc')
        if not was.get('silent'):
            new_silent.append(n)
        elif la:
            try:
                d = datetime.datetime.strptime(la, '%Y-%m-%dT%H:%M:%SZ').replace(
                    tzinfo=datetime.timezone.utc)
                (due if (NOW - d).total_seconds() / 3600 >= REMIND_AFTER_H
                 else still).append(n)
            except ValueError:
                due.append(n)
        else:
            due.append(n)
    recovered = [n for n, v in prev_r.items()
                 if v.get('silent') and not out.get(n, {}).get('silent', False)]
    firing = (new_silent + due) if commits_ok else []
    snap_blind = not commits_ok
    for n in out:
        prior = prev_r.get(n, {}).get('last_alerted_utc')
        out[n]['last_alerted_utc'] = (snap['generated_utc'] if n in firing else prior)
    snap['alert'] = {'firing': bool(firing), 'partially_blind': snap_blind,
                     'new_silent': new_silent,
                     'daily_reminder': due, 'silent_but_already_reported': still,
                     'recovered_since_last_run': recovered,
                     'policy': 'Mail fires when a routine goes silent, or once every %dh '
                               'while it stays silent. Repetition alone never mails.'
                               % REMIND_AFTER_H}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(snap, open(OUT, 'w', encoding='utf-8'), indent=1)

    for n, r in out.items():
        print(f"{'SILENT ' if r['silent'] else 'alive  '} {n:<24} "
              f"{r['hours_since']}h ago (alert >{r['alert_after_h']}h)")
    if recovered:
        print('RECOVERED since last run: ' + ', '.join(recovered))
    if firing:
        print('FLEET ALERT: ' + ', '.join(firing) + ' silent past threshold.',
              file=sys.stderr)
        print('Check the Anthropic subscription/billing first - a lapsed subscription '
              'kills every routine at once with 403 authentication_failed (F29).',
              file=sys.stderr)
        return 1
    if silent:
        print('%d routine(s) still silent (%s) - no mail: already reported, next '
              'reminder in <=%dh.' % (len(silent), ', '.join(silent), REMIND_AFTER_H))
        return 0
    print('\nall routines alive')
    return 0


if __name__ == '__main__':
    sys.exit(main())

# -*- coding: utf-8 -*-
"""
Routine scorecard — measures whether the self-improvement loop actually runs.

Wave 1 of prompts-as-code (scopebit docs/OS/EVOLUTION.md Change Ladder,
2026-08-04): every routine must append its full report to
docs/OS/ledger/routine-reports.md, ending with a '### Prompt critique'
subsection. This script reads that ledger plus the 30-day commit list and
scores each routine: does it report, does it critique its own prompt, does it
commit attributable work, does it fail. scopebit is PRIVATE, so the fetch uses
the GH_PAT repo secret (raw.githubusercontent.com honors token auth).

Honest-nulls rule (§3): a run that filed no report is invisible here BY DESIGN
(failure class F10) — runs_30d counts report headers, not trigger fires, and
missing data is emitted as null/None, never estimated.

Output: data/SCORECARD.json  (committed by the workflow like the other data files)
Requires: GH_PAT env (GitHub secret with read access to VrumVrum/scopebit).
"""
import json, os, re, urllib.request, datetime

PAT = os.environ.get('GH_PAT')
REPO = 'VrumVrum/scopebit'
RAW_REPORTS = f'https://raw.githubusercontent.com/{REPO}/master/docs/OS/ledger/routine-reports.md'
API_COMMITS = f'https://api.github.com/repos/{REPO}/commits'
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'SCORECARD.json')

COMMIT_HEURISTIC = (
    'commits_attributable = scopebit commits (last 30d, default branch) whose message '
    'contains the routine name as a fingerprint (case-insensitive; space/hyphen/underscore '
    'variants). Best-effort only: a routine that never names itself in commit messages '
    'scores 0 here even when it shipped, and shared words can over-match. Not ground truth.')


def fetch(url):
    headers = {'User-Agent': 'pce-ops-scorecard'}
    if PAT:
        headers['Authorization'] = f'token {PAT}'
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', 'replace')


def parse_reports(text):
    """Split routine-reports.md on '## <routine-name> — <timestamp>' headers."""
    entries = []
    heads = list(re.finditer(r'^## (.+?) — (.+)$', text, re.M))
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        entries.append({'routine': m.group(1).strip(),
                        'stamp_raw': m.group(2).strip(),
                        'body': text[m.end():end]})
    return entries


def stamp_date(raw):
    m = re.search(r'(\d{4}-\d{2}-\d{2})', raw)
    return m.group(1) if m else None


def name_variants(name):
    base = name.lower().strip()
    return {base, base.replace(' ', '-'), base.replace(' ', '_'),
            base.replace('-', ' '), base.replace('_', ' ')}


def main():
    if not PAT:
        print('routines_scorecard.py: no GH_PAT, skipping')
        return
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = (now - datetime.timedelta(days=30)).date().isoformat()
    out = {'generated_utc': now.isoformat(timespec='seconds'),
           'source': {'reports': RAW_REPORTS, 'commits': API_COMMITS + '?since=30d'},
           'commit_heuristic': COMMIT_HEURISTIC,
           'note': ('runs_30d counts report headers in routine-reports.md, NOT trigger fires — '
                    'a run that filed no report is invisible here (failure class F10). '
                    'null = data not derivable, never a fabricated count.')}

    # 1) the report ledger (the routines' own words)
    try:
        entries = parse_reports(fetch(RAW_REPORTS))
    except Exception as e:
        entries = None
        out['reports_error'] = str(e)[:200]

    # 2) the 30-day commit list (up to 3 pages of 100)
    commits = []
    commits_error = None
    since = (now - datetime.timedelta(days=30)).isoformat(timespec='seconds')
    try:
        for page in (1, 2, 3):
            batch = json.loads(fetch(f'{API_COMMITS}?since={since}&per_page=100&page={page}'))
            if not isinstance(batch, list):
                raise ValueError(str(batch)[:150])
            commits.extend(batch)
            if len(batch) < 100:
                break
    except Exception as e:
        commits_error = str(e)[:200]
    out['commits_30d_total'] = None if commits_error else len(commits)
    if commits_error:
        out['commits_error'] = commits_error
    messages = [((c.get('commit') or {}).get('message') or '').lower() for c in commits]

    routines = {}
    for e in entries or []:
        r = routines.setdefault(e['routine'], {
            'runs_30d': 0, 'reports_filed': 0, 'prompt_critiques_present': 0,
            'commits_attributable': None, 'failed_runs': 0,
            'stamps_unparsed': 0, 'last_report': None})
        r['reports_filed'] += 1
        d = stamp_date(e['stamp_raw'])
        if d is None:
            r['stamps_unparsed'] += 1
        elif d >= cutoff:
            r['runs_30d'] += 1
        if d and (r['last_report'] is None or d > r['last_report']):
            r['last_report'] = d
        if '### prompt critique' in e['body'].lower():
            r['prompt_critiques_present'] += 1
        if 'failed run' in e['body'].lower():
            r['failed_runs'] += 1
    for name, r in routines.items():
        if not commits_error:
            variants = name_variants(name)
            r['commits_attributable'] = sum(1 for m in messages
                                            if any(v in m for v in variants))
        if r['stamps_unparsed'] and r['runs_30d'] == 0:
            r['runs_30d'] = None  # entries exist but no parseable dates — don't guess
    out['routines'] = None if entries is None else routines
    if entries is not None and not routines:
        out['routines_note'] = 'routine-reports.md has no entries yet — nothing to score, nothing invented'

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=1)
    print(f"SCORECARD.json written — {len(routines)} routine(s) scored, "
          f"{out.get('commits_30d_total')} commits scanned")


if __name__ == '__main__':
    main()

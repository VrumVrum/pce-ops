# -*- coding: utf-8 -*-
"""
Due-experiment radar — surfaces EXPERIMENTS.md entries whose verify date has
arrived, next to the real GSC numbers for their target pages.

The experiment ledger accumulated a verification debt all July: verify dates
pass silently because no routine is forced to look. This script closes the
"forced look": it parses scopebit's docs/OS/ledger/EXPERIMENTS.md (PRIVATE repo
— GH_PAT auth), finds still-open entries due today or earlier, and attaches
28d clicks/impressions for every target page path it can find in the local
data/gsc_dump.json.

Honesty rules (§3): the verdict ALWAYS stays with the routine — every entry is
proposed 'needs-routine-judgment' unless the data shows unambiguous zero
movement (then 'likely-loss (0 imp delta)'). A Win is NEVER proposed by this
script. A prev-28d control delta is NOT derivable from the dump (no per-page
prev-window series — only 28d/90d snapshots and site-level dailies), and every
entry says so instead of estimating one.

Output: data/DUE-VERDICTS.json  (committed by the workflow like the other data files)
Requires: GH_PAT env (GitHub secret). --dry-run skips the remote fetch and reads
a local EXPERIMENTS.md from env EXPERIMENTS_MD instead (desktop testing, no PAT).
"""
import json, os, re, sys, urllib.request, datetime

PAT = os.environ.get('GH_PAT')
REPO = 'VrumVrum/scopebit'
RAW_EXPERIMENTS = f'https://raw.githubusercontent.com/{REPO}/master/docs/OS/ledger/EXPERIMENTS.md'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GSC = os.environ.get('GSC_OUT', os.path.join(ROOT, 'data', 'gsc_dump.json'))
OUT = os.path.join(ROOT, 'data', 'DUE-VERDICTS.json')
SITE = 'https://projectcostestimator.com'

CLOSED = ('🟢', '🔴', '⚪')  # any of these in the header = already classified
DELTA_NOTE = ('prev-28d control NOT derivable from gsc_dump (no per-page prev-window '
              'series; 90d totals overlap the 28d window; daily_28d is site-level only) '
              '— 28d numbers are point-in-time, advisory only')


def fetch(url):
    headers = {'User-Agent': 'pce-ops-due-experiments'}
    if PAT:
        headers['Authorization'] = f'token {PAT}'
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', 'replace')


def parse_experiments(text):
    """Split on '### E-001 · …' / '## E-013 — …' headers (both forms exist)."""
    out = []
    heads = list(re.finditer(r'^#{2,3} (E-\d+)\s*[·—-]?\s*(.*)$', text, re.M))
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        title = re.sub(r'\s*·\s*[🔵🟢🔴⚪].*$', '', m.group(2)).strip('` ')
        out.append({'id': m.group(1), 'title': title[:120],
                    'header': m.group(2), 'body': text[m.end():end]})
    return out


def verify_date(body):
    m = re.search(r'\*\*Verify:\s*\**\s*(\d{4}-\d{2}-\d{2})', body)
    return m.group(1) if m else None


def target_paths(body):
    """Site paths named in the entry — backticked (`/x`) or bare in prose
    (older entries: '**KPI:** /law-firm-website-cost clicks'). `*`/`[` mark
    prefix patterns. Dotted paths (/page.tsx, /route.ts) are code files, not
    URLs, and are dropped."""
    seen, out = set(), []
    found = re.findall(r'`(/[A-Za-z0-9\-_/\[\].*]*)`', body)
    # bare matches need >=5 chars: kills markup/code fragments (</a>, </loc>,
    # a JS regex's /g flag) that live inside longer code spans
    found += [p for p in re.findall(
        r'(?<![\w`./:<])(/[a-z0-9\-]+(?:/[a-z0-9\-\[\]*]+)*)(?!\w|\.[A-Za-z])', body)
        if len(p) >= 5]
    for p in found:
        if '?' in p or '.' in p or p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out[:20]


def norm(page):
    return (page or '').replace(SITE, '').split('?')[0].rstrip('/') or '/'


def path_metrics(path, pages_by_path):
    if '*' in path or '[' in path:
        prefix = re.split(r'[\[*]', path)[0]
        hits = [v for k, v in pages_by_path.items() if k.startswith(prefix)]
    else:
        hits = [pages_by_path[norm(path)]] if norm(path) in pages_by_path else []
    return {'pages_matched': len(hits),
            'impressions_28d': sum(h['impressions'] for h in hits),
            'clicks_28d': sum(h['clicks'] for h in hits)}


def main():
    dry = '--dry-run' in sys.argv
    if dry:
        local = os.environ.get('EXPERIMENTS_MD')
        if not local or not os.path.exists(local):
            print('due_experiments.py --dry-run: set EXPERIMENTS_MD to a local '
                  'EXPERIMENTS.md path; nothing to parse, skipping')
            return
        text = open(local, encoding='utf-8').read()
    else:
        if not PAT:
            print('due_experiments.py: no GH_PAT, skipping')
            return
        text = fetch(RAW_EXPERIMENTS)

    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    out = {'generated_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
           'note': ('advisory only — the VERDICT stays with the routine that reads this. '
                    'A Win is never proposed here; §3: no estimated/invented numbers.'),
           'delta_note': DELTA_NOTE}

    pages_by_path = {}
    dump_rows = None
    if os.path.exists(GSC):
        d = json.load(open(GSC, encoding='utf-8'))
        rows = d.get('pages_28d') or []
        dump_rows = len(rows)
        for p in rows:
            k = norm(p.get('page'))
            e = pages_by_path.setdefault(k, {'impressions': 0, 'clicks': 0})
            e['impressions'] += p.get('impressions', 0)
            e['clicks'] += p.get('clicks', 0)
        out['gsc_generated'] = d.get('generated')
    else:
        out['gsc_error'] = f'no gsc_dump at {GSC} — metrics omitted, not invented'
    # rowLimit is 500: a full dump means absence of a path is ambiguous (truncated),
    # a short dump means absence genuinely = zero recorded impressions.
    truncated = dump_rows is not None and dump_rows >= 500
    out['gsc_pages_rows'] = dump_rows
    out['gsc_truncated'] = truncated

    due = []
    for e in parse_experiments(text):
        if any(s in e['header'] for s in CLOSED):
            continue  # already classified — not open
        vdate = verify_date(e['body'])
        if not vdate or vdate > today:
            continue
        paths = target_paths(e['body'])
        entry = {'id': e['id'], 'title': e['title'], 'due': vdate,
                 'target_paths': paths, 'delta_prev_28d': None,
                 'proposed': 'needs-routine-judgment'}
        if paths and pages_by_path:
            metrics = {p: path_metrics(p, pages_by_path) for p in paths}
            entry['metrics_28d'] = metrics
            imp = sum(m['impressions_28d'] for m in metrics.values())
            clk = sum(m['clicks_28d'] for m in metrics.values())
            entry['totals_28d'] = {'impressions': imp, 'clicks': clk}
            if imp == 0 and clk == 0 and not truncated:
                entry['proposed'] = 'likely-loss (0 imp delta)'
        elif not paths:
            entry['note'] = 'no target page paths named in the entry — GSC cannot inform this one'
        else:
            entry['note'] = 'gsc_dump missing — no metrics attached'
        due.append(entry)
    due.sort(key=lambda x: (x['due'], x['id']))
    out['due_count'] = len(due)
    out['due'] = due

    if dry:
        print(json.dumps(out, indent=1, ensure_ascii=False))
        print(f"-- dry-run: {len(due)} due entr(ies), nothing written")
        return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"DUE-VERDICTS.json written — {len(due)} experiment(s) due for a verdict")


if __name__ == '__main__':
    main()

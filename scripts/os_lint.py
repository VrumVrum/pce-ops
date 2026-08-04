# -*- coding: utf-8 -*-
"""
OS lint — structural validation of scopebit's machine-read OS ledgers (SWE-agent
ACI principle: an agent-facing interface must be lintable, and a lint that cries
wolf gets ignored — so ONLY checks with ~0 false positives live here; style is
never flagged, structure only).

Wave 2 of the self-improvement loop. Validates:
  - routine-reports.md   : '## <name> — <timestamp>' headers parse (dated),
                           '### Prompt critique' present per entry dated on/after
                           the rule's start (2026-08-04); CONDENSATION blocks exempt
  - prompt-experiments.md: every P-entry heading carries the required fields
  - run-status.md        : every row after the '---' separator matches
                           date|routine|OK/FAIL/PARTIAL|commits|note
  - docs/OS/prompts/*.md : version header '<!-- vN · YYYY-MM-DD ... -->' on line 1,
                           LESSONS block <= 10 bullets (README.md exempt: canon doc,
                           not a routine prompt)

scopebit is PRIVATE — fetch uses the GH_PAT repo secret, same auth pattern as
routines_scorecard.py (raw.githubusercontent.com + api.github.com honor token
auth). Output: data/OS-LINT.json  {ok, violations: [{file, line?, rule, evidence}]}.

--dry-run [path]: read a local scopebit clone (path arg or SCOPEBIT_DIR env)
instead of fetching; print JSON, write nothing. No PAT needed.
"""
import json, os, re, sys, urllib.request, urllib.error, datetime

PAT = os.environ.get('GH_PAT')
REPO = 'VrumVrum/scopebit'
RAW = f'https://raw.githubusercontent.com/{REPO}/master'
API_PROMPTS = f'https://api.github.com/repos/{REPO}/contents/docs/OS/prompts'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'OS-LINT.json')

CRITIQUE_RULE_START = '2026-08-04'   # transparency rule went live; older entries exempt
P_REQUIRED = ('Routine', 'Evidence', 'Diff', 'Metric', 'Verify', 'Status', 'Approver')
ROW_RE = re.compile(r'^\d{4}-\d{2}-\d{2}\|[^|]+\|(OK|FAIL|PARTIAL)\|\d+\|.+$')
VERSION_RE = re.compile(r'^<!--\s*v\d+(?:\.\d+)?\s*[·.]\s*\d{4}-\d{2}-\d{2}\b.*-->\s*$')


def fetch(url, accept=None):
    headers = {'User-Agent': 'pce-ops-os-lint'}
    if PAT:
        headers['Authorization'] = f'token {PAT}'
    if accept:
        headers['Accept'] = accept
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', 'replace')


class Source:
    """Uniform reader over the remote repo or a local clone (--dry-run)."""

    def __init__(self, local_dir=None):
        self.local = local_dir

    def read(self, relpath):
        """Return file text (BOM-stripped) or None if the file doesn't exist."""
        if self.local:
            p = os.path.join(self.local, *relpath.split('/'))
            if not os.path.exists(p):
                return None
            return open(p, encoding='utf-8').read().lstrip('﻿')
        try:
            return fetch(f'{RAW}/{relpath}').lstrip('﻿')
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def list_prompts(self):
        if self.local:
            d = os.path.join(self.local, 'docs', 'OS', 'prompts')
            if not os.path.isdir(d):
                return []
            return sorted(n for n in os.listdir(d) if n.endswith('.md'))
        listing = json.loads(fetch(API_PROMPTS))
        if not isinstance(listing, list):
            raise ValueError(str(listing)[:150])
        return sorted(x['name'] for x in listing
                      if x.get('type') == 'file' and x['name'].endswith('.md'))


def v(violations, file, rule, evidence, line=None):
    row = {'file': file, 'rule': rule, 'evidence': evidence[:200]}
    if line is not None:
        row['line'] = line
    violations.append(row)


def lint_reports(text, violations):
    f = 'docs/OS/ledger/routine-reports.md'
    lines = text.split('\n')
    heads = [(i, l) for i, l in enumerate(lines, 1) if l.startswith('## ')]
    for idx, (ln, head) in enumerate(heads):
        m = re.match(r'^## (.+?) — (.+)$', head)
        if not m:
            v(violations, f, 'report-header-format',
              f"header lacks ' — <timestamp>': {head}", ln)
            continue
        name = m.group(1).strip()
        dm = re.search(r'\d{4}-\d{2}-\d{2}', m.group(2))
        if not dm:
            v(violations, f, 'report-header-date',
              f'no YYYY-MM-DD parseable in stamp: {head}', ln)
            continue
        if name.upper().startswith('CONDENSATION'):
            continue  # condensed memory blocks carry no critique by design
        if dm.group(0) < CRITIQUE_RULE_START:
            continue  # entry predates the critique rule
        end_ln = heads[idx + 1][0] - 1 if idx + 1 < len(heads) else len(lines)
        body = '\n'.join(lines[ln:end_ln])
        if '### prompt critique' not in body.lower():
            v(violations, f, 'prompt-critique-missing',
              f"entry '{head}' has no '### Prompt critique' subsection", ln)


def lint_p_entries(text, violations):
    f = 'docs/OS/ledger/prompt-experiments.md'
    lines = text.split('\n')
    heads = [(i, l) for i, l in enumerate(lines, 1)
             if re.match(r'^#{2,3} .*\bP-\d{3}\b', l)]
    for idx, (ln, head) in enumerate(heads):
        end_ln = heads[idx + 1][0] - 1 if idx + 1 < len(heads) else len(lines)
        body = '\n'.join(lines[ln:end_ln])
        missing = [fld for fld in P_REQUIRED
                   if not re.search(rf'\*\*{fld}\b', body)]
        if missing:
            v(violations, f, 'p-entry-fields-missing',
              f"{head} lacks required field(s): {', '.join(missing)}", ln)


def lint_run_status(text, violations):
    f = 'docs/OS/ledger/run-status.md'
    lines = text.split('\n')
    try:
        sep = next(i for i, l in enumerate(lines, 1) if l.strip() == '---')
    except StopIteration:
        v(violations, f, 'run-status-separator-missing',
          "no '---' separator line — rows have no anchored start")
        return
    for i, l in enumerate(lines[sep:], sep + 1):
        if not l.strip():
            continue
        if not ROW_RE.match(l.strip()):
            v(violations, f, 'run-status-row-format',
              f'row does not match date|routine|OK/FAIL/PARTIAL|commits|note: {l}', i)


def lint_prompt_file(name, text, violations):
    f = f'docs/OS/prompts/{name}'
    lines = text.split('\n')
    if not lines or not VERSION_RE.match(lines[0].strip()):
        v(violations, f, 'prompt-version-header-missing',
          f'first line is not <!-- vN · YYYY-MM-DD · P-### -->: '
          f'{(lines[0] if lines else "")!r}', 1)
    for i, l in enumerate(lines, 1):
        if re.match(r'^##\s+LESSONS\b', l):
            bullets = 0
            for j in range(i, len(lines)):
                s = lines[j]
                if s.startswith('## '):
                    break
                if re.match(r'^- ', s):
                    bullets += 1
            if bullets > 10:
                v(violations, f, 'lessons-cap-exceeded',
                  f'LESSONS block has {bullets} bullets (cap 10)', i)
            break


def main():
    dry = '--dry-run' in sys.argv
    local_dir = None
    if dry:
        args = [a for a in sys.argv[1:] if a != '--dry-run']
        local_dir = args[0] if args else os.environ.get('SCOPEBIT_DIR')
        if not local_dir or not os.path.isdir(local_dir):
            print('os_lint.py --dry-run: pass a local scopebit clone path '
                  '(arg or SCOPEBIT_DIR env); nothing to lint, skipping')
            return
    elif not PAT:
        print('os_lint.py: no GH_PAT, skipping')
        return

    src = Source(local_dir)
    violations = []
    out = {'generated_utc': datetime.datetime.now(datetime.timezone.utc)
                                             .isoformat(timespec='seconds'),
           'source': local_dir or f'{REPO}@master',
           'note': ('structure only, never style — every check here is chosen for '
                    '~0 false-positive rate (SWE-agent ACI / EVOLUTION.md meta-rule); '
                    'a missing file is reported, not guessed at')}

    checked, missing = [], []
    try:
        for relpath, linter in (
                ('docs/OS/ledger/routine-reports.md', lint_reports),
                ('docs/OS/ledger/prompt-experiments.md', lint_p_entries),
                ('docs/OS/ledger/run-status.md', lint_run_status)):
            text = src.read(relpath)
            if text is None:
                missing.append(relpath)
                v(violations, relpath, 'file-missing', 'expected ledger file absent')
                continue
            checked.append(relpath)
            linter(text, violations)
        for name in src.list_prompts():
            relpath = f'docs/OS/prompts/{name}'
            checked.append(relpath)
            if name == 'README.md':
                continue  # canon doc, not a routine prompt — no version header
            lint_prompt_file(name, src.read(relpath), violations)
    except Exception as e:
        out['fetch_error'] = f'{type(e).__name__}: {str(e)[:200]}'
        out['ok'] = None  # could not complete — unknown, never claimed green
        out['files_checked'] = checked
        out['violations'] = violations
        _emit(out, dry)
        return

    out['files_checked'] = checked
    if missing:
        out['files_missing'] = missing
    out['violations'] = violations
    out['ok'] = not violations
    _emit(out, dry)


def _emit(out, dry):
    if dry:
        print(json.dumps(out, indent=1, ensure_ascii=False))
        print(f"-- dry-run: ok={out.get('ok')}, "
              f"{len(out.get('violations', []))} violation(s), nothing written")
        return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"OS-LINT.json written — ok={out.get('ok')}, "
          f"{len(out.get('violations', []))} violation(s)")


if __name__ == '__main__':
    main()

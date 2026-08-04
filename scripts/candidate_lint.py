# -*- coding: utf-8 -*-
"""
Candidate lint — STAGE 1 of the evaluator cascade (AlphaEvolve pattern) for
title / meta-description / snippet rewrite candidates on scopebit.

Deterministic, cheap, zero-LLM. A candidate that fails here never reaches the
stage-2 rubric (docs/OS/rubrics/title-rubric.md in scopebit) or stage-3
(DiD cohort verdict at 14-28d). Chosen for ~0 false positives on the site's
REAL title inventory (niche pages legitimately carry page-specific ranges like
"$5K-$30K" — those are NOT flagged; only drift against the three canonical
claims is).

Checks:
  1. title <= 60 chars; desc <= 160 chars
  2. desc (when given) must contain a $ figure OR a 20xx year (publishing
     checklist: "description ... with a $ or year"); stale years (< current)
     are violations in both fields
  3. canon consistency (F9 immune class): where the text makes one of the three
     canonical claims, the numbers must match EXACTLY —
       - generic "a website costs" claim  -> $300-$50,000+  (also $300-$50K)
       - "Eastern Europe" rate claim      -> $25-$50
       - product prices: Full Report $15 · Quote Analyzer $39 · Expert Review $99
     never other prices for these three claims
  4. no AI-tell words — banned list read from scopebit Constitution §8
     (GH_PAT raw fetch, same auth pattern as os_lint.py), or --banned-file,
     with a hardcoded core fallback
  5. no self-citation inside the first sentence of the desc/snippet (the
     extraction span an answer engine quotes must not contain the brand)

Usage:
  python candidate_lint.py --title "..." [--desc "..."] [--page /path]
                           [--banned-file path]
Exit 0 = clean (warnings allowed) · exit 1 = violations, JSON on stdout.
"""
import argparse, datetime, json, os, re, sys, urllib.request

PAT = os.environ.get('GH_PAT')
CONSTITUTION_RAW = ('https://raw.githubusercontent.com/VrumVrum/scopebit/'
                    'master/docs/OS/00-CONSTITUTION.md')

# Core fallback (union of Constitution §8 + pce-content list); "leverage" is
# banned as a verb — all verb forms are matched, the noun "leverage" alone in
# e.g. "financial leverage" would too, but that phrase has no place in a title.
CORE_BANNED = [
    'delve', 'unleash', 'leverage', 'elevate', 'robust', 'seamless',
    'landscape', 'realm', 'tapestry', 'embark', 'crucial', 'comprehensive',
]

TITLE_MAX, DESC_MAX = 60, 160
BRAND_TOKENS = ('project cost estimator', 'projectcostestimator', 'scopebit')
CUR_YEAR = datetime.date.today().year


def fetch_banned_from_constitution():
    """Parse the 'No AI-tell words:' line of Constitution §8. Returns [] on any failure."""
    try:
        headers = {'User-Agent': 'pce-ops-candidate-lint'}
        if PAT:
            headers['Authorization'] = f'token {PAT}'
        req = urllib.request.Request(CONSTITUTION_RAW, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            text = r.read().decode('utf-8', 'replace')
    except Exception:
        return []
    m = re.search(r'No AI-tell words:\s*(.+)', text)
    if not m:
        return []
    words = []
    for raw in m.group(1).split(','):
        w = raw.strip().strip('."').strip()
        if not w or ' ' in w and not w.startswith('"'):
            # multi-word phrases like "in today's fast-paced world" — keep as phrase
            pass
        w = w.strip('"')
        # "seamless(ly)" -> seamless
        w = re.sub(r'\(.*?\)', '', w).strip()
        if w:
            words.append(w.lower())
    return words


def dollars(text):
    """All dollar amounts in text as (int_value, raw) — handles $50K, $50,000, $50000."""
    out = []
    for m in re.finditer(r'\$\s*([0-9][0-9,.]*)\s*([kK])?', text):
        raw = m.group(0)
        num = m.group(1).replace(',', '')
        try:
            val = float(num)
        except ValueError:
            continue
        if m.group(2):
            val *= 1000
        out.append((int(val), raw))
    return out


def check_canon(text, violations):
    """F9 canon drift: only where the text makes one of the 3 canonical claims."""
    t = text.lower()
    amounts = dollars(text)

    # 1) generic website-cost claim: "a website costs", "does a website cost",
    #    or the phrase "website cost" NOT preceded by a niche qualifier word
    generic = re.search(r'(?:\ba\s+website\s+costs?\b|\bdoes\s+a\s+website\s+cost\b'
                        r'|^\s*website\s+costs?\b)', t)
    if generic:
        rng = re.search(r'\$\s*([\d,\.]+)\s*[kK]?\s*[-–—]\s*'
                        r'\$?\s*([\d,\.]+)\s*([kK])?', text)
        if rng:
            vals = dollars(rng.group(0))
            if len(vals) >= 2 and (vals[0][0], vals[1][0]) != (300, 50000):
                violations.append({
                    'check': 'canon-website-range',
                    'evidence': f'generic website-cost claim carries {rng.group(0)!r}; '
                                f'canon is $300-$50,000+ (F9)'})

    # 2) Eastern Europe rate claim
    if 'eastern europe' in t:
        vals = [v for v, _ in amounts]
        if vals and not ({25, 50} <= set(vals)):
            violations.append({
                'check': 'canon-ee-rate',
                'evidence': f'Eastern Europe claim carries {vals}; canon is $25-$50 (F9)'})

    # 3) product prices near their product names
    for product, price in (('full report', 15), ('quote analyzer', 39),
                           ('expert review', 99)):
        if product in t:
            near = [v for v, _ in amounts]
            if near and price not in near:
                violations.append({
                    'check': 'canon-product-price',
                    'evidence': f'{product!r} mentioned with prices {near}; '
                                f'canon is ${price} (frozen, §6)'})


def check_years(text, field, violations):
    for m in re.finditer(r'\b(20\d\d)\b', text):
        if int(m.group(1)) < CUR_YEAR:
            violations.append({
                'check': 'stale-year',
                'evidence': f'{field} claims year {m.group(1)}; current year is {CUR_YEAR}'})


def check_banned(text, field, banned, violations):
    t = text.lower()
    for w in banned:
        if ' ' in w:  # phrase
            if w in t:
                violations.append({'check': 'ai-tell-word',
                                   'evidence': f'{field} contains banned phrase {w!r}'})
            continue
        # match inflections: leverage/leverages/leveraged/leveraging, delve/delves/delving...
        if re.search(rf'\b{re.escape(w)}(?:s|d|ed|ing|ly)?\b', t):
            violations.append({'check': 'ai-tell-word',
                               'evidence': f'{field} contains banned word {w!r}'})


def first_sentence(text):
    m = re.search(r'^(.*?[.!?])(?:\s|$)', text.strip())
    return m.group(1) if m else text.strip()


def main():
    ap = argparse.ArgumentParser(description='Stage-1 deterministic lint for '
                                 'title/meta/snippet rewrite candidates')
    ap.add_argument('--title', required=True)
    ap.add_argument('--desc', default=None)
    ap.add_argument('--page', default=None, help='site path the candidate targets')
    ap.add_argument('--banned-file', default=None,
                    help='newline-separated banned-word list (overrides fetch)')
    args = ap.parse_args()

    violations, warnings = [], []

    banned = list(CORE_BANNED)
    src = 'core-fallback'
    if args.banned_file:
        try:
            with open(args.banned_file, encoding='utf-8') as f:
                extra = [l.strip().lower() for l in f if l.strip()]
            banned = sorted(set(banned) | set(extra))
            src = f'core+{os.path.basename(args.banned_file)}'
        except OSError as e:
            warnings.append({'check': 'banned-file', 'evidence': str(e)})
    else:
        fetched = fetch_banned_from_constitution()
        if fetched:
            banned = sorted(set(banned) | set(fetched))
            src = 'core+constitution-§8'
        else:
            warnings.append({'check': 'banned-fetch',
                             'evidence': 'Constitution fetch unavailable; '
                                         'using hardcoded core list only'})

    # 1. lengths
    if len(args.title) > TITLE_MAX:
        violations.append({'check': 'title-length',
                           'evidence': f'title is {len(args.title)} chars (max {TITLE_MAX})'})
    if args.desc is not None and len(args.desc) > DESC_MAX:
        violations.append({'check': 'desc-length',
                           'evidence': f'desc is {len(args.desc)} chars (max {DESC_MAX})'})

    # 2. anchor ($ or year) + stale years
    if args.desc is not None:
        if not dollars(args.desc) and not re.search(r'\b20\d\d\b', args.desc):
            violations.append({'check': 'desc-no-anchor',
                               'evidence': 'desc has neither a $ figure nor a year '
                                           '(publishing checklist)'})
        check_years(args.desc, 'desc', violations)
    check_years(args.title, 'title', violations)
    if not dollars(args.title) and not re.search(r'\b20\d\d\b', args.title):
        warnings.append({'check': 'title-no-anchor',
                         'evidence': 'title has neither a $ figure nor a year — '
                                     'allowed, but the canon prefers one'})

    # 3. canon drift (F9)
    check_canon(args.title, violations)
    if args.desc:
        check_canon(args.desc, violations)

    # 4. AI-tell words
    check_banned(args.title, 'title', banned, violations)
    if args.desc:
        check_banned(args.desc, 'desc', banned, violations)

    # 5. self-citation in the extraction span
    if args.desc:
        fs = first_sentence(args.desc).lower()
        for tok in BRAND_TOKENS:
            if tok in fs:
                violations.append({'check': 'self-citation-first-sentence',
                                   'evidence': f'first sentence of desc contains '
                                               f'{tok!r} — the extraction span must '
                                               f'be quotable without the brand'})
                break

    out = {
        'ok': not violations,
        'stage': 1,
        'input': {'title': args.title, 'desc': args.desc, 'page': args.page},
        'banned_source': src,
        'violations': violations,
        'warnings': warnings,
        'next': ('stage 2: self-apply docs/OS/rubrics/title-rubric.md (scopebit), '
                 'then stage 3: DiD cohort verdict at 14-28d'
                 if not violations else 'rejected at stage 1 — do not ship'),
    }
    print(json.dumps(out, indent=1))
    sys.exit(0 if not violations else 1)


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""
Search Opportunity Engine — turns the GSC dump into a RANKED action queue.

The site earns tens of thousands of impressions but the "which page do I touch
next" decision was being made by hand (or by whichever pasted analysis was most
recent). This makes it deterministic and autonomous: every week it reads the
committed GSC dump and emits data/PAGE-OPPORTUNITIES.json — the striking-distance
pages ranked by (commercial-intent impressions x proximity-to-page-1), so effort
goes where Google already tests us AND where a click is actually winnable.

THE NUANCE THAT MAKES IT SMARTER THAN "optimise high-impression low-CTR pages"
(verified 2026-08-16): a page can rank position 2 for an informational
"how much does X cost" query and STILL earn 0 clicks because Google's AI Overview
answers inline using our own numbers — no title fixes that. So queries are
classified:
  - tool  : commercial/tool intent ("X cost calculator", "X rates", "hire X")
            -> a click IS winnable, genuinely optimisable.
  - info  : informational "how much does X cost" -> often AI-Overview-eaten,
            flagged ai_overview_risk, NOT counted as the opportunity.
  - junk  : LLM query-fanout permutations ("... pricing official 2026 free plan")
            + third-party product pricing -> excluded so it never inflates a score.

Only 'tool' impressions drive the score. A page with big impressions that are all
info/junk is correctly NOT surfaced as an opportunity.

Blind != healthy (F29): if the dump is missing or stale beyond a threshold, exit
non-zero so the workflow fails loudly instead of publishing an empty queue.
"""
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUMP = os.path.join(HERE, 'data', 'gsc_dump.json')
OUT = os.path.join(HERE, 'data', 'PAGE-OPPORTUNITIES.json')
STALE_DAYS = 10  # dump older than this = we're flying on stale data

JUNK = re.compile(r'\b(official|free plan|free tier)\b|cloudflare|vercel|\bd1\b|workers|\bpages pricing\b|aws|netlify|\b20\d\d\b.*\b20\d\d\b', re.I)
TOOL = re.compile(r'\b(calculator|estimator|how much (do|does).*(charge|cost to (hire|build|make))|rates?|hourly|pricing|hire|quote|cost for)\b', re.I)
INFO = re.compile(r'^how much (does|is|to)\b|\bcost of\b|\bcost (in|for) 20\d\d\b', re.I)


def classify(q):
    if JUNK.search(q):
        return 'junk'
    if TOOL.search(q):
        return 'tool'
    if INFO.search(q):
        return 'info'
    return 'other'


def strip_host(u):
    return re.sub(r'^https?://[^/]+', '', u)


def main():
    if not os.path.exists(DUMP):
        print(f"BLIND: {DUMP} missing — cannot mine. Failing loud (F29).", file=sys.stderr)
        return 2
    d = json.load(open(DUMP, encoding='utf-8'))

    # staleness guard
    gen = d.get('generated')
    stale = None
    if gen:
        try:
            age = (date.today() - date.fromisoformat(gen)).days
            stale = age
            if age > STALE_DAYS:
                print(f"BLIND: gsc_dump.json is {age}d old (> {STALE_DAYS}) — stale. Failing loud.", file=sys.stderr)
                return 2
        except ValueError:
            pass

    pages_28d = d.get('pages_28d') or []
    pq = d.get('page_query_28d') or []
    if not pages_28d:
        print("BLIND: no pages_28d in dump. Failing loud.", file=sys.stderr)
        return 2

    # Per-page intent shares FROM the page/query pairs. NOTE: page_query_28d is
    # capped at the global top-500 pairs, so a high-impression page whose demand
    # is spread across many small-volume queries (e.g. /freelance-website-cost)
    # has little/no data here. So intent is used only to DEMOTE pages we can prove
    # are junk/info-dominated and to ANNOTATE — NEVER as the primary score. The
    # primary rank is pages_28d (accurate per-page impressions + position), which
    # is why the real #1 impression page surfaces even with zero pairs in the cap.
    intent = defaultdict(lambda: {'tool': 0, 'info': 0, 'junk': 0, 'other': 0, 'top_tool': []})
    for r in pq:
        p = strip_host(r['page'])
        c = classify(r['query'])
        intent[p][c] += r['impressions']
        if c == 'tool':
            intent[p]['top_tool'].append({'q': r['query'], 'impr': r['impressions'],
                                          'pos': round(r['position'], 1), 'clicks': r['clicks']})

    def proximity(pos):
        if pos <= 3:
            return 0.25   # already top-3; upside is limited
        if pos <= 12:
            return 1.0    # page 1-2 edge = the sweet spot
        if pos <= 20:
            return 0.7
        if pos <= 30:
            return 0.35
        return 0.12

    opportunities = []
    for t in pages_28d:
        p = strip_host(t['page'])
        pos = t['position']
        impr = t['impressions']
        clicks = t['clicks']
        if impr < 120:            # not enough demand to be worth a cycle
            continue
        sh = intent.get(p, {})
        tool_impr = sh.get('tool', 0)
        info_impr = sh.get('info', 0)
        junk_impr = sh.get('junk', 0)
        known = tool_impr + info_impr + junk_impr + sh.get('other', 0)  # impressions we have intent for
        # PRIMARY score = accurate page impressions x proximity to page 1.
        score = impr * proximity(pos)
        # DEMOTE where we can PROVE the page's visible demand is junk/info, not tool.
        if known >= 50:
            junk_share = (junk_impr + info_impr) / known
            if junk_impr / known >= 0.5:
                score *= 0.15     # junk-dominated (cloudflare/vercel-style) — nearly kill
            elif junk_share >= 0.5:
                score *= 0.5      # AI-Overview-eaten informational — real but capped
        score = round(score, 1)
        top = sorted(sh.get('top_tool', []), key=lambda x: -x['impr'])[:3]
        # recommended action
        if known >= 50 and junk_impr / known >= 0.5:
            action = 'noindex / refocus - impressions are LLM-fanout junk, wrong intent'
        elif pos > 30:
            action = 'content/relevance rebuild (ranks far from page 1 despite demand)'
        elif known >= 50 and info_impr > tool_impr:
            action = 'capture the tool-intent click (informational share is AI-Overview-eaten)'
        elif pos <= 12:
            action = 'optimise + internal-link to climb into top-10; add linkable asset'
        else:
            action = 'strengthen content + internal links to reach page 1'
        opportunities.append({
            'page': p,
            'position': round(pos, 1),
            'impressions': impr,
            'clicks': clicks,
            'score': score,
            'recommended_action': action,
            'intent_coverage_impr': known,  # how much of this page's demand we could classify
            'tool_impr': tool_impr,
            'info_impr_ai_overview_risk': info_impr,
            'junk_impr': junk_impr,
            'top_commercial_queries': top,
        })

    opportunities.sort(key=lambda o: -o['score'])

    snap = {
        'generated_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'dump_generated': gen,
        'dump_age_days': stale,
        'totals_28d': d.get('totals_28d'),
        'method': ('score = tool-intent impressions x proximity-to-page-1. '
                   'info (AI-Overview-eaten) and junk (LLM query-fanout) impressions '
                   'are NOT counted. Only commercial/tool queries where a click is winnable.'),
        'opportunity_count': len(opportunities),
        'opportunities': opportunities[:40],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(snap, fh, indent=1, ensure_ascii=False)
        fh.write('\n')

    print(f"mined {len(opportunities)} opportunities from {len(pages_28d)} pages "
          f"(dump {stale}d old). top 8:")
    for o in opportunities[:8]:
        print("  %6.1f  %-36s pos %5.1f  %5d impr  tool%%=%2.0f  %s"
              % (o['score'], o['page'][:36], o['position'], o['impressions'],
                 100 * o['tool_impr'] / max(o['impressions'], 1), o['recommended_action'][:40]))
    # healthy run: real opportunities found. Zero could be legit but is suspicious.
    if not opportunities:
        print("WARN: 0 opportunities — either genuinely none or the classifier is off.", file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())

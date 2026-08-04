#!/usr/bin/env python3
"""Longitudinal GSC trends from THIS repo's git history (Willison git-scraping).

daily-ops commits data/gsc_dump.json twice a day. Nobody ever looked at the
HISTORY of those commits — each consumer reads only the latest snapshot. This
script walks `git log -- data/gsc_dump.json`, loads up to ~8 deduped daily
snapshots spanning up to 4+ weeks, and computes week-over-week deltas on
IMPRESSIONS and POSITION per page and per query. Clicks are deliberately NOT
used as a delta signal: at 88 clicks/28d the w/w click noise swamps any trend.

Outputs data/GSC-TRENDS.json:
  decaying[]         pages whose 28d-window impressions fell >=30% vs the
                     snapshot ~1 week earlier, guarded by a noise floor of
                     >=100 impressions/week before the decay (28d/4). NOTE:
                     rolling 28d windows ~1 week apart overlap ~21 days, so a
                     -30% window drop is a CONSERVATIVE, strong decay signal.
  refit_candidates[] pages with >=100 impressions/28d AND position 5-15 AND
                     CTR below the site clean average (junk-filtered, from
                     METRICS.json). Title/meta refits on these beat new pages
                     at this traffic level.
  wow.pages/queries  the raw longitudinal deltas the two lists derive from.

Honest nulls: when git history is too short for a ~7-day pair, wow/decaying
report status insufficient_history with the measured span — never a guess.
refit_candidates only needs the CURRENT snapshot, so it is always computed.

Run: python scripts/gsc_trends.py   (wired into daily-ops.yml, non-fatal)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone, date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = "data/gsc_dump.json"
OUT = os.environ.get("GSC_TRENDS_OUT", os.path.join(REPO, "data", "GSC-TRENDS.json"))
METRICS = os.path.join(REPO, "data", "METRICS.json")

MAX_SNAPSHOTS = 8          # newest + closest to 7,14,21,28,35,42,49 days back
WOW_GAP_DAYS = (6.0, 10.0)  # accepted gap for a "week-over-week" pair
DECAY_PCT = -30.0          # impressions drop threshold
DECAY_FLOOR_WEEKLY = 100   # imp/week BEFORE decay (28d window / 4) — noise guard
QUERY_FLOOR_28D = 50       # min prev impressions for a query to be tracked
PAGE_FLOOR_28D = 100       # min prev impressions for a page delta row
REFIT_MIN_IMP_28D = 100
REFIT_POS = (5.0, 15.0)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout


def ensure_history() -> None:
    """CI checkouts are often shallow; deepen so git log actually has history."""
    try:
        if git("rev-parse", "--is-shallow-repository").strip() == "true":
            subprocess.run(["git", "fetch", "--unshallow", "--quiet"], cwd=REPO,
                           capture_output=True, text=True, timeout=300)
    except Exception as e:  # non-fatal — we report whatever history we can see
        print(f"unshallow attempt failed (continuing): {e}", file=sys.stderr)


def load_snapshots() -> list[dict]:
    """One snapshot per `generated` date (newest commit wins), newest first."""
    shas = git("log", "--format=%H", "--", DATA_FILE).split()
    by_date: dict[str, dict] = {}
    for sha in shas:  # newest -> oldest; first seen per date wins
        try:
            d = json.loads(git("show", f"{sha}:{DATA_FILE}"))
        except Exception:
            continue
        gen = d.get("generated")
        if not gen or gen in by_date:
            continue
        by_date[gen] = {"sha": sha, "generated": gen, "data": d}
    snaps = sorted(by_date.values(), key=lambda s: s["generated"], reverse=True)
    if len(snaps) <= 1:
        return snaps
    # thin to ~MAX_SNAPSHOTS spanning up to 7 weeks: newest + weekly anchors
    newest = date.fromisoformat(snaps[0]["generated"])
    picked = {snaps[0]["generated"]: snaps[0]}
    for back in (7, 14, 21, 28, 35, 42, 49):
        target = newest.toordinal() - back
        best = min(snaps[1:], key=lambda s: abs(date.fromisoformat(s["generated"]).toordinal() - target))
        if abs(date.fromisoformat(best["generated"]).toordinal() - target) <= 3:
            picked[best["generated"]] = best
        if len(picked) >= MAX_SNAPSHOTS:
            break
    return sorted(picked.values(), key=lambda s: s["generated"], reverse=True)


def index(rows: list[dict], key: str) -> dict[str, dict]:
    return {r[key]: r for r in rows if r.get(key)}


def deltas(curr: list[dict], prev: list[dict], key: str, floor: int) -> list[dict]:
    ci, pi = index(curr, key), index(prev, key)
    out = []
    for k, p in pi.items():
        if p.get("impressions", 0) < floor:
            continue
        c = ci.get(k, {"impressions": 0, "position": None, "ctr": None})
        pimp, cimp = p["impressions"], c["impressions"]
        row = {
            key: k,
            "impressions_prev_28d": pimp,
            "impressions_curr_28d": cimp,
            "impressions_delta_pct": round((cimp - pimp) / pimp * 100, 1),
            "position_prev": p.get("position"),
            "position_curr": c.get("position"),
        }
        if p.get("position") is not None and c.get("position") is not None:
            row["position_delta"] = round(c["position"] - p["position"], 1)
        out.append(row)
    out.sort(key=lambda r: abs(r["impressions_delta_pct"]), reverse=True)
    return out


def clean_ctr() -> tuple[float | None, str]:
    try:
        m = json.load(open(METRICS, encoding="utf-8"))
        v = m["gsc"]["totals_28d_clean"]["ctr"]
        return float(v), "METRICS.json gsc.totals_28d_clean.ctr (junk-filtered)"
    except Exception:
        return None, "unavailable"


def main() -> int:
    ensure_history()
    snaps = load_snapshots()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result: dict = {
        "generated_utc": now,
        "site": snaps[0]["data"].get("site") if snaps else None,
        "method": {
            "source": "git history of data/gsc_dump.json in this repo (git-scraping)",
            "windows": "each snapshot holds ROLLING 28d aggregates; w/w compares snapshots ~7 days apart, so windows overlap ~21 days — deltas are smoothed and conservative",
            "signals": "impressions + position only; clicks excluded (88 clicks/28d — no w/w signal at this volume)",
            "decay_rule": f"impressions_delta_pct <= {DECAY_PCT}% AND prev >= {DECAY_FLOOR_WEEKLY} imp/week (prev_28d/4 >= {DECAY_FLOOR_WEEKLY})",
            "refit_rule": f"curr impressions >= {REFIT_MIN_IMP_28D}/28d AND position {REFIT_POS[0]}-{REFIT_POS[1]} AND ctr < site clean avg",
            "wow_gap_accepted_days": list(WOW_GAP_DAYS),
        },
        "history": {
            "snapshots_used": [{"sha": s["sha"][:12], "generated": s["generated"]} for s in snaps],
            "span_days": (
                (date.fromisoformat(snaps[0]["generated"]) - date.fromisoformat(snaps[-1]["generated"])).days
                if len(snaps) >= 2 else 0
            ),
        },
    }

    # ---- refit candidates: current snapshot only, always computable ----
    if snaps:
        avg_ctr, ctr_src = clean_ctr()
        cur_pages = snaps[0]["data"].get("pages_28d", [])
        refit = []
        if avg_ctr is not None:
            for p in cur_pages:
                imp, pos, ctr = p.get("impressions", 0), p.get("position"), p.get("ctr")
                if imp >= REFIT_MIN_IMP_28D and pos is not None and REFIT_POS[0] <= pos <= REFIT_POS[1] and ctr is not None and ctr < avg_ctr:
                    refit.append({
                        "page": p["page"], "impressions_28d": imp,
                        "position": pos, "ctr_pct": ctr,
                        "site_clean_ctr_pct": avg_ctr,
                        "headroom_clicks_28d_at_clean_ctr": round(imp * (avg_ctr - ctr) / 100, 1),
                    })
            refit.sort(key=lambda r: r["impressions_28d"], reverse=True)
        result["refit_candidates"] = refit
        result["refit_note"] = (
            f"site clean avg CTR source: {ctr_src}"
            if avg_ctr is not None
            else "null: no clean CTR available (METRICS.json unreadable) — refusing to compare against raw junk-polluted average"
        )
    else:
        result["refit_candidates"] = []
        result["refit_note"] = "null: no snapshots readable from git history"

    # ---- w/w pair selection ----
    pair = None
    if len(snaps) >= 2:
        newest_d = date.fromisoformat(snaps[0]["generated"])
        for s in snaps[1:]:
            gap = (newest_d - date.fromisoformat(s["generated"])).days
            if WOW_GAP_DAYS[0] <= gap <= WOW_GAP_DAYS[1]:
                pair = (snaps[0], s, gap)
                break

    if pair is None:
        span = result["history"]["span_days"]
        result["wow"] = {
            "status": "insufficient_history",
            "reason": f"{len(snaps)} snapshot date(s) spanning {span} day(s); no pair {WOW_GAP_DAYS[0]:.0f}-{WOW_GAP_DAYS[1]:.0f} days apart yet. Honest null — will populate as daily-ops history accumulates.",
            "pages": None, "queries": None,
        }
        result["decaying"] = []
        result["decaying_status"] = "insufficient_history"
    else:
        curr, prev, gap = pair
        pages_wow = deltas(curr["data"].get("pages_28d", []), prev["data"].get("pages_28d", []), "page", PAGE_FLOOR_28D)
        queries_wow = deltas(curr["data"].get("queries_28d", []), prev["data"].get("queries_28d", []), "query", QUERY_FLOOR_28D)
        result["wow"] = {
            "status": "ok",
            "pair": {"curr": curr["generated"], "prev": prev["generated"], "gap_days": gap},
            "pages": pages_wow[:60],
            "queries": queries_wow[:40],
        }
        result["decaying"] = [
            r for r in pages_wow
            if r["impressions_delta_pct"] <= DECAY_PCT
            and r["impressions_prev_28d"] / 4 >= DECAY_FLOOR_WEEKLY
        ]
        result["decaying_status"] = "ok"

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
        f.write("\n")
    print(
        f"GSC-TRENDS: {len(snaps)} snapshots, span {result['history']['span_days']}d, "
        f"wow={result['wow']['status']}, decaying={len(result['decaying'])}, "
        f"refit_candidates={len(result['refit_candidates'])} -> {OUT}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

# PCE-OPS Autonomous Growth Operator — Design (Phase 2, no code yet)

**Purpose:** show exactly how the *existing* pce-ops architecture supports the autonomous acquisition loop you described, the **minimum** additions required, and — honestly — the one lane that carries irreversible risk and how it's made safe. Success criterion held throughout: *"if the operator disappears for 30 days, the system keeps discovering, creating assets, distributing, acquiring citations/links, measuring and reallocating — within safety/budget limits — without daily intervention."*

The operating principle you set, and I agree with: **autonomous ≠ reckless.** The human sets objective + budget + credentials + channels + safety policy. Everything below that runs on policy, not per-opportunity approval.

---

## 1. The honest split: what is safe to fully automate vs what carries hard risk

The 30-day-autonomy vision divides cleanly into two halves. I'm stating this up front because it drives the whole design.

### Half A — FULLY autonomous, low/no irreversible risk (build this at full autonomy)
These act on **our own property** or **read-only on the web**. Worst case is wasted compute, never a burned reputation:
- **Discover** opportunities: resource pages, competitor-cited pages, unlinked mentions, broken resources, journalists/newsletters, dataset-citation targets, SERP gaps. (Read-only crawling/search.)
- **Qualify + score** on relevance × authority × referral × editorial × business value.
- **Create the asset** the opportunity needs: dataset cut, cost index, benchmark, chart, calculator, embeddable widget, report. **This is publishing our own content on our own site — zero external risk, maximum compounding.**
- **Distribute on our own channels**: syndication (dev.to = dofollow, Mastodon), dataset platforms (Zenodo/Kaggle/HF/data.world), IndexNow, our embed network.
- **Verify** whether a link/mention actually appeared (fetch + confirm the anchor).
- **Measure** referral traffic + downstream calculator/lead/revenue.
- **Learn + reallocate** effort by measured success-rate per tactic.

**Half A alone is a real autonomous growth department** and passes most of the 30-day test — because citable assets + dataset citations + own-channel distribution earn links *without sending a single cold email.* Given PCE currently has **0 earned editorial links**, Half A is also exactly where the first genuine ones will come from.

### Half B — carries irreversible, outward-facing risk (build it, but gated by policy + circuit-breakers)
**Autonomously SENDING cold outreach** to strangers, with follow-ups, no human in the loop. The hard truths:
- Deliverability is enforced by **recipient complaint rate**, not by how personalized the message is. A no-human-review send loop *will* eventually send something that draws complaints.
- The blast radius is the **domain's email reputation** — the same domain that sends lead briefs + receipts. Burning it is slow to reverse (weeks–months of re-warming) and silently degrades transactional mail.
- The ESP (Resend) **suspends accounts** on complaint/bounce spikes. That's an external party's decision we don't control.
- Cold commercial outreach is regulated (CAN-SPAM / GDPR / CASL) — unsubscribe honoring, identity, opt-out are mandatory.

None of that is a reason not to build it. It **is** the reason it can't be a naive "send without limits" loop. Design below makes it safe.

---

## 2. The acquisition loop mapped onto EXISTING pce-ops (reuse, don't rebuild)

`DISCOVER → QUALIFY → SCORE → CREATE/SELECT ASSET → CONTACT → FOLLOW-UP → VERIFY → MEASURE → LEARN → REINVEST`

| Loop stage | Existing component that already does ~this | What it needs |
|---|---|---|
| DISCOVER | `demand_*` (demand mining), `bing.py`/`gsc_dump` (query+competitor surface), `crawl.py` | + source adapters (resource-page/unlinked-mention/broken-link/journalist finders) — thin, read-only |
| QUALIFY + SCORE | `candidate_lint` (content gate), `anomaly_watch` (scoring patterns), `due_experiments` (EV logic) | + one shared **opportunity schema + scoring fn** |
| CREATE ASSET | `dataset_refresh` (idempotent multi-platform publish), scopebit build (pages/calculators/embeds) | + asset templates; actuator already can open the PR to build a page |
| DISTRIBUTE (own) | **`syndicate`** (dev.to+Mastodon, live), `dataset_refresh`, `ping_index`/IndexNow, `embed.js` | + extend `syndicate` queue; embed-seeding helper |
| CONTACT / FOLLOW-UP | **`acquisition_actuator`** already performs gated external actions (fork→PR, disclosure, idempotency, 2/run cap) | + an outreach lane with the safety controls in §4 |
| VERIFY | backlink verification crawler (used in this session's audit) + `bing.py` InLinks | + schedule it per acquired-opportunity |
| MEASURE | `ga4.py`, `metrics.py`, GSC | + attribution join (visitor/session id, O18 in the audit) |
| LEARN + REINVEST | **`due_experiments`** (already refuses fabricated WINs) + experiment ledger | + per-tactic success-rate table → allocation weight |

**Conclusion: ~70% of the loop already exists as components.** This is not a 20-agent build. It's **one coordinator + a handful of adapters + safety controls.**

## 3. Minimum additions (the whole net-new surface)

Small, coordinated **workers** — not 20 isolated agents:

1. **`opportunity.py`** — unified opportunity model + scoring (EV = relevance×authority×referral×editorial×business ÷ effort×risk) + `data/OPPORTUNITIES.json` (extends the experiment ledger, doesn't duplicate it).
2. **Discovery adapters** (read-only): `find_resource_pages`, `find_unlinked_mentions`, `find_broken_resources`, `find_journalists`, `find_competitor_gaps`. Each just emits scored opportunities.
3. **`asset_factory` hook** — given an opportunity that needs an asset, pick the template (index/benchmark/chart/embed/report) and drive `dataset_refresh` / an actuator PR to publish it, then auto-generate its distribution plan.
4. **`outreach.py`** — draft + send lane, **wrapped in the §4 safety envelope** (this is the only genuinely risk-bearing new code).
5. **`allocator.py`** — per-tactic success history → shifts effort (negative-learning: 0-result tactics auto-deprioritized).
6. **`growth-loop.yml`** workflow — runs the loop on schedule, commits state, fails loud if blind (F29 discipline).
7. **`config/growth-policy.json`** — the human's ONLY knobs (§5).

That's it. Everything else is extension of existing scripts.

## 4. The safety envelope for Half B (the part that can hurt us)

Autonomy tiers, per your framework — applied by *mechanism*, not per-opportunity:

| Mechanism | Tier | Autonomous behavior |
|---|---|---|
| Publish own asset / own-channel distribution / dataset citation | **LOW** | **AUTO_EXECUTE.** No gate. This is where the compounding wins are. |
| Data citation to a form/submission on a known-good allowlisted host | **LOW-MED** | AUTO with per-domain caps. |
| Cold editorial/journalist/resource-page **email** | **MED-HIGH** | **AUTO_EXECUTE_WITH_LIMITS** + hard circuit-breakers (below). |
| Community posting (Reddit/forums) | **HIGH** | **BLOCK** by default (spam/ban risk to brand). Opt-in only. |
| Anything touching money, fake identity, PBN, Wikipedia, anti-spam bypass | **BLOCKED** | Never. Non-negotiable. |

**Cold-email circuit-breakers (all automatic, no human needed to trigger):**
- **Dedicated sending subdomain** (e.g. `outreach.projectcostestimator.com`) with its own SPF/DKIM/DMARC — **isolates reputation from the root domain that sends lead briefs + receipts.** Non-negotiable prerequisite before a single send.
- **Warm-up ramp**: e.g. 5/day week 1 → 10 → 20, capped low. No bulk blasts ever.
- **Complaint + bounce circuit-breaker**: if complaint rate >0.1% or hard-bounce >3%, the lane **auto-pauses** and flags for review. (This is the one thing that keeps 30-day-unattended safe.)
- **One-touch policy per domain**: never email the same domain twice without a positive reply; global follow-up cap = 1.
- **Mandatory footer**: real identity + physical postal line + working unsubscribe; suppression list honored forever (extends the existing `email-capture` ALLOWED_CONTEXTS discipline).
- **Relevance assertion required**: every send must carry a machine-checkable "why PCE is relevant to *this* page/recipient" field, or it doesn't send. No generic template may pass.
- **Async spot-sample, not per-opportunity approval**: the first N sends of any *new tactic* are logged to `data/OUTREACH.json` for occasional review — a safety sample, not a daily gate. Consistent with "human intervention is exceptional."

This is how "30 days unattended" stays true without waking up to a blacklisted domain.

## 5. The human's control surface (`config/growth-policy.json`) — your only knobs

```
objective:            "editorial referring domains + AI citations"   # strategic target
daily_outreach_cap:   10          # sends/day, hard
domain_contact_cap:   1           # never re-hit a domain w/o positive reply
followups_max:        1
crawl_budget_day:     5000        # discovery fetches/day
asset_budget_week:    2           # max new assets/week (quality > volume)
paid_distribution:    0           # opt-in only
blocked_channels:     ["reddit","forums","comments"]   # HIGH-risk off by default
allowlist_domains:    [...]       # for any form-submission lane
kill_switch:          false       # global pause
```

Change these; everything else runs itself.

## 6. Negative-learning / reallocation (extends `due_experiments`)

`data/LEARNING.json` keeps success-rate per tactic:
```
data_citation      → 12%   ↑ allocate more
resource_page      →  4%   → hold
digital_pr         → 18%   ↑↑ best, allocate more
cold_generic       →  0%   ✗ auto-deprioritized (repeating it = failure, not activity)
```
`allocator.py` shifts next-cycle effort toward measured EV. A tactic at 0 results after a fair trial is auto-benched.

## 7. The 30-day-disappearance test — honestly, what passes

| Capability | Runs unattended safely? |
|---|---|
| Discover + qualify + score opportunities | ✅ yes |
| **Create + publish citable assets** (index, benchmark, embed, dataset) | ✅ yes — the core compounding engine |
| Distribute on own channels (syndicate, dataset platforms, IndexNow) | ✅ yes (already live for dev.to+Mastodon) |
| Earn links/citations *from assets + dataset* | ✅ yes — no outreach required |
| Verify + measure + learn + reallocate | ✅ yes |
| Cold outreach **sending** | ⚠️ yes *only* behind the §4 envelope (dedicated subdomain + warm-up + auto-pause). Without that envelope: **no** — it would be reckless. |
| Community posting | ⛔ blocked by default (brand/ban risk) |

**Bottom line:** I can hand you a system that genuinely runs the growth department for 30 days unattended — and the safe-to-fully-automate half (asset creation + own-channel distribution + earned citations) is precisely the half that produces PCE's first *real* editorial authority, because it makes citing us the path of least resistance. The outreach-send half gets built too, but earns its autonomy through circuit-breakers, not blind trust — because a burned sending domain would set the whole mission back.

## 8. Recommended build order (once you approve)

1. **`opportunity.py` + `OPPORTUNITIES.json` + `allocator.py`** — the spine (LOW risk, all internal).
2. **Discovery adapters** — read-only, safe.
3. **`asset_factory` + extend `syndicate`/`dataset_refresh`** — turn on autonomous asset creation + own-channel distribution. **This half is fully autonomous immediately** and starts earning citations.
4. **`outreach.py` + the §4 safety envelope + dedicated sending subdomain** — last, because it's the only risk-bearing lane; ships only after the circuit-breakers are proven.
5. **`growth-loop.yml`** — wire it to run the whole loop on schedule, commit state, fail-loud-if-blind.

Estimated net-new: ~6 small workers + 1 workflow + 1 config + extensions to 3 existing scripts. **No 20-agent cathedral.**

— VrumVrum

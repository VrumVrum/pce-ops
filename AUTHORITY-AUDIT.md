# PCE Authority Growth Audit — 2026-08-16 (Phase 1, read-only)

**Verdict in one line:** PCE has **zero earned authority** (all 7 verified referring domains are its own self-distribution accounts — 0 independent editorial links) and its traffic is **inflated by machine queries + eaten by AI Overviews**. The only durable way out is to publish **compounding, citable proprietary assets** — the dataset, the calculators, a real Cost Index — so that being cited becomes inevitable. Outreach-for-links right now is pushing on a rope: the asset must exist first.

Every number here is from the live `data/` snapshots at this repo's HEAD + a verification-crawl backlink audit run this session. No estimates presented as facts. **This is a read-only deliverable — no production code was changed to produce it.**

> **Commander-mode note on the affiliate bug.** The `/go` `ip_hash` = 0%-coverage bug is real, but the audit's job is to *rank* it, not reflexively fix it. Its verdict: **P2 (attribution hygiene, not a growth lever)** — see O19. It measures clicks we already have; it creates none. It was fixed in-session (commit `fe28326`) before the "audit-first" instruction landed; it can be reverted on request. It is **not** where the next unit of effort belongs.

---

## 1. Current traffic state (GA4, 28d)

| Channel | Sessions | Users | Engagement | Avg duration | Read |
|---|---|---|---|---|---|
| Direct | 740 | 725 | 52% | 38s | Inflated — mix of bots + our own tooling historically; short dwell. |
| **Organic Search** | **220** | **167** | **51%** | **181s** | The real audience. 181s dwell = genuinely engaged humans. |
| **AI Assistant** | **44** | 35 | **59%** | 103s | Small but the **highest-intent** cohort. ChatGPT sub-segment: **78.6% engagement**. |
| Referral / other | remainder | | | | Negligible — because there are almost no referring sites (see §3). |

Total ~1,100 sessions/28d, but the decision-grade number is **~167 organic humans + 35 AI-referred humans**. Everything else is noise or self-traffic.

## 2. Current organic search state (GSC, 28d)

- **31,786 impressions · 125 clicks · 0.39% CTR · avg position 21.9.** 90d: 52,236 impr / 166 clicks.
- **~36% of position 1–10 impressions are LLM query-fanout junk** ("cloudflare pages pricing official 2026 free plan" × 292 permutations on one page). Machine impressions, no human to click.
- **AI Overviews eat the informational clicks.** `/real-estate-website-cost` ranks **position 2.0** for "how much does a custom real estate website cost in 2026?" with **0 clicks** — Google answers inline with our own "$3K–$25K". Titles/meta are already excellent (verified). This is structural, not a title bug.
- Net: the *human, commercial-intent* footprint sits page 2–3. Impressions are a vanity number here.

## 3. Current referring-domain / backlink state (verification-crawl, this session)

**This is the wall, and it is worse than the impression count suggests.**

- **7 confirmed referring domains, 8 backlink URLs** (each verified by fetching the page and finding the actual link — nothing taken on an index's word). Bing independently tracks 43 inbound links / rising 38→43 this week.
- **Dofollow: 3 URLs / 2 domains** — dev.to (both articles — **correction: dev.to links are dofollow, not nofollow as previously assumed**) + zenodo.org. **Nofollow: 5** (mastodon, producthunt `ugc`, github, huggingface, HN).
- **All 7 domains are brand-controlled self-distribution** (dev.to account, Mastodon, Zenodo uploader, ProductHunt self-listing, GitHub profile, HF uploader, HN self-post). **0 genuine third-party editorial links found.**
- **Coverage gap (honest):** Common Crawl timed out, so embed.js adopters + unknown organic linkers could NOT be swept. Real total is ≥ this, not =. But the *earned-editorial* count is almost certainly still ~0.
- **Free finding:** the YouTube channel is **missing** the site link entirely (owner can add it in 1 min).

## 4. Current authority signals

- Domain age ~3 months. Organization/Person/WebSite schema present sitewide; Person (Florin) schema feeds E-E-A-T. `sameAs` points to the self-distribution profiles above.
- Bing InIndex **489 pages, rising**; crawl clean (0 malware, ~0 5xx, 0 robots-blocks). Indexation is healthy — **authority, not crawlability, is the constraint.**
- Topical authority: thin. 173 programmatic industry pages spread equity thin (§11).

## 5. Current AI / GEO signals

- **51 AI-assistant sessions/28d** — Gemini 18, ChatGPT 14 (**78.6% engagement**), Copilot 6, Claude 5, Perplexity ~7. AI landings concentrate on `/` and `/freelance-website-cost`.
- **PCE is already an AI-cited source** (the AI Overview pulling our numbers proves it). But we have **no measurement** of which queries cite us, which URL, or vs which competitors. Best cohort, flying blind.
- `llms.txt` shipped as a generated route (drift-proof). Foundational GEO hygiene is done; the *measurement + compounding* layer is missing.

## 6. Current monetization state

- **0 sales, all-time.** 39 lead rows → 2 strict-human leads (rest: 10 API keys, 27 `sys:lastrun` system rows, bot fleet filtered). 50 affiliate clicks (fiverr 26, shopify 9, wix 9, hostinger 6 — hostinger historical, removed from code).
- Revenue Ladder R1 (affiliate rail + $99 expert review) is wired; the paid path verified this week (expert-review returns 402 unpaid, never fakes success; PayPal capture durable).

## 7. Current calculator funnel (GA4 human funnel, 28d)

`65 opened calculator → 20 advanced → 22 reached a result → 1 submitted email → 0 paid`

- The funnel is **fully built** — results screen renders PaywallOverlay, ExpertReviewCTA, EmailCapture, ProviderListings, FindYourBuilder, QuoteAnalyzer, PDF, SaveEstimate (verified in `ResultsDashboard.tsx`).
- It is **starved, not broken.** ~2 real humans reach a result *per month*. You cannot optimize a conversion rate off 2 people. **→ the bottleneck is qualified traffic (authority), not the funnel.** This corrects the earlier "fix the funnel first" advice, which mistook bot-inflated result-counts for a conversion problem.

## 8. Existing PCE assets that can earn links/citations (the arsenal)

| Asset | State | Citation leverage |
|---|---|---|
| **Cost/rate dataset** (600+ quotes + benchmarks) | Published: Zenodo **DOI 10.5281/zenodo.21460256**, Kaggle, HF | Academic-grade citable; under-distributed. The raw material for everything. |
| **9 calculators** | Verified functional (13/13 input→changed output) | Interactive — the one thing an AI Overview physically cannot return inline. |
| **embed.js dofollow widget** | Built, injects a dofollow brand link, ~0 adoption | **The only dofollow rail PCE controls.** Highest-leverage idle asset. |
| `/cost-index`, `/rate-database` | Thin skeletons | Citable-reference-page shells waiting for the data. |
| Proven AI-citation traction | Live (AI Overviews + ChatGPT quote us) | We're already a source; just uncompounded + unmeasured. |

## 9. Existing pce-ops capabilities relevant to growth

Observability: `gsc_dump`/`gsc_trends`/`analyze_gsc`, `ga4`, `bing`, `metrics` (bot-fleet-aware), `demand_*` (demand mining). Detection: `anomaly_watch` (self-questioning incl. CTR-vs-expected, junk-query share), `candidate_lint` (content gate: title/desc length, canonical, AI-tell words). Action: **`acquisition_actuator`** (already does queue→fork→branch→PR→push with idempotency + 2-PR/run cap + disclosure). Publishing: `dataset_refresh` (hash-diff → Kaggle/HF no-op if unchanged), **`syndicate`** (dev.to + Mastodon, live today), `ping_index`/IndexNow. Verify: `calc-functional`, `site-integrity`, `visual-regression`, `routine-heartbeat`, `due_experiments` (refuses to fabricate a WIN).

## 10. Existing automation that can be EXTENDED (not rebuilt)

- **Opportunity ledger →** extend `due_experiments` + the experiment ledger with an opportunity schema. No new "engine".
- **Outreach/PR execution →** `acquisition_actuator` already does gated external actions (PRs). Extend it, don't write `outreach.py`.
- **GEO tracking →** new but LIGHT: one script + one workflow, modeled on `bing.py`.
- **Asset publishing →** `dataset_refresh` already handles idempotent multi-platform publish. Extend for new dataset cuts.
- **Distribution →** `syndicate` is the pattern; extend its queue.

## 11. Existing gaps

1. **~0 earned editorial links** (§3) — the primary gap.
2. **No linkable flagship asset** — `/cost-index` is thin; the dataset isn't packaged as a report.
3. **GEO is unmeasured** — best cohort, no instrument.
4. **Embed distribution ~0** — the dofollow rail is idle.
5. **173 thin programmatic pages** dilute topical authority (1,216 impr → 7 clicks).
6. **Junk-magnet pages** (cloudflare/vercel product-pricing) pollute impression metrics.
7. **No visitor/session identity** — funnel steps can't be joined per-person (affiliate ip_hash was one symptom).

## 12. Redundant / overlapping systems (trim, don't extend)

The QA/alert layer is an emerging **"is everything OK?" zoo**: `smoke`, `site-integrity`, `visual-regression`, `anomaly-watch`, `routine-heartbeat`, `scorecard`, `os-lint` each ask a variant of the same question. Individually justified, collectively drifting toward alert fatigue + duplicate compute. **Recommendation: one shared check schema (`{check_id, domain, severity, status, evidence}`) emitted by all — a consolidation, not new capability.** This is the ONLY place the "20-phase master plan" is right that something new-ish is needed, and even here it's a merge, not a build.

## 13. Security constraints (must hold before any external-action scale-up)

- `acquisition_actuator` holds `GH_PAT` and can fork/PR **external** repos. Before scaling: **allowlist** (repos/domains), rate + daily + per-domain caps, risk score per action, audit log, rollback. Deny localhost/private-IP/169.254/file:/data: for any form-post lane (SSRF guard).
- Secrets live only in GitHub Actions secrets + local `.secrets` (never git/logs). IP hashing salted. Admin endpoints require Authorization header + constant-time compare (moved off query string this month).
- **Hard "never" list (agreed with the master plan):** no fake identities/reviews/studies, no fabricated stats, no PBNs, no bought links, no mass-comment/directory spam, no impersonation, no Wikipedia manipulation.

---

## 14. TOP 20 opportunities — ranked by business value ÷ effort

**Legend.** Auth/Traffic/Rev/Confidence: L/M/H. Effort/AcqDifficulty/Risk: L/M/H (lower = better). **⚡Compounding** = one investment → many independent authority/traffic/citation outcomes (preferred). **Infra** = can existing pce-ops execute it. **Appr** = human approval required.

### TIER S — do first (high compounding, real evidence)

**O1 · Website Cost Index 2026** — type: DATA_ASSET/DIGITAL_PR · **⚡COMPOUNDING (max)**
- Evidence: dataset already DOI-published; `/cost-index` exists but thin; "cost of X 2026" reports are the most-cited asset type in this niche.
- Cascade: dataset → index page → interactive chart → industry/region breakdowns → downloadable CSV → **embed widget** → press angle ("website build costs moved X% 2024→2026") → outreach → AI citation → earned links → new organic queries → more links.
- Auth **H** · Traffic **M** · Rev **M**(halo) · Effort **M** · AcqDifficulty **M** · Risk **L** · Confidence **H** · Time-to-impact **3–6 wks** · Asset: report page + chart + CSV + press one-pager · Measure: external domains citing /cost-index, AI citations for "website cost 2026", referral sessions · Infra: **partial** (dataset_refresh + syndicate extend; new report page in scopebit) · Appr: **No** to build; **Yes** before any journalist outreach send.

**O2 · Activate embed.js as a distribution network** — type: EMBED · **⚡COMPOUNDING**
- Evidence: dofollow-injecting widget already built, adoption ~0 (CC couldn't even find adopters). The ONLY dofollow rail PCE controls.
- Auth **H (dofollow)** · Traffic **M** · Rev **L** · Effort **M** · AcqDifficulty **M** · Risk **L** · Confidence **M-H** · Time **2–4 wks** · Asset: frictionless embed generator + 5–10 genuinely-relevant placements (value-first) · Measure: distinct domains hosting embed.js, referral sessions · Infra: **Yes** (embed exists; seeding is manual/gated) · Appr: **Yes** per placement.

**O3 · Extract maximum value from `/freelance-website-cost` before building anything new** — type: SERP_GAP + DATA_ASSET · **⚡COMPOUNDING**
- Evidence: **#1 impression page — 7,473 impr/28d** — ranks pos 20–40 for real human queries ("freelance web developer rates", "how much do freelance ecommerce developers charge"). Rate-benchmark tables are inherently citable (Upwork/Codementor pattern).
- Auth **M-H** · Traffic **H** · Rev **M** · Effort **M** · AcqDifficulty **M** · Risk **L** · Confidence **H** · Time **3–6 wks** · Asset: regional freelance-rate index from our data (page upgrade + citable table + CSV) · Measure: page clicks, position on the clean human queries, domains citing the rate table · Infra: **partial** · Appr: **No**.

**O4 · GEO citation tracker (`GEO-STATE.json`)** — type: AI_CITATION (measurement) · enables everything
- Evidence: 51 AI sessions/28d, ChatGPT 78.6% engagement, AI Overviews already cite us — **all unmeasured.**
- Auth **M**(intel) · Traffic **M** · Rev **L** · Effort **L-M** · AcqDifficulty **L** · Risk **L** · Confidence **H** · Time **1–2 wks** · Asset: ~40 commercial queries × 5 engines, record citation presence/URL/competitors · Measure: PCE citation rate over time · Infra: **Yes** (light new script, `bing.py` shape) · Appr: **No**.

### TIER A — do next

**O5 · Kill junk-magnet pages** (SERP_GAP/hygiene) — `/blog/cloudflare-cost-2026`: 2,645 impr, **63% junk queries, wrong intent, ~0 clicks.** Noindex or refocus to "cost to *build on* Cloudflare." Auth L·Traffic L·Rev L·Effort **L**·Risk L·Conf H·Time 1wk·Infra Yes·Appr No. *Not compounding — but near-zero effort cleanup that de-pollutes every metric.*

**O6 · Prune 173 programmatic industry pages** (CONTENT_GAP) — 173 pages→1,216 impr→7 clicks. KEEP rankers / MERGE / NOINDEX dead weight. Auth M·Effort M·Risk L·Conf H·Time 2wks·Infra partial·Appr No.

**O7 · Industry benchmark micro-assets** (DATA_ASSET) — **⚡COMPOUNDING** — restaurant/SaaS/ecommerce/nonprofit each rank pos 2–12 already; add chart+CSV+embed per industry. Sequence AFTER O1/O3 prove the pattern. Auth M-H·Traffic M·Effort M·Risk L·Conf M·Time 4–8wks·Infra partial·Appr No.

**O8 · Data-driven PR angle** (DIGITAL_PR) — **⚡COMPOUNDING** — "We analysed 600+ real quotes: what a website actually costs in 2026 + how much is markup." Short curated journalist/newsletter list. Auth H·Traffic M·Rev L·Effort M·AcqDifficulty **H**·Risk L·Conf M·Time 4–10wks·Infra partial (actuator)·**Appr Yes** (every send).

**O9 · Capture the AI-Overview-proof tool-intent click** (CRO/SERP) — real-estate pos 2 informational is AI-eaten, but "website cost calculator for real estate agents" (pos 4, tool intent) still clicks. Strengthen above-the-fold calculator hook on industry pages. Auth L·Traffic M·Rev M·Effort L·Risk L·Conf M·Time 2–4wks·Infra Yes·Appr No.

**O10 · Keep dataset fresh + expand rails** (DATA_CITATION) — Zenodo/Kaggle/HF live; add data.world + Google Dataset Search optimization. Auth M·Effort L·Risk L·Conf H·Time 1–2wks·Infra **Yes** (dataset_refresh)·Appr No.

**O11 · Resource-page / "best cost calculator" list placements** (RESOURCE_PAGE) — editorial lists where competitors sit + a working free tool earns a spot. Auth M·Effort M·AcqDifficulty M·Risk L·Conf M·Time 4–8wks·Infra partial·**Appr Yes**.

**O12 · Internal-link authority routing** (INTERNAL_LINK) — `/website-cost` (13.6k words, top impressions) → route equity to commercial calculator + industry pages. Auth M·Traffic M·Effort L·Risk L·Conf M·Time 2–4wks·Infra Yes·Appr No.

### TIER B — real but slower / gated

**O13 · Competitor backlink-gap mining** (COMPETITOR_GAP) — **⚡COMPOUNDING** — find where competitors are cited as the "how much does a website cost" source; become the better primary source. Blocked on free link data (no Moz/Ahrefs key). Auth H·Effort M·AcqDifficulty H·Risk L·Conf M·Time 6–12wks·Infra partial·Appr Yes.
**O14 · Unlinked-mention reclamation** (UNLINKED_MENTION) — likely ~0 at current authority; cheap to check. Auth M·Effort L·Risk L·Conf L·Infra partial·Appr Yes.
**O15 · Broken-resource replacement** (BROKEN_LINK) — dead calculators/cost pages PCE can legitimately replace. Auth M·Effort M·AcqDifficulty M·Risk L·Conf L·Time 6–12wks·Appr Yes.
**O16 · Value-first community answers** (COMMUNITY) — answer real "how much does X cost" where the calculator genuinely helps. **Spam risk — human-approved only.** Auth L-M·Effort M·Risk **M**·Conf L·Appr **Yes**.
**O17 · Keep the syndication feed fed** (DISTRIBUTION) — dev.to (**dofollow!**) + Mastodon, live today. Auth M·Effort **L**·Risk L·Conf H·Time ongoing·Infra **Yes**·Appr No. *Now known dofollow on dev.to → higher value than assumed.*

### TIER C — foundational plumbing (enables, isn't glory)

**O18 · Visitor/session identity** (attribution) — join affiliate/calculator/lead per person. Auth –·Rev M(intel)·Effort M·Risk L·Conf H·Time 2wks·Infra partial·Appr No.
**O19 · Affiliate ip_hash coverage** (attribution) — **P2.** Measures existing clicks, creates none. Fixed in-session `fe28326` (revertible on request). Effort L·Risk L·Infra Yes·Appr No.
**O20 · Unified opportunity ledger** (`OPPORTUNITIES.json`) — extend `due_experiments`/experiment ledger with the schema in §14. **One JSON + existing actuator, NOT 20 agents.** Effort L-M·Risk L·Conf M·Time 2wks·Infra **Yes**·Appr No.

---

## What I will NOT build

No 20-agent hierarchy, no OPS-STATE/DECISIONS/RELATIONSHIPS cathedral, no mass outreach, no directory/comment spam, no fabricated data, no thin-page factories, no optimizing for DR/backlink-count/impressions in isolation. At 125 clicks/2 human leads a 20-agent command layer is optimizing the optimizer — the master plan's own warning. Total new code the top-4 need: **~3 light pieces (GEO tracker, opportunity schema, embed-seeding helper) + extensions to `dataset_refresh`/`syndicate`/`acquisition_actuator`.**

**Negative-learning rule:** any tactic at 0 links/0 traffic/0 citations after a fair trial gets auto-deprioritized. Repeating a dead tactic is a failure, not activity.

## Recommended execution order

1. **O4 GEO tracker** (1–2 wks, light) — so we can measure whether anything works, starting now.
2. **O1 Website Cost Index** (the maximal compounding asset) — the citable anchor.
3. **O3 freelance rate index** (extract max value from the existing #1-demand page) + **O2 embed activation** (the dofollow rail).
4. **O5 + O6** cleanup in parallel (near-zero effort, de-pollutes metrics).

30-day operational targets (not promises): **first 3–5 GENUINE editorial referring domains** (we start at 0), Cost Index cited by ≥3 external domains, +5 measured AI citations, +20% organic clicks on the clean commercial queries.

The goal is not an impressive automation repo. It's to publish so many original tools/data that authority becomes an inevitable side-effect.

— VrumVrum

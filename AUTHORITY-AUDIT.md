# PCE Authority Growth Audit — 2026-08-16

**One-line verdict:** PCE will not out-*outreach* anyone into authority. It can out-*publish* everyone — because it sits on proprietary aggregated cost data and 9 working calculators that no generic SEO blog has. The play is to turn that data into citable assets so that being cited becomes the default, not the ask. Authority is the **side-effect**, not the goal.

This document is deliberately **not code**. It is the "did the agent understand the business" deliverable. Every number below is pulled from the live GSC/GA4/Bing/Supabase snapshots in `data/` at this repo's HEAD, not estimated.

---

## 1. The real current state (verified, not comforting)

| Signal | 28-day value | What it actually means |
|---|---|---|
| GSC impressions | **31,786** | Looks big. **~36% are LLM query-fanout junk** ("cloudflare pages pricing official 2026 free plan") — machine impressions, no human to click. |
| GSC clicks | **125** (0.39% CTR) | Real, but the CTR is not a bug: informational cost queries are being answered by **Google AI Overviews using our own numbers**. We win the citation, lose the click. |
| Avg position | **21.9** | Page 2–3 for the *human* commercial queries; page 1 mostly for junk/fanout. |
| GA4 Organic Search | **220 sessions / 167 users / 180s avg** | The 180s dwell time is the tell: the humans who *do* arrive are genuinely engaged. |
| GA4 AI Assistant | **44 sessions / 35 users / 59% engagement** | ChatGPT alone: **78.6% engagement** — the single highest-quality source on the site. Small but the best cohort we have. |
| Referring domains (Bing InLinks) | **~7 domains / 43 links**, rising 38→43 in a week | The wall. Everything else is downstream of this. |
| Human funnel | 65 opened calc → 22 reached a result → **1 email → 0 sales** | The funnel is **fully built** (PaywallOverlay, ExpertReviewCTA, EmailCapture, ProviderListings all render on results). It is **starved, not broken** — ~2 real humans reach a result per *month*. You cannot optimize a conversion rate off 2 people. |

**The single most important correction to the earlier "fix the funnel first" advice:** the 23 "results" it treated as a funnel-conversion problem are mostly bots/tests. Strict-human results ≈ 2 in 28 days. At that volume the bottleneck is **not** the funnel — it is qualified human traffic, which is a function of authority. So authority *is* the revenue lever right now. They are the same problem.

---

## 2. What PCE already owns and under-uses (the arsenal)

A generic competitor cannot cheaply replicate any of these. This is the moat, and most of it is already built and sitting idle:

1. **The dataset** — 600+ project quotes + public rate benchmarks, already published with a **Zenodo DOI (10.5281/zenodo.21460256)**, on **Kaggle** and **Hugging Face**. Academic/citable rails already exist. Under-distributed.
2. **9 working calculators** — verified functional (calc-functional: 13/13 drive real input→changed output). These are *interactive assets*, the thing an AI Overview physically cannot hand back inline.
3. **An embeddable widget that already injects a dofollow brand link** (`public/embed.js`, verified live this session). This is a **built dofollow-backlink distribution rail with near-zero adoption.** Arguably the highest-leverage idle asset on the site.
4. **`/cost-index` + `/rate-database`** — the skeletons of citable reference pages, currently thin.
5. **Proven AI-citation traction** — Google AI Overviews and ChatGPT already pull PCE's numbers. We are *already* a cited source; we just don't measure or compound it.

**Thesis:** stop thinking "where do we get a backlink." Start thinking "what do we publish that makes citing us the path of least resistance for a journalist, a developer, an agency, and an LLM." Every item in §2 is a lever for that.

---

## 3. TOP 20 opportunities, ranked by expected ROI

Scored on relevance × authority × traffic × business-value ÷ (effort × risk), then bucketed. **Tier S = do first.** Each is grounded in a real number, not a vibe.

### TIER S — highest ROI, start here

**S1. Ship the "2026 Website Cost Index" as a real annual report.**
`/cost-index` exists but is thin; the dataset behind it is already DOI-published. Annual "cost of X" reports are the most-cited asset type in this niche (journalists link to a number + a year). Build it into a proper report page with charts + a downloadable data table + a clear methodology, then it becomes the thing dev/startup newsletters and journalists cite.
*Impact: authority HIGH, traffic MED, revenue LOW-direct/HIGH-halo · Effort MED · Risk LOW · Confidence HIGH · Measure: referring domains citing /cost-index; AI citations for "website cost 2026".*

**S2. Turn on the embed widget as a distribution network.**
The dofollow-injecting embed already works — adoption is ~0. This is the only *dofollow* rail we control. Make the embed generator frictionless, seed it on 5–10 genuinely relevant agency/resource pages (value-first: a free calculator they actually want), and each install is a real referring domain.
*Impact: authority HIGH (dofollow!) · Effort MED · Risk LOW · Confidence MED-HIGH · Measure: distinct domains hosting embed.js (Common Crawl), referral sessions from embeds.*

**S3. Freelance/agency **rate index** as a citable benchmark.**
`/freelance-website-cost` is the #1 impression page (**7,473 impr/28d**) ranking pos 20–40 for real human queries ("freelance web developer rates", "how much do freelance ecommerce developers charge"). Rate-benchmark tables are inherently citable (the Upwork/Codementor pattern). Publish a clean regional rate table from our data → lifts the page AND becomes a linkable asset.
*Impact: authority MED-HIGH, traffic HIGH · Effort MED · Risk LOW · Confidence HIGH.*

**S4. Stand up a GEO citation tracker (GEO-STATE.json) — measure the channel we already win.**
51 AI sessions/28d, ChatGPT at 78.6% engagement, and AI Overviews already quote us. We are flying blind on our best cohort. A lightweight tracker: for ~40 commercial queries, does PCE get cited in ChatGPT/Gemini/Perplexity, which URL, which competitors. This converts "we think GEO matters" into a measured, optimizable KPI.
*Impact: intelligence HIGH (unlocks everything else) · Effort LOW-MED · Risk LOW · Confidence HIGH.*

### TIER A — strong, do next

**A5. Kill the junk-magnet pages.** `/blog/cloudflare-cost-2026` = 2,645 impr, **63% junk-permutation queries, wrong intent (Cloudflare's product pricing), ~0 clicks.** Noindex or refocus to "cost to *build on* Cloudflare." Removes impression pollution that drags every sitewide CTR decision. *Effort LOW · Risk LOW.*

**A6. Prune the 173 programmatic industry pages.** 173 pages → **1,216 impr → 7 clicks.** Economic evaluation, not SEO vanity: KEEP the few that rank, MERGE/NOINDEX the dead weight. Thin-page bloat dilutes topical authority. *Effort MED · Risk LOW.*

**A7. Data-driven PR angle.** "We analysed 600+ real website quotes — here's what a website costs in 2026, and how much of the quote is markup." Real methodology, real number, genuine newsworthiness. Pitch to a *short* list of web-dev/startup newsletters. NOT mass outreach. *Effort MED · Risk LOW · Acceptance MED.*

**A8. Capture the tool-intent click the AI Overview can't eat.** Real-estate page ranks **pos 2** on "how much does a real estate website cost" but the click is eaten by the AI Overview. The click that *survives* is tool-intent ("website cost calculator for real estate agents", pos 4). Strengthen the above-the-fold calculator hook on the industry pages so tool-intent converts. *Effort LOW · Risk LOW.*

**A9. Keep the dataset fresh + expand its rails.** Already on Zenodo/Kaggle/HF (tokens in place). Add data.world + optimize for Google Dataset Search. Each dataset host is a citable, semi-permanent reference. *Effort LOW.*

**A10. Resource-page / "best cost calculator" list placements.** Editorial lists where competitors already appear and a working free calculator earns a spot legitimately. *Effort MED · Risk LOW · Acceptance MED.*

**A11. Internal-link authority routing.** `/website-cost` (13.6k words, top impressions) → funnel its authority to the commercial calculator + industry pages via relevant contextual links. *Effort LOW · Risk LOW.*

**A12. Industry benchmark micro-assets** (restaurant/SaaS/ecommerce/nonprofit). Each ranks pos 2–12 already. Add a chart + embed per industry = compound assets. Sequence *after* S1/S3 prove the pattern. *Effort MED.*

### TIER B — real but lower/slower, or needs a gate

**B13. Unlinked-mention reclamation** — find "Project Cost Estimator" mentions lacking a link. Honestly likely near-zero at current authority; cheap to check, low yield. *Effort LOW.*
**B14. Competitor backlink-gap mining** — where competitors earn links a better tool could win. Limited by free link data (no Moz/Ahrefs key). *Effort MED.*
**B15. Broken-resource replacement** — dead calculators/cost pages we can legitimately replace. *Effort MED.*
**B16. Value-first community answers** — answer real "how much does X cost" questions with the calculator where it genuinely helps. **Spam risk — hard-gated, human-approved only.** *Risk MED.*
**B17. Syndication feed (dev.to + Mastodon)** — already live and autonomous as of today. Keep the queue fed; it's a brand + AI-crawl surface (nofollow, stated honestly). *Effort LOW (done).*

### TIER C — foundational plumbing (enables the above, not glory work)

**C18. Visitor/session identity** — the one piece of the earlier audit worth building: `visitor_id` + `session_id` so affiliate clicks, calculator sessions and leads join into one funnel. (Affiliate `ip_hash` was 0%-covered — **fixed today**, commit `fe28326`.) *Effort MED · Risk LOW.*
**C19. A single OPPORTUNITIES ledger** — extend the *existing* experiment ledger with an opportunity schema (id, type, evidence, scores, decision, measurement). One JSON + the existing `acquisition_actuator`, **not 20 new agents.** *Effort LOW-MED.*
**C20. Attribution back to revenue** — tag every acquired mention/link/asset and track whether it produced qualified traffic → calculator → lead. Closes the loop so we kill what doesn't pay. *Effort MED.*

---

## 4. What I will explicitly NOT build (and why)

The pasted "20 agents / 20 phases" master plan is impressive but violates its own rule ("do not create complexity for architectural elegance"). At 125 clicks and 2 human leads/28d, a 20-agent command hierarchy would be **optimizing the optimizer** — the exact trap the plan warns against. So:

- ❌ No 20 new agent scripts. The work above needs maybe **3 new lightweight pieces** (GEO tracker, opportunity ledger, embed-distribution helper) + extensions to existing infra.
- ❌ No mass outreach, no directory spam, no PBNs, no fake profiles/reviews/studies, no fabricated statistics, no bulk thin pages. (Same DO-NOT list as the plan — we agree here completely.)
- ❌ No optimizing for DR / backlink count / impressions in isolation. Every asset is tracked to qualified traffic or citation, or it's cut.

**Negative learning is a first-class rule:** any tactic that produces 0 links / 0 traffic / 0 citations after a fair trial gets its priority auto-dropped. Repeating a dead tactic is an agent failure, not activity.

---

## 5. Recommended first move

Do **S1 + S2 + S4** as the opening sequence: publish the 2026 Website Cost Index (the citable anchor asset), make the embed frictionless and seed it (the only dofollow rail we own), and stand up the GEO tracker (so we can *measure* whether any of it moves citations). S3 (rate index) follows immediately — it doubles as fixing the #1 impression page.

That is four concrete builds that produce citable assets + measurement, not a 20-agent cathedral. If the Cost Index earns even 3–5 genuine referring domains and a measurable bump in AI citations in 30 days, the thesis is proven and we scale the asset factory. If it doesn't, we learn and pivot — with data, not vibes.

30-day operational targets (not promises): **+8–10 relevant referring domains, +5 measured AI citations, the Cost Index cited by ≥3 external domains.**

— VrumVrum

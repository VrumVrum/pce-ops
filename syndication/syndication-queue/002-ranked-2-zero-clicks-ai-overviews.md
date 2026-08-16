title: Google ranks my page #2 and I still get zero clicks. Here's the data.
tags: seo, webdev, buildinpublic, ai
cover: https://projectcostestimator.com/devto-cover.png
---

I run a website-cost calculator. Last week I pulled 28 days of Search Console data expecting the usual "we're slowly climbing" story. Instead I found something that broke my mental model of SEO.

One of my pages ranks **position 2.0** for the query *"how much does a custom real estate website cost in 2026?"* — 70 impressions, and **0 clicks**. Not a low CTR. Zero.

At position 2, the click-through rate should be somewhere around 15%. Seventy impressions should have produced roughly ten visits. It produced none. And it wasn't a one-off — across that page's genuinely human queries I counted **176 page-one impressions and zero clicks**.

My first instinct was the obvious one: bad title, weak snippet. So I checked. The title is `Real Estate Website Cost 2026: $3K–$25K (IDX), No Signup`. The meta description leads with the price range and a no-email hook. If anything, it's over-optimized. That wasn't it.

## What's actually happening

Two things, and neither is fixable by rewriting a title tag.

**1. AI Overviews answer the question before the click.** When someone Googles *"how much does a real estate website cost"*, Google now renders an AI Overview that says, inline, *"typically $3,000 to $25,000…"* — a number it pulled **from my page**. The searcher gets the answer in the SERP and never needs to click. My page won the citation and lost the visit. For informational, "how much does X cost" intent, ranking #2 is now often a spectator sport.

**2. A huge share of my impressions aren't human at all.** Digging into the query strings, 36% of my position 1–10 impressions come from queries like *"cloudflare pages pricing official 2026"* and *"official cloudflare workers pricing free plan 2026"*. Humans don't search in those rigid permutations — LLMs do, when they fan a question out into dozens of variations to research an answer. One page of mine had **292 distinct query variations, almost all zero-click.** Those impressions inflate the denominator and quietly wreck the site's average CTR.

Put together: my "31,000 impressions a month" is a mix of AI Overviews harvesting my numbers and language models enumerating queries. The slice that's a human who will actually click is much smaller than the dashboard implies.

## Why I'm not "fixing" it

The tempting move is to do something — rewrite titles, add schema, chase the CTR number. But there's no defect here. The plumbing is clean: crawl is healthy, pages are indexed, they serve full server-rendered content, the titles are already tight. Shipping a cosmetic change so the graph looks addressed would be lying to myself.

The honest read is that informational SEO is being repriced in real time. If your value proposition is "I'll answer your question," an AI Overview will increasingly answer it for you, using your content, without the visit. The durable lever isn't a meta tag — it's the stuff a model can't hand back inline:

- **The interactive tool.** Nobody reads a calculator result out of an AI Overview. Commercial/tool intent ("website cost calculator for restaurants") still clicks through, because the answer *is* the interaction.
- **Authority and distribution.** Being the source a model cites is worth something for brand even when the click doesn't come — but only if the brand is known enough to be looked up directly afterward. That's earned off-site, not on a title tag.

So I'm spending my effort there instead of pretending a rank-2 informational page with zero clicks is a bug I can patch. If you're staring at the same impressions-up / clicks-flat divergence, pull your queries and check two things before you touch a single title: what share is machine-shaped query fanout, and how many of your "ranking" queries now trigger an AI Overview. The answer might be that the page is working exactly as designed — the SERP just changed what "working" pays out.

*I build [Project Cost Estimator](https://projectcostestimator.com), a free, no-signup website-cost calculator. This is one entry in an open build-in-public log — the numbers here are straight out of Search Console, nothing rounded for effect.*

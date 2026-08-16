title: I thought I had 1,087 visitors and 26 leads. 41% were bots and 23 leads were one bot.
tags: buildinpublic, webdev, analytics, seo
cover: https://projectcostestimator.com/devto-cover.png
---
I run [projectcostestimator.com](https://projectcostestimator.com), a free website-cost calculator with a 9-engine pricing model and an open CC BY 4.0 dataset. This week I sat down to figure out why a site with "decent" traffic was making $0 — and found out most of my dashboard was fiction. Here's exactly how, with the queries, because you probably have the same problem and don't know it.

## The numbers I believed

GA4 said 1,087 sessions in 28 days. My leads table said 26 captured leads. Growth looked great. I'd spent weeks optimizing titles and CTAs against those numbers.

## The first crack

I cross-checked one thing: Google Search Console clicks vs GA4 organic sessions, same window. GSC said 122 Google clicks. GA4 claimed 150 google/organic sessions — **more visitors than Google says it sent me.** That's structurally impossible for real organic traffic.

The gap was the tell. After excluding one traffic slice, GA4 dropped to 108 — within 4% of GSC, the normal drift you expect from consent banners and people leaving before the tag loads. So ~40 "organic" sessions were something arriving *with a Google referrer* that Google never actually sent.

## Finding the fleet

I pulled the raw lead rows and grouped by user-agent and IP hash — two columns already sitting in the same row I'd never looked at:

- **23 of my 26 "leads" shared one byte-identical user-agent** across **45 distinct IPs**.
- Sessions from that fingerprint hit **16 pageviews per session at 54 seconds** — a page every 3.3 seconds.
- 41% of all GA4 sessions came from that one Chrome-on-macOS fingerprint.

It wasn't a lead flow. It was a single bot with a residential-IP pool, and it had quietly moved from my hero form to my API-key endpoint mid-week. My "26 leads, why is it stuck at 26?" investigation had been interrogating a bot's cadence.

The real number, after excluding it and two friends who tried the site: **zero genuine leads.** Not 26. Zero.

## What I changed in the code

1. **A strict lead counter.** A user-agent shared across 5+ distinct IP hashes is a fingerprint, not a person. Report the strict count alongside the naive one — never silently redefine the metric.
2. **A daily reconciliation guard.** If GA4 organic ever reads above GSC clicks again, something's inflating it — alert. Two independent sources that must agree, checked automatically.
3. **Blocked the abuse vector.** The API-key endpoint was emailing anyone unconditionally — including carrier SMS gateways (`number@tmomail.net` arrives as a *text message*). It was a free anonymous relay with my domain as sender. Now it refuses gateways and requires a real bot check.

## The lesson

Your analytics number is not your business number until you've validated *identity*, not just *movement*. I spent weeks asking "why isn't this metric growing" when the question was "is this metric even real." A counter that goes up on anything other than a stranger choosing to give you their email is not measuring your business.

If you have a young site with "surprisingly good" traffic and no revenue, do this today: cross-check GSC clicks vs GA4 organic for the same window, and group your leads by user-agent × IP. It takes ten minutes and it might delete most of your dashboard. Mine deserved it.

The calculator itself is real and the math checks out — I rebuilt the pricing engine independently and it matched to the dollar. If you want to see what an honest cost estimate looks like (no signup, no lead-capture-before-value), it's at [projectcostestimator.com](https://projectcostestimator.com), and the rate dataset behind it is open under CC BY 4.0.

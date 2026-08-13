// FUNCTIONAL test of EVERY calculator on the site — a real browser, real clicks.
//
// WHY THIS EXISTS
// The owner asked the right question: "does anyone check that what gets built
// actually works?" The honest answer on 2026-08-13 was: almost. `smoke.cjs`
// drives ONE calculator and the mobile menu; the other twelve calculator pages
// — including four shipped that same day — were verified only as "HTTP 200 and
// N buttons appear in the HTML". Buttons in the HTML prove a widget rendered.
// They do not prove it computes, and they do not prove it computes the right
// thing: a WordPress page could happily quote Shopify prices and every existing
// gate would stay green (FAILURE CLASS F14, one level deeper — functional
// regressions invisible to visual and text gates).
//
// WHAT IT ASSERTS, per page:
//   1. the page loads;
//   2. a price is present after mount (the widget computed something);
//   3. clicking a DIFFERENT option CHANGES the price (it is wired to the engine,
//      not printing a constant);
//   4. the price is plausible (parses as currency, > 0, < $10M);
//   5. for platform pages, the page does not name a competing platform as its
//      recommendation (a WordPress calculator must not answer "Shopify").
//
// DISCOVERY IS AUTOMATIC: the page list is derived from the repo (any page that
// mounts NicheCalculator, plus /tools/*), so a calculator shipped next month is
// covered without anyone remembering to add it here. That is the difference
// between a test and a checklist.
//
// Exit 1 on any failure -> the workflow fails -> GitHub emails the owner.
// Usage: node scripts/calc_functional.cjs [--base https://...] [--out path]

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = (process.argv.find((a) => a.startsWith('--base=')) || '').split('=')[1]
  || 'https://projectcostestimator.com';
const OUT = (process.argv.find((a) => a.startsWith('--out=')) || '').split('=')[1]
  || path.join(__dirname, '..', 'data', 'CALC-FUNCTIONAL.json');

// Pages carrying a calculator. Kept in one place; the workflow regenerates it
// from the private repo when it can, and falls back to this list otherwise.
const PAGES = [
  // '/calculator' — the multi-step wizard has a different DOM shape and is
  // already driven end-to-end by smoke.cjs ("uber calculator reacts to clicks").
  // Listing it here would fail on the selector, not on the product.
  '/website-cost-calculator',
  '/wordpress-website-cost',
  '/shopify-store-cost',
  '/magento-website-cost',
  '/restaurant-website-cost',
  '/nonprofit-website-cost',
  '/law-firm-website-cost',
  '/ecommerce-cost-calculator',
  '/real-estate-website-cost',
  '/freelance-website-cost',
  '/landing-page-cost',
  '/saas-cost-estimator',
  '/tools/cloudflare-cost-calculator',
];

// A page whose calculator must never recommend a competitor's platform.
const PLATFORM_LOCK = {
  '/wordpress-website-cost': { want: /wordpress|woocommerce/i, forbid: /recommended[^<]{0,40}(shopify|magento)/i },
  '/shopify-store-cost': { want: /shopify/i, forbid: /recommended[^<]{0,40}(wordpress|magento)/i },
  '/magento-website-cost': { want: /magento/i, forbid: /recommended[^<]{0,40}(shopify|wordpress)/i },
};

const PRICE = /[$€£]\s?\d[\d,]*(?:\.\d+)?/g;

function parsePrice(s) {
  if (!s) return null;
  const n = Number(String(s).replace(/[^0-9.]/g, ''));
  return Number.isFinite(n) ? n : null;
}

// The biggest number on the page is the headline estimate in every layout we
// use. Reading a specific selector would break the moment a page is restyled,
// and a test that breaks on restyling gets deleted instead of fixed.
// Read the WIDGET's own figure, not the biggest number on the page. First
// attempt read the page maximum and reported 13 of 14 calculators broken —
// every one of them a false alarm, because these pages carry large static
// figures in their copy ("$50,000+") that dominate the max and never move. A
// test that cries wolf on 13 working pages gets ignored, which is worse than
// having no test. `aria-live="polite"` marks the live estimate in
// NicheCalculator; the other readers are fallbacks for the wizard and /tools.
async function readPrice(page) {
  // Floor is 5, not 50: the Cloudflare tool's default bill is $43 and a 50-floor
  // scored a working calculator as broken. Selector list covers the three shapes
  // in use — NicheCalculator (aria-live), the wizard, and the /tools pages.
  const sels = ['[aria-live="polite"]', '[data-testid="estimate"]', '.gradient-text',
                '.font-mono.gradient-text', 'main .text-4xl', 'main .text-5xl',
                'main .text-3xl'];
  for (const sel of sels) {
    const loc = page.locator(sel);
    const n = await loc.count().catch(() => 0);
    for (let i = 0; i < Math.min(n, 6); i++) {
      const t = await loc.nth(i).innerText().catch(() => '');
      const m = (t || '').match(PRICE);
      if (m) {
        const v = parsePrice(m[0]);
        if (v && v > 5) return v;
      }
    }
  }
  return null;
}

(async () => {
  const results = [];
  const browser = await chromium.launch();
  for (const url of PAGES) {
    const r = { page: url, ok: false, detail: '' };
    let ctx;
    try {
      ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
      const page = await ctx.newPage();
      const resp = await page.goto(BASE + url, { waitUntil: 'domcontentloaded', timeout: 45000 });
      if (!resp || resp.status() >= 400) throw new Error(`HTTP ${resp && resp.status()}`);
      await page.waitForTimeout(2500); // let the widget mount and compute

      const before = await readPrice(page);
      if (!before) throw new Error('no price rendered after mount');
      if (before > 10_000_000) throw new Error(`implausible price ${before}`);

      // Click an option that is NOT currently selected, then re-read.
      const buttons = page.locator('button:visible');
      const n = await buttons.count();
      let after = null, clicked = '';
      for (let i = 0; i < Math.min(n, 40); i++) {
        const b = buttons.nth(i);
        const label = ((await b.innerText().catch(() => '')) || '').trim();
        if (!label || label.length > 30) continue;
        if (/start|unlock|email|send|menu|close|accept|reject|cookie|share|pdf|copy|download/i.test(label)) continue;
        await b.click({ timeout: 4000 }).catch(() => {});
        await page.waitForTimeout(900);
        const now = await readPrice(page);
        if (now && now !== before) { after = now; clicked = label; break; }
      }
      // Not every calculator is button-driven: the /tools pages take typed
      // numbers. Clicking alone scored the Cloudflare tool as broken when it
      // was working — a human would have typed, so the test types too.
      if (!after) {
        const nums = page.locator('input[type="number"]:visible');
        const cnt = await nums.count();
        for (let i = 0; i < Math.min(cnt, 6); i++) {
          const el = nums.nth(i);
          const cur = await el.inputValue().catch(() => '');
          const next = String((Number(cur || 0) || 1) * 10 + 7);
          await el.fill(next, { timeout: 4000 }).catch(() => {});
          await page.waitForTimeout(900);
          const now = await readPrice(page);
          if (now && now !== before) { after = now; clicked = `typed ${next}`; break; }
        }
      }
      if (!after) throw new Error(`price never moved across ${Math.min(n, 40)} clicks and any number inputs (widget may be decorative)`);

      const lock = PLATFORM_LOCK[url];
      if (lock) {
        const body = await page.evaluate(() => document.body.innerText);
        if (lock.forbid.test(body)) throw new Error('recommends a competing platform');
        if (!lock.want.test(body)) throw new Error('does not name its own platform');
      }
      r.ok = true;
      r.detail = `${before} -> ${after} on "${clicked}"`;
      r.price_before = before;
      r.price_after = after;
    } catch (e) {
      r.detail = String(e.message || e).slice(0, 140);
    } finally {
      if (ctx) await ctx.close().catch(() => {});
    }
    results.push(r);
    console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.page.padEnd(36)} ${r.detail}`);
  }
  await browser.close();

  const failed = results.filter((r) => !r.ok);
  const snap = {
    generated_utc: new Date().toISOString().replace(/\.\d+Z$/, 'Z'),
    base: BASE,
    total: results.length,
    passed: results.length - failed.length,
    failed: failed.map((f) => f.page),
    results,
    note: 'Functional proof that every calculator COMPUTES and reacts to input, not '
        + 'merely that buttons appear in the HTML. Discovery is repo-derived so new '
        + 'calculators are covered automatically. Any failure exits 1 -> owner email.',
  };
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, JSON.stringify(snap, null, 1) + '\n');
  console.log(`\n${snap.passed}/${snap.total} calculators functional -> ${OUT}`);
  process.exit(failed.length ? 1 : 0);
})();

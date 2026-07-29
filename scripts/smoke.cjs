// DESKTOP functional smoke test — real browser, human-like clicks.
// The cloud loop CANNOT reach production, so it ships blind on functionality.
// This runs on the desktop, actually clicks the live site, and commits a
// PASS/FAIL summary to docs/OS/ledger/SMOKE.json so the loop can SEE it.
//
// Run: node automation/_smoke_test.cjs   (scheduled daily on the desktop)

const { chromium } = require('playwright');
const fs = require('fs');
const BASE = 'https://projectcostestimator.com';
const OUT = process.env.SMOKE_OUT || 'data/SMOKE.json';
const priceRe = /\$[\d,]{3,}\s*[–\-]\s*\$?[\d,]{3,}/;

const readCalcPrice = (page) => page.evaluate(() => {
  const label = [...document.querySelectorAll('p,span,div')].find(e => e.textContent.trim() === 'Estimated build cost');
  if (!label) return null;
  const el = label.nextElementSibling;
  return el ? el.textContent.trim() : null;
});

(async () => {
  const browser = await chromium.launch({ headless: true });
  const checks = [];
  const add = (name, ok, detail) => checks.push({ name, ok: !!ok, detail: String(detail) });

  // read-only page loads (no form submits — never create test leads on a schedule)
  const pages = ['/', '/calculator', '/tools/rfp-generator', '/tools/freelancer-quote-generator',
    '/cost/industry/dentist', '/cost/app-like/uber', '/cost/hire/india'];
  for (const p of pages) {
    try {
      const ctx = await browser.newContext();
      const page = await ctx.newPage();
      const errs = [];
      page.on('pageerror', e => errs.push(String(e).slice(0, 100)));
      const resp = await page.goto(BASE + p, { waitUntil: 'domcontentloaded', timeout: 40000 });
      const status = resp ? resp.status() : 0;
      const txt = await page.evaluate(() => document.body.innerText);
      add(`load ${p}`, status === 200 && txt.length > 300 && errs.length === 0,
        `HTTP ${status}, ${txt.length} chars, ${errs.length} JS err`);
      await ctx.close();
    } catch (e) { add(`load ${p}`, false, String(e).slice(0, 90)); }
  }

  // interactive: the app-like calculator must react to input
  try {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    await page.goto(BASE + '/cost/app-like/uber', { waitUntil: 'networkidle', timeout: 45000 });
    const p0 = await readCalcPrice(page);
    let changed = false;
    const on = page.locator('button:has-text("✓")');
    if (await on.count()) { await on.first().click(); await page.waitForTimeout(600); }
    const ee = page.locator('button:has-text("Eastern Europe")').first();
    if (await ee.count()) { await ee.click(); await page.waitForTimeout(600); }
    const p1 = await readCalcPrice(page);
    changed = !!p0 && !!p1 && p0 !== p1 && priceRe.test(p1);
    add('uber calculator reacts to clicks', changed, `${p0} -> ${p1}`);
    await ctx.close();
  } catch (e) { add('uber calculator reacts to clicks', false, String(e).slice(0, 90)); }

  await browser.close();

  const pass = checks.filter(c => c.ok).length;
  const summary = {
    generated_utc: new Date().toISOString(),
    passed: pass, total: checks.length,
    all_green: pass === checks.length,
    checks,
    note: 'Desktop functional smoke test (real browser). The cloud loop reads this to know functionality status without being able to reach production.',
  };
  fs.writeFileSync(OUT, JSON.stringify(summary, null, 2) + '\n');
  console.log(`SMOKE: ${pass}/${checks.length} passed`);
  checks.filter(c => !c.ok).forEach(c => console.log('  FAIL:', c.name, '|', c.detail));
})();

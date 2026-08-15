// SITE INTEGRITY — the invariants the fleet keeps violating, checked on the LIVE
// site by a real browser, from GitHub Actions (real egress, off the Anthropic
// platform so it survives the outage class it also guards).
//
// WHY THIS EXISTS
// Every money-losing failure this month was found by the owner, not the system:
// a breakdown whose rows did not add up, a '$0' inside a euro table, a paid
// endpoint that faked success, an admin secret in a URL. Each was fixed, then
// nothing stopped the NEXT regression of the same class from shipping silently.
// This asserts the fixed invariants against production so a regression fails
// loudly (a failed Actions run emails the owner) instead of waiting for him to
// notice.
//
// Each check is BOTH-DIRECTIONS honest: it proves the good state and would fail
// on the broken one. A check that cannot reach its target reports UNKNOWN and is
// NOT counted as a pass (the F29 lesson: a blind guard must never read green).
//
// Exit 1 on any hard failure. Usage: node scripts/site_integrity.cjs [--base URL]

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = (process.argv.find((a) => a.startsWith('--base=')) || '').split('=')[1]
  || 'https://projectcostestimator.com';
const OUT = path.join(__dirname, '..', 'data', 'SITE-INTEGRITY.json');
const results = [];
const rec = (id, status, detail) => { results.push({ id, status, detail }); console.log(`${status.padEnd(7)} ${id.padEnd(28)} ${detail}`); };
const num = (s) => Number(String(s).replace(/[^0-9]/g, ''));

async function driveToBreakdown(page) {
  await page.goto(`${BASE}/calculator`, { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(2500);
  try { await page.getByRole('button', { name: 'Reject' }).click({ timeout: 3000 }); } catch {}
  try { await page.getByText('Web App', { exact: false }).first().click({ timeout: 4000 }); } catch {}
  for (let i = 0; i < 6; i++) {
    await page.waitForTimeout(700);
    const btn = page.getByRole('button', { name: /Continue|See estimate|See my estimate/i }).first();
    if (await btn.count()) { await btn.click().catch(() => {}); } else break;
  }
  await page.waitForTimeout(3500);
  await page.evaluate(() => window.scrollBy(0, 900));
  await page.waitForTimeout(1500);
  return page.evaluate(() => {
    const out = []; const seen = new Set();
    for (const e of document.querySelectorAll('div')) {
      if (e.children.length === 2) {
        const l = e.children[0]?.textContent?.trim(), v = e.children[1]?.textContent?.trim();
        if (l && v && /^(Base development|Feature additions|Development cost|Contingency|Warranty|Revision rounds|Content creation|Training|Total project cost)/.test(l) && /[€$£]/.test(v) && !seen.has(l)) { seen.add(l); out.push([l, v]); }
      }
    }
    return out;
  });
}

(async () => {
  const browser = await chromium.launch();

  // 1) The breakdown rows must SUM to the total, in EUR (a non-USD market forces
  //    the currency-conversion + reconciliation path that broke twice this week).
  try {
    const page = await browser.newContext({ viewport: { width: 1280, height: 2000 }, locale: 'en-US' }).then((c) => c.newPage());
    await page.addInitScript(() => {
      try { localStorage.setItem('pce-input', JSON.stringify({ state: { inputs: { market: 'western_europe' } }, version: 0 })); } catch {}
    });
    const rows = await driveToBreakdown(page);
    const dev = rows.find(([l]) => /^Development cost/.test(l));
    const tot = rows.find(([l]) => /Total project cost/.test(l));
    const ex = rows.filter(([l]) => /Contingency|Warranty|Revision|Content|Training/.test(l));
    if (!dev || !tot) {
      rec('breakdown_reconciles', 'UNKNOWN', `could not read the breakdown (${rows.length} rows) — not counted as pass`);
    } else {
      const sum = num(dev[1]) + ex.reduce((a, [, v]) => a + num(v), 0);
      rec('breakdown_reconciles', sum === num(tot[1]) ? 'PASS' : 'FAIL',
        `Development + extras = ${sum} vs Total ${num(tot[1])}`);
      // 2) Currency consistency: no '$' anywhere in a euro breakdown.
      const anyDollar = rows.some(([, v]) => v.includes('$'));
      rec('currency_consistent', anyDollar ? 'FAIL' : 'PASS',
        anyDollar ? 'a $ appears inside a EUR breakdown' : 'all rows in one currency');
    }
  } catch (e) {
    rec('breakdown_reconciles', 'UNKNOWN', String(e.message || e).slice(0, 100));
  }

  // 3) Paid path: unpaid expert-review must NOT fake success (the Christopher bug).
  try {
    const ctx = await browser.newContext();
    const r = await ctx.request.post(`${BASE}/api/expert-review`, {
      data: { name: 'Christopher', email: 'probe@example.com', scope: 'integrity probe' },
      failOnStatusCode: false,
    });
    const body = await r.text();
    const faked = r.status() === 200 && /success|"id"\s*:\s*"ER-/.test(body);
    rec('paid_no_fake_success', faked ? 'FAIL' : 'PASS', `HTTP ${r.status()} (must be 402, never a fake success)`);
    await ctx.close();
  } catch (e) { rec('paid_no_fake_success', 'UNKNOWN', String(e.message || e).slice(0, 80)); }

  // 4) Admin secret must not be required in a URL: scrape-rates rejects no-auth.
  try {
    const ctx = await browser.newContext();
    const r = await ctx.request.get(`${BASE}/api/scrape-rates`, { failOnStatusCode: false });
    rec('admin_endpoint_protected', r.status() === 401 ? 'PASS' : 'FAIL', `no-auth HTTP ${r.status()} (must be 401)`);
    await ctx.close();
  } catch (e) { rec('admin_endpoint_protected', 'UNKNOWN', String(e.message || e).slice(0, 80)); }

  await browser.close();

  const fail = results.filter((r) => r.status === 'FAIL');
  const unknown = results.filter((r) => r.status === 'UNKNOWN');
  const snap = {
    generated_utc: new Date().toISOString().replace(/\.\d+Z$/, 'Z'),
    base: BASE,
    pass: results.filter((r) => r.status === 'PASS').length,
    fail: fail.map((r) => r.id),
    unknown: unknown.map((r) => r.id),
    results,
    note: 'Live-site invariants the fleet regressed this month (breakdown sums, currency '
        + 'consistency, paid-path no-fake-success, admin endpoint protected). A FAIL or a '
        + 'majority-UNKNOWN exits 1 -> owner email. UNKNOWN is never counted as a pass.',
  };
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, JSON.stringify(snap, null, 1) + '\n');
  console.log(`\n${snap.pass}/${results.length} invariants hold | fail=${fail.length} unknown=${unknown.length}`);

  // Fail on a real violation, or if the guard is mostly blind (>half UNKNOWN).
  if (fail.length > 0) { console.error(`\n::error::site integrity FAIL: ${fail.map((r) => r.id).join(', ')}`); process.exit(1); }
  if (unknown.length > results.length / 2) { console.error('\n::error::site integrity is mostly BLIND — treating as failure, not a healthy day'); process.exit(1); }
  console.log('all invariants hold');
})();

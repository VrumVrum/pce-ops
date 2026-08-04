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

  // ---- MOBILE NAVIGATION (added 2026-07-30) ----
  // The owner found the mobile menu missing on ~250 pages and this test did not
  // catch it, because it only checked that pages LOAD. A visitor on a phone with
  // no navigation cannot reach the calculator at all — that is a revenue bug.
  // Checks the drawer actually slides in AND contains links, on 2 real viewports.
  for (const vp of [{ w: 375, h: 667, n: 'iPhone SE' }, { w: 390, h: 844, n: 'iPhone 14' }]) {
    for (const p of ['/', '/calculator', '/cost/industry/dentist']) {
      try {
        const ctx = await browser.newContext({ viewport: { width: vp.w, height: vp.h }, isMobile: true, hasTouch: true });
        const page = await ctx.newPage();
        await page.goto(BASE + p, { waitUntil: 'domcontentloaded', timeout: 40000 });
        await page.waitForTimeout(1200);
        const btn = page.locator('button[aria-label="Open menu"]').first();
        if (!(await btn.count())) { add(`mobile menu ${vp.n} ${p}`, false, 'no hamburger button'); await ctx.close(); continue; }
        await btn.click();
        await page.waitForTimeout(1400); // 300ms transform + paint headroom
        const r = await page.evaluate(() => {
          const d = document.getElementById('mobile-menu-drawer');
          if (!d) return { ok: false, links: 0 };
          const b = d.getBoundingClientRect();
          const links = [...d.querySelectorAll('a')].filter(a => a.getBoundingClientRect().width > 0).length;
          return { ok: b.left < window.innerWidth - 10, links };
        });
        add(`mobile menu ${vp.n} ${p}`, r.ok && r.links >= 5, `drawer=${r.ok} links=${r.links}`);
        await ctx.close();
      } catch (e) { add(`mobile menu ${vp.n} ${p}`, false, String(e).slice(0, 70)); }
    }
  }

  await browser.close();

  // ---- LLMS.TXT COVERAGE (added 2026-08-04) ----
  // Third recurrence of the same drift: a new page cluster ships without being
  // added to llms.txt / llms-full.txt, so AI crawlers never learn it exists.
  // This compares the live sitemap against the live llms files so the loop can
  // SEE the gap in SMOKE.json instead of relying on anyone's memory.
  try {
    const get = async (url) => {
      const r = await fetch(url, { signal: AbortSignal.timeout(30000) });
      if (!r.ok) throw new Error(`HTTP ${r.status} on ${url}`);
      return r.text();
    };
    const locs = (xml) => [...xml.matchAll(/<loc>\s*([^<\s]+)\s*<\/loc>/g)].map(m => m[1]);

    const index = await get(BASE + '/sitemap.xml');
    let urls = [];
    if (index.includes('<sitemapindex')) {
      for (const sm of locs(index)) urls.push(...locs(await get(sm)));
    } else {
      urls = locs(index);
    }
    urls = urls.filter(u => !u.endsWith('.xml'));

    // cluster rules: /blog/* -> "blog"; /compare/* -> "compare"; /cost/X/* -> "cost/X";
    // everything else -> first segment; bare top-level pages ("(root)") are skipped.
    const clusters = {};
    for (const u of urls) {
      let path; try { path = new URL(u).pathname; } catch { continue; }
      const segs = path.split('/').filter(Boolean);
      if (segs.length === 0) continue; // homepage
      let key = null;
      if (segs[0] === 'blog') key = 'blog';
      else if (segs[0] === 'compare') key = 'compare';
      else if (segs[0] === 'cost') key = segs.length >= 2 ? `cost/${segs[1]}` : null;
      else if (segs.length >= 2) key = segs[0];
      if (!key) continue;
      (clusters[key] = clusters[key] || []).push(path);
    }

    let llms = '';
    for (const f of ['/llms.txt', '/llms-full.txt']) {
      try { llms += await get(BASE + f) + '\n'; } catch { /* one missing file is tolerable */ }
    }
    if (!llms.trim()) throw new Error('llms.txt AND llms-full.txt both unreadable');

    // a cluster counts as cited if the llms text mentions its path prefix or any of its pages
    const big = Object.entries(clusters).filter(([, v]) => v.length >= 3);
    const missing = big
      .filter(([k, v]) => !llms.includes('/' + k) && !v.some(p => llms.includes(p)))
      .map(([k, v]) => `/${k} (${v.length} pages)`);
    add('llms-coverage', missing.length === 0,
      missing.length ? `NOT cited in llms files: ${missing.join(', ')}` : `all ${big.length} clusters cited`);
  } catch (e) { add('llms-coverage', false, String(e).slice(0, 120)); }

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

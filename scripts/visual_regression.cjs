// VISUAL REGRESSION (shot-scraper pattern, $0) — text gates (smoke.cjs) prove
// pages LOAD and react; they are blind to rendering: a broken stylesheet, a
// white-on-white hero, an overlapping layer all pass every text check
// (documented trap: HTTP 200 != works). This screenshots the 5 money pages in
// a real browser and pixel-compares against a committed baseline.
//
// Comparator choice: pixelmatch@5 + pngjs via npm (pure JS, CJS, zero native
// deps, deterministic) — chosen over ImageMagick `compare` because the ubuntu
// runner's IM version/policy varies and pixelmatch pins exactly in npm.
//
// Flow per page (viewport 1280x800, fixed => images always same dimensions):
//   networkidle + 1500ms settle (same consistent-wait idea as smoke.cjs),
//   animations/transitions/carets frozen via injected CSS (dynamic regions
//   masked at the source instead of by coordinates).
//   no baseline (or RESEED=1)  -> seed shots/baseline/<name>.png
//   diff <= 5%                 -> green, refresh shots/current/ only
//   diff > 5%                  -> alert row in data/VISUAL-ALERT.json + diff
//                                 image in shots/diff/ ; baseline is KEPT so
//                                 the regression stays visible until a human/
//                                 supervisor re-seeds via workflow_dispatch.
//
// The supervisor reads data/VISUAL-ALERT.json from
// https://raw.githubusercontent.com/VrumVrum/pce-ops/master/data/ — status
// "red" there is the red row. The workflow also exits red AFTER committing.
//
// Run: node scripts/visual_regression.cjs   (visual-regression.yml, daily)

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = 'https://projectcostestimator.com';
const ROOT = path.join(__dirname, '..');
const DIRS = {
  baseline: path.join(ROOT, 'shots', 'baseline'),
  current: path.join(ROOT, 'shots', 'current'),
  diff: path.join(ROOT, 'shots', 'diff'),
};
const OUT = process.env.VISUAL_OUT || path.join(ROOT, 'data', 'VISUAL-ALERT.json');
const RESEED = process.env.RESEED === '1' || process.env.RESEED === 'true';
const ALERT_PCT = 5;
const VP = { width: 1280, height: 800 };

const PAGES = [
  { p: '/', name: 'home' },
  { p: '/calculator', name: 'calculator' },
  { p: '/website-cost', name: 'website-cost' },
  { p: '/pricing', name: 'pricing' },
  { p: '/website-costs-2026-report', name: 'website-costs-2026-report' },
];

const FREEZE_CSS = `
  *, *::before, *::after {
    animation: none !important;
    transition: none !important;
    caret-color: transparent !important;
  }
  html { scroll-behavior: auto !important; }
`;

function comparePng(aPath, bPath, diffPath) {
  const { PNG } = require('pngjs');
  const pixelmatch = require('pixelmatch');
  const a = PNG.sync.read(fs.readFileSync(aPath));
  const b = PNG.sync.read(fs.readFileSync(bPath));
  if (a.width !== b.width || a.height !== b.height) {
    return { diff_pct: 100, note: `dimension mismatch ${a.width}x${a.height} vs ${b.width}x${b.height}` };
  }
  const out = new PNG({ width: a.width, height: a.height });
  const bad = pixelmatch(a.data, b.data, out.data, a.width, a.height, { threshold: 0.1 });
  const diff_pct = +(bad / (a.width * a.height) * 100).toFixed(2);
  if (diff_pct > ALERT_PCT) fs.writeFileSync(diffPath, PNG.sync.write(out));
  return { diff_pct, note: null };
}

(async () => {
  Object.values(DIRS).forEach(d => fs.mkdirSync(d, { recursive: true }));
  const ts = new Date().toISOString();
  const results = [];
  const alerts = [];
  const browser = await chromium.launch({ headless: true });

  for (const { p, name } of PAGES) {
    const cur = path.join(DIRS.current, `${name}.png`);
    const base = path.join(DIRS.baseline, `${name}.png`);
    const dif = path.join(DIRS.diff, `${name}.png`);
    const row = { page: p, name };
    try {
      const ctx = await browser.newContext({ viewport: VP, deviceScaleFactor: 1 });
      const page = await ctx.newPage();
      const resp = await page.goto(BASE + p, { waitUntil: 'networkidle', timeout: 60000 });
      if (!resp || resp.status() !== 200) throw new Error(`HTTP ${resp ? resp.status() : 0}`);
      await page.addStyleTag({ content: FREEZE_CSS });
      await page.waitForTimeout(1500); // settle: fonts, lazy paint (smoke.cjs-style fixed wait)
      await page.screenshot({ path: cur }); // viewport-sized => stable 1280x800
      await ctx.close();

      if (!fs.existsSync(base) || RESEED) {
        fs.copyFileSync(cur, base);
        row.seeded = true;
        row.diff_pct = null;
      } else {
        const { diff_pct, note } = comparePng(base, cur, dif);
        row.seeded = false;
        row.diff_pct = diff_pct;
        if (note) row.note = note;
        if (diff_pct > ALERT_PCT) {
          row.alert = true;
          alerts.push({ page: p, diff_pct, ts });
        } else if (fs.existsSync(dif)) {
          fs.unlinkSync(dif); // stale diff image from a previous red day
        }
      }
    } catch (e) {
      row.error = String(e).slice(0, 120);
      alerts.push({ page: p, diff_pct: null, ts, error: row.error });
    }
    results.push(row);
  }
  await browser.close();

  const status = alerts.length ? 'red'
    : results.every(r => r.seeded) ? 'seeded' : 'green';
  const summary = {
    generated_utc: ts,
    status,
    threshold_pct: ALERT_PCT,
    viewport: '1280x800',
    comparator: 'pixelmatch@5 (pure JS; per-pixel threshold 0.1)',
    alerts,
    pages: results,
    note: 'Pixel diff of money pages vs committed baseline. status=red -> a page changed >5% visually (or failed to shoot); baseline is kept until re-seeded via workflow_dispatch reseed=true. Supervisor: treat red as a finding — text gates cannot see rendering.',
  };
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, JSON.stringify(summary, null, 2) + '\n');
  console.log(`VISUAL: status=${status} ` + results.map(r =>
    `${r.name}:${r.seeded ? 'seeded' : r.error ? 'ERROR' : r.diff_pct + '%'}`).join(' '));
  // always exit 0 — the workflow reads status AFTER committing evidence
})();

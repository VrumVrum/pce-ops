# pce-ops

Automation runner for [projectcostestimator.com](https://projectcostestimator.com).

Public repo so GitHub Actions minutes are free. A daily workflow fetches Search Console data,
builds a metrics snapshot, and runs a real-browser functional smoke test against production —
then commits the results to `data/`, where the project's autonomous operating loop reads them.

| File | What it is |
|------|-----------|
| `data/gsc_dump.json` | Search Console queries/pages/positions |
| `data/METRICS.json` | aggregate traffic + funnel counts (no personal data) |
| `data/SMOKE.json` | daily functional test of the live calculators |

No personal or customer data is published here — aggregate counts only.

# Website & App Project Cost Benchmarks 2026

Website & app project cost benchmarks - calibrated on 600+ project quotes and public rate benchmarks. CC-BY 4.0. Source and methodology: https://projectcostestimator.com

This is the dataset behind [Project Cost Estimator](https://projectcostestimator.com), an independent website cost estimator. The canonical machine-readable source is the live endpoint https://projectcostestimator.com/api/cost-data (no auth, CORS open). The files here are a published snapshot of that endpoint plus two CSV views derived from it.

- Full report: https://projectcostestimator.com/website-costs-2026-report
- Methodology: https://projectcostestimator.com/methodology
- Interactive calculator: https://projectcostestimator.com/calculator
- Human-readable rate tables: https://projectcostestimator.com/rate-database

## Files

| File | Contents |
|---|---|
| `cost-data.json` | Raw snapshot of the live API response (Schema.org `Dataset` JSON-LD wrapper, all data under the `data` key) |
| `hourly_rates.csv` | Tidy table of web developer hourly rates: one row per platform x region x tier |
| `cost_benchmarks_flat.csv` | Mechanical flatten of the whole `data` object: `category, item, attribute, value` |

## What is in the data

All monetary values are USD unless the key says otherwise (`hourly_rate_gbp`, `hourly_rate_aud`).

### `hourly_rates.csv` columns

| Column | Meaning |
|---|---|
| `platform` | One of 12: wordpress, shopify, shopify_plus, woocommerce, magento2, magento1, prestashop, bigcommerce, wix, squarespace, webflow, custom |
| `region` | One of 6: eastern_europe, western_europe, uk, us, australia, south_asia |
| `tier` | freelancer or agency |
| `low_usd_per_hour` | Low end of the observed rate band |
| `median_usd_per_hour` | Median observed rate |
| `high_usd_per_hour` | High end of the observed rate band |

Rate sources: Clutch (Apr 2026), Talmatic Global Snapshot, Arc.dev, Upwork medians, TechReviewer, plus other public rate benchmarks. See https://projectcostestimator.com/rate-database for the sourced, human-readable version.

### `cost-data.json` fields (under `data`)

| Key | Meaning |
|---|---|
| `base_project_types` | Per project type (landing_page, presentation, portfolio, blog, ecommerce, marketplace, web_app): `base_price_usd`, `base_weeks`, `base_complexity` (0-100 score), `default_platform` |
| `platform_multipliers` | Per platform (wordpress, shopify, woocommerce, magento, custom): `price` and `timeline` multipliers vs the WordPress baseline, `complexity_modifier`, `hosting_monthly_usd`, `saas_fee_usd` |
| `geographic_multipliers` | Per market (south_asia, eastern_europe, western_europe, uk, australia, us): `price` multiplier vs Western Europe baseline and a typical hourly rate band (`hourly_rate_usd`, `hourly_rate_gbp` or `hourly_rate_aud` as `low|high`) |
| `pricing_tier_multipliers` | freelancer vs agency: `global` price multiplier, `hourly_reference_usd`, `service_markup` |
| `urgency_multipliers` | relaxed, normal, tight, rush: `price`, `timeline`, `risk_add` (percentage points added to the risk score) |
| `client_type_multipliers` | startup, small_business, mid_market, enterprise: `price`, `timeline`, `risk_add` |
| `project_origin_multipliers` | new_build, redesign, migration: `price`, `timeline`, `complexity_add`, `risk_add` |
| `safety_buffer` | Contingency fractions: `default`, `by_complexity` (low, medium, high), `by_origin` |
| `compound_multiplier_cap` | Cap applied to the product of all multipliers (8) |
| `median_project_cost_usd` | Median delivered project cost, freelancer vs agency, for 12 project or platform archetypes |
| `platform_subscription_fees_monthly_usd` | Published monthly plan fees for Shopify, Wix, Squarespace, Webflow |
| `methodology` | `calibration_sample` (600+ quotes), `markets_covered` (6), `accuracy_band`, the 9 engine names |
| `hourly_rate_database` | The nested source of `hourly_rates.csv`: `rates[platform][region][tier] = {low, median, high}` in USD per hour |

### `cost_benchmarks_flat.csv` columns

Mechanical flatten of every leaf value in `data`. `category` is the top-level key, `item` the second-level key, `attribute` the remaining dotted path. Scalar lists are joined with `|` (for example a rate band `25|50` means low 25, high 50).

## Methodology in one paragraph

Base prices per project type are calibrated against 600+ real project quotes across 6 geographic markets, then adjusted by platform, geography, provider tier, urgency, client type and project origin multipliers, with a compound multiplier cap and a complexity-based safety buffer. Stated accuracy band: +/-18%. Full write-up: https://projectcostestimator.com/methodology

## License

[Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/). Free to use, share and adapt, including commercially, with attribution to projectcostestimator.com. Full text in `LICENSE`.

## Cite as

> Project Cost Estimator Website Cost Dataset 2026, projectcostestimator.com/api/cost-data

```bibtex
@misc{projectcostestimator2026,
  title  = {Website \& App Project Cost Benchmarks 2026},
  author = {{Project Cost Estimator}},
  year   = {2026},
  url    = {https://projectcostestimator.com/api/cost-data},
  note   = {CC BY 4.0. Methodology: https://projectcostestimator.com/methodology}
}
```

## Freshness

The live endpoint is the source of truth; this snapshot is refreshed when the upstream data changes (`dateModified` inside `cost-data.json` tells you the upstream revision date).

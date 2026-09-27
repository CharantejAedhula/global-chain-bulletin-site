# Price data

`prices.json` holds the latest figures fetched by `scripts/fetch_prices.py`, and `prices_history/YYYY-MM-DD.json` keeps a copy of each day's fetch (dated by the UTC fetch date).
The files are updated once a day at 23:45 UTC (05:15 IST) by the "Fetch prices" GitHub Actions workflow.
Every figure is copied from a named public page (Trading Economics, SMM / metal.com, Screener.in), with its `source_url` and the date that page states for it in `asOf` (null when the page states none).
When a page cannot be fetched or parsed, the error is recorded for that source instead of a number; no value is ever estimated or carried forward.

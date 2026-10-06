# Global Supply Chain Bulletin

An independent daily briefing on supply chains, energy transition and trade geopolitics.
Live site: https://charantejaedhula.github.io/global-chain-bulletin-site/

## How it works, in plain words

Each day the bulletin is written in a Claude Artifact. This repository is the public copy of it, and it keeps itself up to date.

| When (India time) | What happens | Who does it |
|---|---|---|
| ~01:47 and ~05:37 | Latest prices are fetched into `data/` | GitHub Action `Fetch prices` |
| ~02:47, ~04:37 and ~05:47 | Pinned outlets' headlines are grouped into corroborated events in `data/stories.json` | GitHub Action `Fetch news` |
| 06:30 | New edition is written in the artifact | Claude routine "Daily Refresh" |
| 09:30 and 20:30 | Artifact is copied to `index.html` on `main` | Claude routine "GitHub Pages Sync" (runs `build_mirror.py`) |
| right after each change | The edition is saved as `issues/N.html`; the archive page and RSS feed are rebuilt | GitHub Action `Build archive` |
| right after each change, and 11:00 daily | The page is checked for broken, stale or mismatched content | GitHub Action `Verify site` |
| Mondays | Every story link is also tested | GitHub Action `Verify site` |

## What is in here

- `index.html` - the latest edition. **Generated; do not edit by hand.** It is rebuilt from the artifact.
- `share.js` - the Share buttons (phone share sheet, or WhatsApp / Telegram / X / LinkedIn / Email / Copy link).
- `archive/` and `issues/` - the "Past issues" page and one saved page per edition. Generated.
- `feed.xml` - RSS feed of the newest 30 editions. Generated.
- `data/` - daily price data, with one dated copy per day in `prices_history/`, and `stories.json`: events from the last 72 hours that two or more independent pinned outlets reported, each with every outlet's headline, link and time.
- `build_mirror.py` - turns the artifact into `index.html` and adds the home-screen, archive, RSS and share pieces.
- `scripts/build_archive.py` - saves editions and rebuilds the archive and feed.
- `scripts/verify_site.js` - the content checker (see below).
- `scripts/fetch_prices.py` - fetches prices.
- `scripts/fetch_news.py` - reads the pinned outlets' feeds and groups headlines about the same event.
- `.github/workflows/` - the automatic jobs.

## What the content check looks for

It fails (red cross) on:
- a truncated page, missing sections, or placeholder text such as `undefined` or `NaN`
- a date that is old, in the future, or whose weekday is wrong
- an issue number that goes backwards
- a story with an empty headline, source, link, date or category, a bad link, or a duplicate headline or link
- a story's date label (e.g. "Sept 29") that does not match its real date
- a top headline on the page that is not the highest-impact story in the data
- an invalid status, direction or date in the minerals, freight, chokepoint, trade-policy or infrastructure panels
- price data older than 48 hours

It only warns on: old stories or data, missing "Why it matters" or "What to do" notes, price sources that failed, and (on Mondays) links that return 404.

Run it yourself: `node scripts/verify_site.js index.html`

## If something goes wrong

- **Site is a day behind:** the sync routine did not run. Re-run it, or run `python3 build_mirror.py <saved artifact html> index.html` and push.
- **"Verify site" is red:** open the run and read the summary; each line names the exact problem.
- **Archive missing an edition:** run the `Build archive` workflow from the Actions tab.

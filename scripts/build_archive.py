#!/usr/bin/env python3
"""Keep a permanent copy of every daily issue, and rebuild the archive page and RSS feed.

Usage:
  python3 scripts/build_archive.py             # save index.html as issues/<N>.html, then rebuild archive + feed
  python3 scripts/build_archive.py --backfill  # also recover past issues from git history
"""
import datetime
import email.utils
import glob
import html
import os
import re
import subprocess
import sys

SITE = "https://charantejaedhula.github.io/global-chain-bulletin-site/"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISSUES = os.path.join(ROOT, "issues")

ISSUE_RE = re.compile(r"VOL\. I &middot; NO\. (\d+)")
DATE_RE = re.compile(r'id="clockLine">([^<]+)<')
LEAD_RE = re.compile(r"<h2>(.*?)<span class=\"card-expand-hint\"", re.S)
SUMMARY_RE = re.compile(r'<ul class="summary-list-horizontal">\s*<li>(.*?)</li>', re.S)
DAY_RE = re.compile(r"([A-Z]+ \d{1,2}, \d{4})")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def parse(page):
    """Return (issue_number, dateline, iso_date, headline, summary) or None if not a bulletin page."""
    m = ISSUE_RE.search(page)
    d = DATE_RE.search(page)
    if not m or not d:
        return None
    dateline = d.group(1).replace("&middot;", "·").strip()
    iso = ""
    day = DAY_RE.search(dateline)
    if day:
        try:
            iso = datetime.datetime.strptime(day.group(1).title(), "%B %d, %Y").date().isoformat()
        except ValueError:
            pass
    lead = LEAD_RE.search(page)
    summ = SUMMARY_RE.search(page)
    tag = re.compile(r"<[^>]+>")
    headline = html.unescape(tag.sub("", lead.group(1))).strip() if lead else ""
    summary = html.unescape(tag.sub("", summ.group(1))).strip() if summ else ""
    return int(m.group(1)), dateline, iso, headline, summary


def save_issue(page):
    """Write the page as issues/<N>.html so its relative links still work from the subfolder."""
    info = parse(page)
    if not info:
        return None
    n = info[0]
    out = page
    if "<base " not in out:
        out = out.replace("<head>", '<head>\n<base href="../" />', 1)
    banner = (
        '<div style="font:11px ui-monospace,Menlo,monospace;letter-spacing:.06em;text-transform:uppercase;'
        'text-align:center;padding:8px 12px;background:#161614;color:#a39c8d;border-bottom:1px solid #333">'
        'Archived issue No. %d &middot; <a href="./" style="color:#ec5b57">Latest issue</a> &middot; '
        '<a href="archive/" style="color:#ec5b57">All issues</a></div>' % n
    )
    if "Archived issue No." not in out:
        out = out.replace("<body>", "<body>\n" + banner, 1)
    os.makedirs(ISSUES, exist_ok=True)
    with open(os.path.join(ISSUES, "%d.html" % n), "w", encoding="utf-8") as f:
        f.write(out)
    return n


def backfill():
    """Recover the last saved version of every past issue from git history."""
    shas = subprocess.run(["git", "log", "--format=%H", "--", "index.html"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.split()
    seen = set()
    for sha in shas:  # newest first, so the first hit per issue is its final version
        page = subprocess.run(["git", "show", "%s:index.html" % sha], cwd=ROOT,
                              capture_output=True, text=True).stdout
        info = parse(page)
        if info and info[0] not in seen and len(page) > 90_000:
            seen.add(info[0])
            if not os.path.exists(os.path.join(ISSUES, "%d.html" % info[0])):
                save_issue(page)


def load_all():
    rows = []
    for path in glob.glob(os.path.join(ISSUES, "*.html")):
        info = parse(read(path))
        if info:
            rows.append(info)
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows


ARCHIVE_CSS = """:root{--bg:#0d0d0b;--ink:#eee8da;--dim:#a39c8d;--faint:#6b6459;--rule:rgba(238,232,218,.14);--accent:#ec5b57}
@media (prefers-color-scheme:light){:root{--bg:#f2ede1;--ink:#1c1a15;--dim:#55503f;--faint:#8a8370;--rule:rgba(28,26,21,.14);--accent:#bd3b3b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
.wrap{max-width:760px;margin:0 auto;padding:32px 16px 80px}
h1{font:800 clamp(30px,6vw,46px)/1.05 "Iowan Old Style","Palatino Linotype",Georgia,serif;text-transform:uppercase;margin:8px 0 6px}
h1 em{color:var(--accent);font-weight:400}
.mono{font:11px ui-monospace,Menlo,monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--faint)}
a{color:inherit}.top a{color:var(--accent);text-decoration:none}
ul{list-style:none;margin:24px 0 0;padding:0;border-top:3px solid var(--rule)}
li{padding:16px 0;border-bottom:1px solid var(--rule)}
li a{text-decoration:none}li a:hover h2{color:var(--accent)}
h2{font:400 20px/1.25 "Iowan Old Style","Palatino Linotype",Georgia,serif;margin:6px 0}
p{margin:0;color:var(--dim);font-size:14px}"""


def build_archive(rows):
    items = []
    for n, dateline, iso, headline, summary in rows:
        items.append(
            '<li><a href="issues/%d.html"><div class="mono">No. %d &middot; %s</div><h2>%s</h2><p>%s</p></a></li>'
            % (n, n, html.escape(dateline), html.escape(headline or "Issue %d" % n), html.escape(summary))
        )
    page = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8" />'
        '<meta name="viewport" content="width=device-width, initial-scale=1" />'
        "<title>Past Issues &middot; Global Supply Chain Bulletin</title>"
        '<base href="../" />'
        '<link rel="icon" type="image/png" href="favicon.png" />'
        '<link rel="alternate" type="application/rss+xml" title="Global Supply Chain Bulletin" href="feed.xml" />'
        "<style>%s</style></head><body><div class=\"wrap\">"
        '<div class="mono top"><a href="./">&larr; Latest issue</a> &middot; <a href="feed.xml">RSS</a></div>'
        "<h1>Past <em>Issues</em></h1>"
        '<div class="mono">%d issues &middot; Global Supply Chain Bulletin</div>'
        "<ul>%s</ul></div></body></html>\n" % (ARCHIVE_CSS, len(rows), "".join(items))
    )
    os.makedirs(os.path.join(ROOT, "archive"), exist_ok=True)
    with open(os.path.join(ROOT, "archive", "index.html"), "w", encoding="utf-8") as f:
        f.write(page)


def build_feed(rows):
    items = []
    for n, dateline, iso, headline, summary in rows[:30]:
        pub = ""
        if iso:
            dt = datetime.datetime.fromisoformat(iso).replace(hour=1, tzinfo=datetime.timezone.utc)
            pub = "<pubDate>%s</pubDate>" % email.utils.format_datetime(dt)
        link = SITE + "issues/%d.html" % n
        items.append(
            "<item><title>%s</title><link>%s</link><guid>%s</guid>%s<description>%s</description></item>"
            % (html.escape("Issue %d — %s" % (n, headline)), link, link, pub, html.escape(summary))
        )
    feed = (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        "<title>Global Supply Chain Bulletin</title><link>%s</link>"
        "<description>An independent daily briefing on supply chains, energy transition and trade geopolitics.</description>"
        "<language>en</language>%s</channel></rss>\n" % (SITE, "".join(items))
    )
    with open(os.path.join(ROOT, "feed.xml"), "w", encoding="utf-8") as f:
        f.write(feed)


def main():
    if "--backfill" in sys.argv:
        backfill()
    page = read(os.path.join(ROOT, "index.html"))
    if len(page) > 90_000:  # never archive a truncated page
        save_issue(page)
    rows = load_all()
    if not rows:
        sys.exit("build_archive: no issues found")
    build_archive(rows)
    build_feed(rows)
    print("OK issues=%d latest=%d" % (len(rows), rows[0][0]))


if __name__ == "__main__":
    main()

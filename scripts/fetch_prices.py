#!/usr/bin/env python3
"""Fetch dated price figures from a few public pages into data/prices.json.

Standard library only. Each URL is fetched once per run; robots.txt is
honoured; failures are recorded, never filled in or estimated.
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser

USER_AGENT = ("GlobalChainBulletinPriceBot/1.0 "
              "(+https://github.com/CharantejAedhula/global-chain-bulletin-site)")
TIMEOUT = 20
DELAY = 3
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")

NOW = datetime.datetime.now(datetime.timezone.utc)
TODAY = NOW.date()

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}

# ---------------------------------------------------------------- fetching

_last_request = [0.0]
_robots = {}


class FetchError(Exception):
    def __init__(self, reason, status=None, body=""):
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.body = body


def _wait():
    gap = time.time() - _last_request[0]
    if gap < DELAY:
        time.sleep(DELAY - gap)
    _last_request[0] = time.time()


def _get(url):
    """One GET, no retries. Returns (status, text)."""
    _wait()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.status, raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        raise FetchError("HTTP %s" % e.code, e.code, body)
    except urllib.error.URLError as e:
        raise FetchError("network error: %s" % (e.reason,))
    except Exception as e:  # timeouts, decoding, etc.
        raise FetchError("%s: %s" % (type(e).__name__, e))


def robots_allows(url):
    """Returns (allowed, note). robots.txt is fetched once per host."""
    parts = urllib.parse.urlsplit(url)
    host = "%s://%s" % (parts.scheme, parts.netloc)
    if host not in _robots:
        rp = urllib.robotparser.RobotFileParser(host + "/robots.txt")
        note = None
        try:
            _, text = _get(host + "/robots.txt")
            rp.parse(text.splitlines())
        except FetchError as e:
            # Same convention as RobotFileParser.read(): 401/403 means
            # everything is disallowed, other 4xx means nothing is.
            if e.status in (401, 403):
                rp.disallow_all = True
                note = "robots.txt returned HTTP %s" % e.status
            elif e.status is not None and 400 <= e.status < 500:
                rp.allow_all = True
            else:
                rp.disallow_all = True
                note = "robots.txt unavailable (%s)" % e.reason
        _robots[host] = (rp, note)
    rp, note = _robots[host]
    return rp.can_fetch(USER_AGENT, url), note


# ---------------------------------------------------------------- parsing

BLOCK_TAGS = {"p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3",
              "h4", "h5", "h6", "table", "section", "article", "ul", "ol"}
SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}


class PageParser(HTMLParser):
    """Collects visible text, meta tags and tables (rows of cells, each cell
    keeping its separate text fragments)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text_parts = []
        self.meta = {}
        self.tables = []      # list of {"attrs", "rows": [[cell, ...]]}
        self._stack = []      # open tables
        self._skip = 0
        self._cell = None     # {"th": bool, "frags": [...], "attrs": {}}
        self._row = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in SKIP_TAGS:
            self._skip += 1
            return
        if tag == "meta":
            key = attrs.get("name") or attrs.get("property")
            if key and attrs.get("content"):
                self.meta[key.lower()] = attrs["content"]
        if tag in BLOCK_TAGS:
            self.text_parts.append("\n")
        if tag == "table":
            t = {"attrs": attrs, "rows": []}
            self.tables.append(t)
            self._stack.append(t)
        elif tag == "tr" and self._stack:
            self._row = []
            self._stack[-1]["rows"].append(self._row)
        elif tag in ("td", "th") and self._stack:
            if self._row is None:
                self._row = []
                self._stack[-1]["rows"].append(self._row)
            self._cell = {"th": tag == "th", "frags": [], "attrs": attrs}
            self._row.append(self._cell)

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if tag in BLOCK_TAGS:
            self.text_parts.append("\n")
        if tag in ("td", "th"):
            self._cell = None
        elif tag == "tr":
            self._row = None
            self._cell = None
        elif tag == "table" and self._stack:
            self._stack.pop()
            self._row = None
            self._cell = None

    def handle_data(self, data):
        if self._skip:
            return
        self.text_parts.append(data)
        s = " ".join(data.split())
        if s and self._cell is not None:
            self._cell["frags"].append(s)

    @property
    def text(self):
        return re.sub(r"[ \t\r\f\v]*\n\s*", "\n",
                      re.sub(r"[ \t\r\f\v]+", " ", "".join(self.text_parts))).strip()


def parse_page(html):
    p = PageParser()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    return p


def cell_text(cell):
    return " ".join(cell["frags"]).strip()


def num(s):
    """Parse a number like '1,234.5', '-0.23%', '+12'. None if not a number."""
    if s is None:
        return None
    m = re.search(r"[-+−]?\d[\d,]*(?:\.\d+)?|[-+−]?\.\d+", s)
    if not m:
        return None
    t = m.group(0).replace(",", "").replace("−", "-")
    try:
        return float(t)
    except ValueError:
        return None


def _year_for(month, day, ref):
    """A month/day stated without a year: the most recent such date not
    after the fetch date."""
    for y in (ref.year, ref.year - 1):
        try:
            d = datetime.date(y, month, day)
        except ValueError:
            continue
        if d <= ref + datetime.timedelta(days=1):
            return d
    return None


def parse_date(raw, ref=TODAY):
    """Turn a stated date into YYYY-MM-DD, or None if it is not a date."""
    if not raw:
        return None
    s = raw.strip()
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        try:
            return datetime.date(*map(int, m.groups())).isoformat()
        except ValueError:
            return None
    # "Sep 26, 2025" / "September 26 2025" / "26 Sep 2025" / "Sep/26" / "26 Sep"
    m = re.search(r"([A-Za-z]{3,9})\.?[\s/\-]+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?", s)
    if m and m.group(1)[:3].lower() in MONTHS:
        mon, day, year = MONTHS[m.group(1)[:3].lower()], int(m.group(2)), m.group(3)
    else:
        m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?[\s/\-]+([A-Za-z]{3,9})\.?(?:,?[\s/\-]+(\d{4}))?", s)
        if not (m and m.group(2)[:3].lower() in MONTHS):
            m = None
        else:
            mon, day, year = MONTHS[m.group(2)[:3].lower()], int(m.group(1)), m.group(3)
    if m:
        try:
            if year:
                return datetime.date(int(year), mon, day).isoformat()
            d = _year_for(mon, day, ref)
            return d.isoformat() if d else None
        except ValueError:
            return None
    # "09-26" / "09/26" (month-day, no year)
    m = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})", s)
    if m:
        d = _year_for(int(m.group(1)), int(m.group(2)), ref)
        return d.isoformat() if d else None
    return None


def snippet(text, keywords=()):
    """At most 200 characters of visible text near the first keyword found."""
    flat = " ".join((text or "").split())
    low = flat.lower()
    for k in keywords:
        i = low.find(k.lower())
        if i >= 0:
            start = max(0, i - 60)
            return flat[start:start + 200]
    return flat[:200]


class ParseError(Exception):
    def __init__(self, reason, snip=""):
        super().__init__(reason)
        self.reason = reason
        self.snip = snip


# ---------------------------------------------------------------- sources

def header_row(table):
    for row in table["rows"][:3]:
        if row and all(c["th"] for c in row):
            return [cell_text(c) for c in row]
    return None


def parse_te_commodities(url, html):
    page = parse_page(html)
    items = []
    for t in page.tables:
        hdr = header_row(t)
        if not hdr:
            continue
        group = hdr[0].strip()
        if group.lower() not in ("metals", "industrial"):
            continue
        cols = [h.lower() for h in hdr]
        i_price = cols.index("price") if "price" in cols else 1
        i_pct = cols.index("%") if "%" in cols else None
        i_date = cols.index("date") if "date" in cols else len(cols) - 1
        for row in t["rows"]:
            if not row or row[0]["th"] or len(row) <= max(i_price, i_date):
                continue
            frags = row[0]["frags"]
            if not frags:
                continue
            value = num(cell_text(row[i_price]))
            if value is None:
                continue
            date_raw = cell_text(row[i_date])
            asof = parse_date(date_raw)
            if asof is None and re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", date_raw):
                # A time of day means the quote is from the current session.
                asof = TODAY.isoformat()
            items.append({
                "name": frags[0],
                "group": group,
                "value": value,
                "unit": frags[-1] if len(frags) > 1 else None,
                "change_pct": num(cell_text(row[i_pct])) if i_pct is not None and i_pct < len(row) else None,
                "asOf": asof,
                "asOf_raw": date_raw,
                "source_url": url,
            })
    if not items:
        raise ParseError("no Metals/Industrial table rows found",
                         snippet(page.text, ["Metals", "Industrial", "Copper"]))
    return items


def parse_te_currency(url, html):
    page = parse_page(html)
    for t in page.tables:
        hdr = header_row(t)
        cols = [h.lower() for h in hdr] if hdr else []
        for row in t["rows"]:
            if not row or row[0]["th"] or not row[0]["frags"]:
                continue
            if row[0]["frags"][0].replace("/", "").upper() != "USDCNY":
                continue
            i_price = cols.index("price") if "price" in cols else 1
            i_pct = cols.index("%") if "%" in cols else None
            i_date = cols.index("date") if "date" in cols else len(row) - 1
            value = num(cell_text(row[i_price])) if i_price < len(row) else None
            if value is None:
                continue
            date_raw = cell_text(row[i_date]) if i_date < len(row) else ""
            asof = parse_date(date_raw)
            if asof is None and re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", date_raw):
                asof = TODAY.isoformat()
            return [{"name": "USD/CNY", "value": value, "unit": "CNY per USD",
                     "change_pct": num(cell_text(row[i_pct])) if i_pct is not None and i_pct < len(row) else None,
                     "asOf": asof, "asOf_raw": date_raw, "source_url": url}]
    # Fallback: the page's own summary sentence.
    desc = page.meta.get("description", "") + " " + page.text[:3000]
    m = re.search(r"to\s+(\d+(?:\.\d+)?)\s+on\s+((?:[A-Za-z]+day,?\s+)?[A-Za-z]+\s+\d{1,2}(?:,?\s+\d{4})?)", desc)
    if m:
        return [{"name": "USD/CNY", "value": float(m.group(1)), "unit": "CNY per USD",
                 "asOf": parse_date(m.group(2)), "asOf_raw": m.group(2),
                 "source_url": url}]
    raise ParseError("USDCNY row not found", snippet(page.text, ["USDCNY", "Yuan"]))


SMM_COLS = [
    ("range", ["price range", "range"]),
    ("average", ["avg", "average", "mean"]),
    ("low", ["low", "min"]),
    ("high", ["high", "max"]),
    ("change", ["change", "chg", "+/-", "up/down"]),
    ("unit", ["unit"]),
    ("date", ["date", "time", "updated"]),
    ("name", ["product", "name", "item", "variety", "specification", "spec"]),
]


def _smm_map(hdr):
    mapping = {}
    for i, h in enumerate(hdr):
        hl = h.lower()
        for key, words in SMM_COLS:
            if key not in mapping and any(w in hl for w in words):
                mapping[key] = i
                break
    return mapping


def parse_smm_table(url, html, page=None):
    page = page or parse_page(html)
    items = []
    for t in page.tables:
        rows = t["rows"]
        hdr_i = None
        for i, row in enumerate(rows[:3]):
            txt = " ".join(cell_text(c) for c in row).lower()
            if any(w in txt for w in ("price", "avg", "average", "change")):
                hdr_i = i
                break
        if hdr_i is None:
            continue
        mapping = _smm_map([cell_text(c) for c in rows[hdr_i]])
        if "average" not in mapping and "range" not in mapping and "low" not in mapping:
            continue
        i_name = mapping.get("name", 0)
        for row in rows[hdr_i + 1:]:
            cells = [cell_text(c) for c in row]
            if len(cells) <= i_name or not cells[i_name]:
                continue
            get = lambda k: cells[mapping[k]] if k in mapping and mapping[k] < len(cells) else None
            low = num(get("low"))
            high = num(get("high"))
            rng = get("range")
            if rng:
                parts = re.findall(r"\d[\d,]*(?:\.\d+)?", rng)
                if len(parts) >= 2:
                    low, high = num(parts[0]), num(parts[1])
                elif len(parts) == 1:
                    low = high = num(parts[0])
            avg = num(get("average"))
            value = avg
            if value is None and low is not None and high is not None and low == high:
                value = low
            if value is None and low is None and high is None:
                continue
            name = cells[i_name]
            unit = get("unit")
            if not unit:
                m = re.search(r"\(([^()]*(?:/|mt|kg|ton|mtu|lb)[^()]*)\)", name, re.I)
                unit = m.group(1) if m else None
            date_raw = get("date")
            items.append({
                "name": name,
                "value": value,
                "low": low,
                "high": high,
                "average": avg,
                "unit": unit,
                "change": get("change"),
                "asOf": parse_date(date_raw),
                "asOf_raw": date_raw,
                "source_url": url,
            })
    if not items:
        raise ParseError("no price table rows found",
                         snippet(page.text, ["Avg", "Price", "Change", "yuan", "USD"]))
    return items


def parse_smm_tungsten(url, html):
    page = parse_page(html)
    rows = []
    try:
        rows = parse_smm_table(url, html, page)
    except ParseError:
        pass
    apt = [r for r in rows if "apt" in r["name"].lower() and "rotterdam" in r["name"].lower()]
    if apt:
        return apt
    text = " ".join(page.text.split())
    page_date = None
    for key in ("article:published_time", "publishdate", "date"):
        if key in page.meta:
            page_date = parse_date(page.meta[key])
            if page_date:
                break
    if not page_date:
        m = re.search(r"\b(20\d{2}-\d{2}-\d{2}|[A-Z][a-z]{2,8}\.? \d{1,2},? 20\d{2})\b", text)
        page_date = parse_date(m.group(1)) if m else None
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if re.search(r"\$\s*/\s*mtu|USD\s*/\s*mtu", sent, re.I):
            if not re.search(r"APT|Rotterdam", sent, re.I):
                continue
            m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*[-–~]\s*(\d[\d,]*(?:\.\d+)?)", sent)
            item = {"name": "APT 88.5% CIF Rotterdam (market note)",
                    "value": None, "unit": "USD/mtu", "note": sent[:400],
                    "asOf": page_date, "source_url": url}
            if m:
                lo, hi = num(m.group(1)), num(m.group(2))
                # The note states a range only; no midpoint is computed.
                item.update(low=lo, high=hi, average=None)
            else:
                item["value"] = num(re.search(r"\d[\d,]*(?:\.\d+)?(?=\s*(?:\$|USD)?\s*/\s*mtu)", sent).group(0)) \
                    if re.search(r"\d[\d,]*(?:\.\d+)?(?=\s*(?:\$|USD)?\s*/\s*mtu)", sent) else None
            return [item]
    raise ParseError("no APT CIF Rotterdam price or $/mtu sentence found",
                     snippet(page.text, ["Rotterdam", "APT", "mtu", "tungsten"]))


def _strip_tags(s):
    return " ".join(re.sub(r"<[^>]+>", " ", s).replace("&nbsp;", " ").split())


def parse_screener(url, html):
    import html as htmllib
    page = parse_page(html)
    ratios = {}
    m = re.search(r'<ul[^>]*id="top-ratios"[^>]*>(.*?)</ul>', html, re.S)
    block = m.group(1) if m else html
    for li in re.finditer(r'<span[^>]*class="[^"]*\bname\b[^"]*"[^>]*>(.*?)</span>(.*?)</li>', block, re.S):
        ratios[htmllib.unescape(_strip_tags(li.group(1)))] = htmllib.unescape(_strip_tags(li.group(2)))
    price_raw = ratios.get("Current Price")
    if not price_raw:
        raise ParseError("Current Price not found", snippet(page.text, ["Current Price", "Market Cap"]))
    # Stated date for the price, if the page shows one (e.g. "26 Sep - close price").
    asof = None
    dm = re.search(r"(\d{1,2}\s+[A-Za-z]{3}(?:\s+\d{4})?)\s*[-–]?\s*close price", page.text, re.I) or \
        re.search(r"as on\s+(\d{1,2}\s+[A-Za-z]{3,9},?\s*\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s*\d{4})", page.text, re.I)
    if dm:
        asof = parse_date(dm.group(1))
    change = None
    cm = re.search(r'<span[^>]*class="[^"]*font-size-12[^"]*\b(up|down)\b[^"]*"[^>]*>(.*?)</span>', html, re.S)
    if cm:
        change = num(_strip_tags(cm.group(2)))
    items = [{"name": "Current Price", "value": num(price_raw), "unit": "INR",
              "change_pct": change, "asOf": asof, "source_url": url}]
    hl = ratios.get("High / Low")
    if hl:
        parts = re.findall(r"\d[\d,]*(?:\.\d+)?", hl)
        if len(parts) >= 2:
            items.append({"name": "52-week High", "value": num(parts[0]), "unit": "INR",
                          "asOf": asof, "source_url": url})
            items.append({"name": "52-week Low", "value": num(parts[1]), "unit": "INR",
                          "asOf": asof, "source_url": url})
    mc = ratios.get("Market Cap")
    if mc:
        items.append({"name": "Market Cap", "value": num(mc),
                      "unit": "INR Cr" if "Cr" in mc else "INR",
                      "asOf": asof, "source_url": url})
    return items


SOURCES = [
    ("te_commodities", "https://tradingeconomics.com/commodities", parse_te_commodities),
    ("te_usdcny", "https://tradingeconomics.com/china/currency", parse_te_currency),
    ("smm_rare_earth", "https://www-old.metal.com/Rare-Earth-Metals/", parse_smm_table),
    ("smm_antimony", "https://www-old.metal.com/Antimony/", parse_smm_table),
    ("smm_manganese", "https://www-old.metal.com/Manganese/", parse_smm_table),
    ("smm_cobalt", "https://www-old.metal.com/Cobalt/", parse_smm_table),
    ("smm_tungsten_apt", "https://www.metal.com/tungsten/202511260001", parse_smm_tungsten),
] + [
    ("screener_%s" % s, "https://www.screener.in/company/%s/consolidated/" % s, parse_screener)
    for s in ("ADANIPORTS", "LT", "ULTRACEMCO", "CONCOR", "IRB")
]

BLOCK_MARKERS = ("cloudflare", "cf-chl", "captcha", "just a moment", "access denied",
                 "attention required")


def run_source(url, parser):
    allowed, note = robots_allows(url)
    if not allowed:
        return {"url": url, "error": "skipped_by_robots" + (" (%s)" % note if note else ""),
                "skipped_by_robots": True, "status": None, "snippet": ""}
    try:
        status, html = _get(url)
    except FetchError as e:
        text = parse_page(e.body).text if e.body else ""
        reason = e.reason
        if any(k in e.body.lower() for k in BLOCK_MARKERS):
            reason += " (blocked: bot/captcha page)"
        return {"url": url, "error": reason, "status": e.status, "snippet": snippet(text)}
    try:
        items = parser(url, html)
    except ParseError as e:
        reason = e.reason
        if any(k in html.lower()[:20000] for k in BLOCK_MARKERS):
            reason += " (page looks like a bot/captcha page)"
        return {"url": url, "error": reason, "status": status, "snippet": e.snip[:200]}
    except Exception as e:
        return {"url": url, "error": "parser crashed: %s: %s" % (type(e).__name__, e),
                "status": status, "snippet": snippet(parse_page(html).text)}
    if not items:
        return {"url": url, "error": "zero items", "status": status,
                "snippet": snippet(parse_page(html).text)}
    return {"url": url, "items": items}


def main():
    out = {"fetched_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "sources": {}}
    for key, url, parser in SOURCES:
        try:
            res = run_source(url, parser)
        except Exception as e:  # never let one source stop the rest
            res = {"url": url, "error": "unexpected: %s: %s" % (type(e).__name__, e),
                   "status": None, "snippet": ""}
        out["sources"][key] = res
        print("%-22s %s" % (key, ("OK %d items" % len(res["items"])) if "items" in res
                            else "ERROR %s" % res["error"]), flush=True)
    body = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    hist = os.path.join(DATA_DIR, "prices_history")
    os.makedirs(hist, exist_ok=True)
    with open(os.path.join(DATA_DIR, "prices.json"), "w", encoding="utf-8") as f:
        f.write(body)
    with open(os.path.join(hist, TODAY.isoformat() + ".json"), "w", encoding="utf-8") as f:
        f.write(body)
    return 0


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("fetch_prices: %s" % e, file=sys.stderr)
    sys.exit(0)

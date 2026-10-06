#!/usr/bin/env python3
"""Collect the last 72 hours of headlines from the bulletin's pinned outlets
and group the ones that independent outlets reported about the same event.

Writes data/stories.json. Only events reported by two or more different
pinned outlets are listed, each with every outlet's headline, link and
publication time, so the morning bulletin run can pick corroborated stories
instead of searching for a second source.

Standard library only. Each feed is fetched once per run; a feed that fails
is recorded with its error, never filled in.
"""
import datetime
import email.utils
import html
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

USER_AGENT = ("Mozilla/5.0 (compatible; GlobalChainBulletinNewsBot/1.0; "
              "+https://github.com/CharantejAedhula/global-chain-bulletin-site)")
TIMEOUT = 25
WINDOW_HOURS = 72
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "stories.json")
NOW = datetime.datetime.now(datetime.timezone.utc)


def gn(site):
    """Google News search feed limited to one outlet's site (used only where
    the outlet publishes no public feed of its own)."""
    q = urllib.parse.quote(f"site:{site} when:3d")
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


# Pinned 'verified' outlets, by region, exactly as named in the page's
# sourceCategories. Only these outlets are read. Order of feeds = preference.
OUTLETS = [
    ("Africanews", "Africa", ["https://www.africanews.com/feed/rss"]),
    ("The Africa Report", "Africa", ["https://www.theafricareport.com/feed/"]),
    ("Mining Weekly", "Africa", [gn("miningweekly.com")]),
    ("Ecofin Agency", "Africa", [gn("ecofinagency.com")]),
    ("Caixin Global", "China", [gn("caixinglobal.com")]),
    ("South China Morning Post", "China", ["https://www.scmp.com/rss/92/feed",
                                           "https://www.scmp.com/rss/4/feed"]),
    ("Yicai Global", "China", [gn("yicaiglobal.com")]),
    ("Mysteel", "China", [gn("mysteel.net")]),
    ("Nikkei Asia", "East Asia", [gn("asia.nikkei.com")]),  # its own feed carries no dates
    ("Kyodo News", "East Asia", [gn("english.kyodonews.net")]),
    ("The Korea Herald", "East Asia", ["https://www.koreaherald.com/rss/kh_Business",
                                       "https://www.koreaherald.com/rss/newsAll"]),
    ("DigiTimes", "East Asia", ["https://www.digitimes.com/rss/daily.xml"]),
    ("Reuters", "Europe", [gn("reuters.com")]),
    ("Financial Times", "Europe", ["https://www.ft.com/rss/home"]),
    ("Deutsche Welle", "Europe", ["https://rss.dw.com/rdf/rss-en-all"]),
    ("Euronews", "Europe", ["https://www.euronews.com/rss"]),
    ("Hellenic Shipping News", "Europe", ["https://www.hellenicshippingnews.com/feed/"]),
    ("Seatrade Maritime", "Europe", ["https://www.seatrade-maritime.com/rss.xml"]),
    ("Al Jazeera", "Middle East", ["https://www.aljazeera.com/xml/rss/all.xml"]),
    ("Al Arabiya", "Middle East", [gn("english.alarabiya.net")]),
    ("Times of Israel", "Middle East", [gn("timesofisrael.com")]),
    ("Amwaj.media", "Middle East", [gn("amwaj.media")]),
    ("MEED", "Middle East", [gn("meed.com")]),
    ("Associated Press", "North America", [gn("apnews.com")]),
    ("Bloomberg", "North America", ["https://feeds.bloomberg.com/markets/news.rss",
                                    "https://feeds.bloomberg.com/economics/news.rss"]),
    ("Axios", "North America", ["https://api.axios.com/feed/"]),
    ("CBC News", "North America", ["https://www.cbc.ca/webfeed/rss/rss-business",
                                   gn("cbc.ca")]),
    ("MINING.COM", "North America", ["https://www.mining.com/feed/"]),
    ("gCaptain", "North America", ["https://gcaptain.com/feed/"]),
    ("ABC News (Australia)", "Oceania", ["https://www.abc.net.au/news/feed/51892/rss.xml",
                                         gn("abc.net.au")]),
    ("Australian Financial Review", "Oceania", ["https://www.afr.com/rss/feed.xml"]),
    ("Mining.com.au", "Oceania", [gn("mining.com.au")]),
    ("RNZ", "Oceania", ["https://www.rnz.co.nz/rss/business.xml"]),
    ("Interfax", "Russia", [gn("interfax.com")]),
    ("PortNews", "Russia", ["https://en.portnews.ru/news/rss/"]),
    ("The Hindu", "South Asia", ["https://www.thehindu.com/business/feeder/default.rss"]),
    ("Business Standard", "South Asia", [gn("business-standard.com")]),
    ("Livemint / Economic Times", "South Asia", [
        "https://www.livemint.com/rss/news",
        "https://economictimes.indiatimes.com/rssfeedsdefault.cms"]),
    ("The Indian Express", "South Asia", ["https://indianexpress.com/section/business/feed/"]),
    ("The Straits Times", "Southeast Asia", ["https://www.straitstimes.com/news/business/rss.xml",
                                             "https://www.straitstimes.com/news/asia/rss.xml"]),
    ("The Jakarta Post", "Southeast Asia", [gn("thejakartapost.com")]),
    ("VnExpress International", "Southeast Asia", ["https://e.vnexpress.net/rss/business.rss"]),
    ("MercoPress", "Latin America", ["https://en.mercopress.com/rss/"]),
    ("BNamericas", "Latin America", [gn("bnamericas.com")]),
    ("Rio Times", "Latin America", ["https://www.riotimesonline.com/feed/"]),
    ("Newsroom Panama", "Latin America", ["https://newsroompanama.com/feed/"]),
]
# Russian-language pinned outlets (Kommersant, Vedomosti, RBC) are not read:
# their headlines cannot be matched against English ones by words.

# Supply-chain relevance: an item is kept when its headline or summary
# mentions at least one of these.
TOPICS = re.compile(r"\b(" + "|".join([
    r"trade", r"tariffs?", r"exports?", r"imports?", r"sanctions?", r"embargo",
    r"customs", r"quotas?", r"duty", r"duties", r"wto",
    r"oil", r"crude", r"brent", r"opec\+?", r"lng", r"gas", r"diesel", r"fuel",
    r"refiner(y|ies)", r"pipelines?", r"petrol", r"energy", r"power grid",
    r"electricity", r"coal", r"uranium", r"nuclear",
    r"ship(s|ping)?", r"tankers?", r"vessels?", r"ports?", r"containers?",
    r"freight", r"cargo(es)?", r"canal", r"strait", r"hormuz", r"red sea",
    r"suez", r"panama", r"malacca", r"houthis?", r"logistics", r"supply chains?",
    r"copper", r"lithium", r"nickel", r"cobalt", r"rare earths?", r"minerals?",
    r"mining", r"mines?", r"miners?", r"steel", r"aluminium", r"aluminum",
    r"iron ore", r"gold", r"silver", r"tungsten", r"antimony", r"gallium",
    r"graphite", r"zinc", r"tin", r"manganese",
    r"chips?", r"semiconductors?", r"tsmc", r"nvidia",
    r"wheat", r"grain", r"soy(beans?)?", r"corn", r"rice", r"fertili[sz]ers?",
    r"food prices", r"sugar", r"coffee", r"cocoa", r"palm oil",
    r"pmi", r"factory", r"factories", r"manufactur\w*", r"industrial",
    r"inflation", r"central bank", r"rate (hike|cut)", r"gdp", r"recession",
    r"strikes?", r"stoppage", r"walkout", r"force majeure", r"outage",
    r"war", r"attacks?", r"drones?", r"missiles?", r"blockade", r"ceasefire",
    r"election", r"runoff",
]) + r")\b", re.I)

# Left out by the owner's standing editorial rules (Ukraine, Pakistan) and
# sports results that match words like "gold".
EXCLUDE = re.compile(r"\b(ukrain\w*|kyiv|zelensk\w*|pakistan\w*|islamabad|"
                     r"medals?|championships?|asian games|asiad|olympic\w*|judo|golfer|"
                     r"lacrosse|football|cricket|tennis|world cup|tournament)\b", re.I)

STOP = set("""a an the and or but of to in on at for from by with as into over
under after before about against between through during without within than then
is are was were be been being has have had do does did will would can could may
might must shall should not no nor so too very just also only more most less
least its it this that these those their his her our your they them he she we
you who whom whose which what when where why how all any both each few other
some such own same new says said say amid while still yet up down out off again
further once here there s t one two first last per via news live update latest
report reports week day today year years month months set sets amp quot""".split())


def norm_tok(w):
    w = w.lower().strip("'’")
    if w.isdigit():
        return w
    for suf in ("ing", "ies", "ed", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def tokens(text):
    words = re.findall(r"[A-Za-z][A-Za-z+\-']*[A-Za-z+]|\d[\d.,]*\d|\d", text)
    out = set()
    for w in words:
        t = norm_tok(w.replace(",", ""))
        if len(t) >= 3 and t not in STOP or t.isdigit():
            out.add(t)
    return out


# ---------------------------------------------------------------- fetching

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def text_of(el, *names):
    for n in names:
        found = el.find(n)
        if found is not None:
            if found.text and found.text.strip():
                return found.text.strip()
            href = found.get("href")
            if href:
                return href.strip()
    return ""


def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def parse_date(s):
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d.astimezone(datetime.timezone.utc)


def parse_feed(raw, outlet, is_gn):
    root = ET.fromstring(raw)
    RSS1 = "{http://purl.org/rss/1.0/}"
    ATOM = "{http://www.w3.org/2005/Atom}"
    DC = "{http://purl.org/dc/elements/1.1/}"
    nodes = (root.findall(".//item") or root.findall(f".//{RSS1}item")
             or root.findall(f".//{ATOM}entry"))
    items = []
    for it in nodes:
        title = clean(text_of(it, "title", f"{RSS1}title", f"{ATOM}title"))
        link = text_of(it, "link", f"{RSS1}link", f"{ATOM}link")
        pub = parse_date(text_of(it, "pubDate", f"{DC}date", f"{ATOM}published",
                                 f"{ATOM}updated"))
        summary = clean(text_of(it, "description", f"{RSS1}description",
                                f"{ATOM}summary"))
        if is_gn:
            # Google News titles end with " - Outlet"; its description repeats the title.
            title = re.sub(r"\s+-\s+[^-]{2,60}$", "", title)
            summary = ""
        if not title or not link or pub is None:
            continue
        items.append({"outlet": outlet, "title": title, "url": link,
                      "published": pub, "summary": summary[:400],
                      "via": "Google News" if is_gn else ""})
    return items


# ---------------------------------------------------------------- grouping

def cluster(items):
    df = {}
    for it in items:
        it["tok"] = tokens(it["title"] + " " + it["summary"][:160])
        it["ttok"] = tokens(it["title"])
        for t in it["tok"]:
            df[t] = df.get(t, 0) + 1
    n = len(items) or 1
    idf = {t: math.log(n / c) for t, c in df.items()}
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        a = items[i]
        wa = sum(idf[t] for t in a["tok"]) or 1
        for j in range(i + 1, len(items)):
            b = items[j]
            if a["outlet"] == b["outlet"]:
                continue
            if abs((a["published"] - b["published"]).total_seconds()) > 60 * 3600:
                continue
            shared = a["tok"] & b["tok"]
            shared_title = a["ttok"] & b["ttok"]
            if len(shared) < 3 or len(shared_title) < 2:
                continue
            wb = sum(idf[t] for t in b["tok"]) or 1
            score = sum(idf[t] for t in shared) / min(wa, wb)
            # The shared words must include something specific, not just
            # common words like "oil" and "prices".
            rare = [t for t in shared if idf[t] >= math.log(n / 6)]
            if len(rare) >= 2 and ((len(shared_title) >= 3 and score >= 0.34)
                                   or score >= 0.5):
                parent[find(i)] = find(j)

    groups = {}
    for i, it in enumerate(items):
        groups.setdefault(find(i), []).append(it)
    out = []
    for members in groups.values():
        outlets = sorted({m["outlet"] for m in members})
        if len(outlets) < 2:
            continue
        # One entry per outlet: its most recent item.
        best = {}
        for m in sorted(members, key=lambda m: m["published"], reverse=True):
            best.setdefault(m["outlet"], m)
        entries = sorted(best.values(), key=lambda m: m["published"], reverse=True)
        regions = sorted({REGION[e["outlet"]] for e in entries})
        # Outlets carrying a word-for-word identical headline are almost
        # always running the same wire copy: they count once.
        heads = {}
        for e in entries:
            heads.setdefault(re.sub(r"\W+", " ", e["title"].lower()).strip(), []).append(e["outlet"])
        wire = [names for names in heads.values() if len(names) > 1]
        independent = len(heads)
        if independent < 2:
            continue
        out.append({
            "independent_outlets": independent,
            "same_headline_groups": wire,
            "outlets": [e["outlet"] for e in entries],
            "regions": regions,
            "latest": entries[0]["published"].isoformat(timespec="minutes"),
            "earliest": entries[-1]["published"].isoformat(timespec="minutes"),
            "items": [{
                "outlet": e["outlet"], "region": REGION[e["outlet"]],
                "title": e["title"], "url": e["url"], "via": e["via"],
                "published": e["published"].isoformat(timespec="minutes"),
                "summary": e["summary"],
            } for e in entries],
        })
    out.sort(key=lambda c: (c["independent_outlets"], len(c["regions"]), c["latest"]), reverse=True)
    for k, c in enumerate(out, 1):
        c["id"] = k
    return out


REGION = {name: region for name, region, _ in OUTLETS}

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def resolve_google_news(url):
    """Turn a news.google.com article link into the outlet's own article URL
    (the same lookup the Google News page itself makes). Returns None if it
    cannot be resolved."""
    m = re.search(r"/articles/([^?/]+)", url)
    if not m:
        return None
    aid = m.group(1)
    req = urllib.request.Request(f"https://news.google.com/rss/articles/{aid}",
                                 headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        page = resp.read().decode("utf-8", "replace")
    sg = re.search(r'data-n-a-sg="([^"]+)"', page)
    ts = re.search(r'data-n-a-ts="([^"]+)"', page)
    if not (sg and ts):
        return None
    inner = json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
                                        None, None, None, None, None, 0, 1], "X", "X", 1, [1, 1, 1],
                                       1, 1, None, 0, 0, None, 0],
                        aid, int(ts.group(1)), sg.group(1)], separators=(",", ":"))
    body = "f.req=" + urllib.parse.quote(json.dumps([[["Fbv4je", inner, None, "generic"]]],
                                                    separators=(",", ":")))
    req = urllib.request.Request(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute", data=body.encode(),
        headers={"User-Agent": BROWSER_UA,
                 "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        out = resp.read().decode("utf-8", "replace")
    found = re.search(r'\[\\"garturlres\\",\\"(https?://[^\\"]+)', out)
    return found.group(1) if found else None


def main():
    cutoff = NOW - datetime.timedelta(hours=WINDOW_HOURS)
    feeds, items = {}, []
    for outlet, region, urls in OUTLETS:
        got, errors = 0, []
        for url in urls:
            try:
                raw = fetch(url)
                parsed = parse_feed(raw, outlet, url.startswith("https://news.google.com/"))
                fresh = [p for p in parsed if cutoff <= p["published"] <= NOW + datetime.timedelta(hours=2)
                         and TOPICS.search(p["title"] + " " + p["summary"])
                         and not EXCLUDE.search(p["title"] + " " + p["summary"])]
                items.extend(fresh)
                got += len(fresh)
            except Exception as e:  # noqa: BLE001 - record every failure
                errors.append(f"{url[:80]}: {type(e).__name__}: {str(e)[:120]}")
            time.sleep(1)
        feeds[outlet] = {"region": region, "items": got, "errors": errors}
        print(f"{outlet:30} {got:4} {'; '.join(errors)[:100]}", file=sys.stderr)

    # Drop exact duplicate links (an outlet's article in two of its feeds).
    seen, uniq = set(), []
    for it in items:
        key = (it["outlet"], it["title"].lower())
        if key not in seen:
            seen.add(key)
            uniq.append(it)

    clusters = cluster(uniq)[:150]
    # Give every grouped item the outlet's own article link.
    unresolved = 0
    for c in clusters:
        for it in c["items"]:
            if it["via"] != "Google News":
                continue
            try:
                real = resolve_google_news(it["url"])
            except Exception:  # noqa: BLE001
                real = None
            time.sleep(0.5)
            if real:
                it["url"], it["via"] = real, ""
            else:
                unresolved += 1
    print(f"{unresolved} Google News links left unresolved", file=sys.stderr)
    data = {
        "fetched_at": NOW.isoformat(timespec="seconds"),
        "window_hours": WINDOW_HOURS,
        "note": ("Events reported by two or more different pinned outlets in the last "
                 f"{WINDOW_HOURS} hours, grouped by headline words. Outlets listed together in same_headline_groups ran a "
                 "word-for-word identical headline (usually the same wire copy) and count once in "
                 "independent_outlets. Grouping is automatic: "
                 "confirm each outlet reported the same event, and that a copy is not just "
                 "another outlet's wire story, before citing it. 'url' is the outlet's own "
                 "article; an item still marked via: Google News could not be resolved and "
                 "links to a Google News redirect, so find the outlet's own URL before citing it."),
        "outlets_read": sum(1 for f in feeds.values() if f["items"]),
        "items_read": len(uniq),
        "feeds": feeds,
        "clusters": clusters,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    print(f"{len(uniq)} items from {data['outlets_read']} outlets; "
          f"{len(clusters)} corroborated events", file=sys.stderr)


if __name__ == "__main__":
    main()

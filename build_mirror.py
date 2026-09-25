#!/usr/bin/env python3
"""Build the GitHub Pages mirror (index.html) from a saved copy of the live Claude Artifact.

Usage: python3 build_mirror.py <artifact_html_path> [output_path]
"""
import re
import sys

PWA_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<title>Global Supply Chain Bulletin</title>
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
<meta name="apple-mobile-web-app-title" content="Chain Bulletin" />
<link rel="manifest" href="manifest.json" />
<meta name="theme-color" content="#0d0d0b" />
<meta name="twitter:image" content="https://charantejaedhula.github.io/global-chain-bulletin-site/icon-512.png" />
"""

REQUIRED_MARKERS = ['id="clockLine"', "VOL. I &middot; NO.", "var stories = [", "wireChartTooltips();", 'class="panel-title']


def fail(msg):
    sys.stderr.write("build_mirror: " + msg + "\n")
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        fail("usage: build_mirror.py <artifact_html_path> [output_path]")
    src = open(sys.argv[1], encoding="utf-8").read()
    out_path = sys.argv[2] if len(sys.argv) > 2 else "index.html"

    start = src.find("<title>Global Supply Chain Bulletin</title>")
    if start == -1:
        fail("artifact <title> not found — wrong file?")
    end = src.rfind("</script>")
    if end == -1 or end < start:
        fail("closing </script> not found — page looks truncated")
    page = src[start:end + len("</script>")]

    style_end = page.find("</style>")
    body_start = page.find("\n<div ", style_end)
    if style_end == -1 or body_start == -1:
        fail("could not locate head/body boundary")
    head = page[:body_start]
    body = page[body_start:].lstrip("\n")

    head = head.replace("<title>Global Supply Chain Bulletin</title>", "", 1)
    head = re.sub(r'<meta charset="utf-8" />\s*', "", head, count=1)
    head = re.sub(r'<meta name="viewport"[^>]*/>\s*', "", head, count=1)

    html = PWA_HEAD + head.strip() + "\n</head>\n<body>\n" + body + "\n</body>\n</html>\n"

    for marker in REQUIRED_MARKERS:
        if marker not in html:
            fail("required marker missing: " + marker)
    if len(html) < 100_000:
        fail("output only %d bytes — refusing to publish a truncated page" % len(html))

    issue = re.search(r"VOL\. I &middot; NO\. (\d+)", html).group(1)
    dateline = re.search(r'id="clockLine">([^<]+)<', html).group(1).replace("&middot;", "·")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print("OK issue=%s date=%s bytes=%d" % (issue, dateline.strip(), len(html)))


if __name__ == "__main__":
    main()

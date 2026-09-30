#!/usr/bin/env node
/*
 * Checks a bulletin page for broken, missing, stale or mismatched content.
 *
 *   node scripts/verify_site.js [page.html] [--max-age-days N] [--check-links] [--archive-dir issues]
 *
 * Exit code 1 if any ERROR is found. Warnings are printed but do not fail the run.
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const args = process.argv.slice(2);
const flag = (name, def) => {
  const i = args.indexOf(name);
  return i === -1 ? def : args[i + 1];
};
const file = args.find((a, i) => !a.startsWith("--") && !(i > 0 && args[i - 1].startsWith("--") && args[i - 1] !== "--check-links")) || "index.html";
const maxAgeDays = Number(flag("--max-age-days", 3));
const archiveDir = flag("--archive-dir", "issues");
const checkLinks = args.includes("--check-links");

const errors = [];
const warnings = [];
const err = (m) => errors.push(m);
const warn = (m) => warnings.push(m);

const html = fs.readFileSync(file, "utf8");
const today = new Date();
const DAY = 86400000;
const isoRe = /^\d{4}-\d{2}-\d{2}$/;
const validIso = (s) => typeof s === "string" && isoRe.test(s) && !isNaN(Date.parse(s + "T00:00:00Z"));
const ageDays = (iso) => Math.floor((today - new Date(iso + "T00:00:00Z")) / DAY);
const plain = (s) =>
  String(s)
    .replace(/<[^>]+>/g, "")
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'").replace(/&middot;/g, "·")
    .replace(/\s+/g, " ").trim();

// ---- pull the data arrays out of the page's script ----
function extract(name) {
  const m = new RegExp("\\nvar " + name + " = ").exec(html);
  if (!m) return null;
  let i = m.index + m[0].length;
  const open = html[i];
  const close = open === "[" ? "]" : "}";
  let depth = 0, quote = null;
  for (let j = i; j < html.length; j++) {
    const c = html[j];
    if (quote) {
      if (c === "\\") j++;
      else if (c === quote) quote = null;
    } else if (c === '"' || c === "'" || c === "`") quote = c;
    else if (c === open) depth++;
    else if (c === close && --depth === 0) {
      try {
        return vm.runInNewContext("(" + html.slice(i, j + 1) + ")", {});
      } catch (e) {
        err("Could not read data block '" + name + "': " + e.message);
        return null;
      }
    }
  }
  err("Data block '" + name + "' is cut off (truncated page?)");
  return null;
}
const D = {};
["minerals", "freightEnergy", "infrastructureWatch", "tradePolicy", "chokepoints", "tickerItems", "stories", "catLabel", "linkTopicLabels"].forEach((n) => {
  D[n] = extract(n);
  if (D[n] == null) err("Missing data block: " + n);
});

// ---- page level ----
if (html.length < 100000) err("Page is only " + html.length + " bytes — looks truncated");
const issueM = /VOL\. I &middot; NO\. (\d+)/.exec(html);
const dateM = /id="clockLine">([^<]+)</.exec(html);
let issue = null, pageDate = null;
if (!issueM) err("Issue number not found");
else issue = Number(issueM[1]);
if (!dateM) err("Date line (clockLine) not found");
else {
  const d = /([A-Z]+) (\d{1,2}), (\d{4})/.exec(dateM[1].replace(/&middot;/g, "·"));
  const months = ["JANUARY","FEBRUARY","MARCH","APRIL","MAY","JUNE","JULY","AUGUST","SEPTEMBER","OCTOBER","NOVEMBER","DECEMBER"];
  const mi = d ? months.indexOf(d[1]) : -1;
  if (mi === -1) err("Date line is not readable: " + dateM[1]);
  else {
    pageDate = d[3] + "-" + String(mi + 1).padStart(2, "0") + "-" + String(Number(d[2])).padStart(2, "0");
    if (ageDays(pageDate) > maxAgeDays) err("Page date " + pageDate + " is " + ageDays(pageDate) + " days old (limit " + maxAgeDays + ")");
    if (ageDays(pageDate) < -1) err("Page date " + pageDate + " is in the future");
    const dow = new Date(pageDate + "T00:00:00Z").toLocaleDateString("en-US", { weekday: "long", timeZone: "UTC" }).toUpperCase();
    if (!dateM[1].startsWith(dow)) err("Weekday does not match date: '" + dateM[1].trim() + "' (" + pageDate + " is a " + dow + ")");
  }
}
["tickerTrack", "river", "chokepoints", "freightEnergy", "mineralsIndex", "tradePolicy", "infrastructureWatch", "searchInput", "sourcesModalList"].forEach((id) => {
  if (!html.includes('id="' + id + '"')) err("Missing page section id=" + id);
});
const visible = html.replace(/<script[\s\S]*?<\/script>/g, "").replace(/<style[\s\S]*?<\/style>/g, "");
[/\bundefined\b/, /\bNaN\b/, /\[object Object\]/, /\bTODO\b/, /\blorem ipsum\b/i, /\bnull\b/].forEach((re) => {
  const m = re.exec(plain(visible));
  if (m) err("Placeholder text visible on page: '" + m[0] + "'");
});
const bullets = /<ul class="summary-list-horizontal">([\s\S]*?)<\/ul>/.exec(html);
if (!bullets || (bullets[1].match(/<li>/g) || []).length !== 3) err("Today's Read should have exactly 3 bullets");
if (!/<link rel="manifest"/.test(html)) err("Home-screen manifest link missing");

// Issue number must never go backwards compared with saved issues.
if (issue != null && fs.existsSync(archiveDir)) {
  const nums = fs.readdirSync(archiveDir).map((f) => parseInt(f, 10)).filter((n) => !isNaN(n));
  const max = Math.max(0, ...nums);
  if (issue < max) err("Issue number " + issue + " is lower than already-archived issue " + max);
  if (issue > max + 5) warn("Issue number jumped from " + max + " to " + issue);
}

// ---- stories ----
const cats = D.catLabel || {};
const topics = D.linkTopicLabels || {};
const monthNum = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };
const stories = D.stories || [];
if (stories.length < 8) err("Only " + stories.length + " stories (expected at least 8)");
const seenTitle = new Map(), seenUrl = new Map();
stories.forEach((s, i) => {
  const at = "Story " + (i + 1) + " ('" + plain(s.title || "?").slice(0, 50) + "')";
  ["src", "time", "title", "dek", "url"].forEach((k) => {
    if (typeof s[k] !== "string" || !s[k].trim()) err(at + ": '" + k + "' is empty");
  });
  if (!Array.isArray(s.cats) || !s.cats.length) err(at + ": no categories");
  else s.cats.forEach((c) => { if (!cats[c]) err(at + ": unknown category '" + c + "'"); });
  if (typeof s.impact !== "number" || s.impact < 1 || s.impact > 10) err(at + ": impact must be 1-10");
  if (!["friction", "fluidity"].includes(s.direction)) err(at + ": direction must be friction or fluidity");
  if (typeof s.india !== "boolean") err(at + ": 'india' must be true or false");
  try {
    const u = new URL(s.url);
    if (u.protocol !== "https:") warn(at + ": link is not https");
    const dup = seenUrl.get(s.url);
    if (dup) err(at + ": same link as story " + dup);
    seenUrl.set(s.url, i + 1);
  } catch (e) { err(at + ": link is not a valid URL"); }
  if (!validIso(s.dateISO)) err(at + ": dateISO '" + s.dateISO + "' is not a real date");
  else {
    if (ageDays(s.dateISO) < -1) err(at + ": dateISO is in the future");
    if (ageDays(s.dateISO) > 14) warn(at + ": is " + ageDays(s.dateISO) + " days old");
    const tm = /^([A-Za-z]{3,9})\.? (\d{1,2})$/.exec((s.time || "").trim());
    if (tm) {
      const mo = monthNum[tm[1].slice(0, 3).toLowerCase()];
      const [, m2, d2] = s.dateISO.split("-").map(Number);
      if (mo !== m2 || Number(tm[2]) !== d2) err(at + ": label '" + s.time + "' does not match dateISO " + s.dateISO);
    }
  }
  if (s.dek && !s.dek.includes("<strong>Why it matters:</strong>")) warn(at + ": missing 'Why it matters'");
  if (!s.action) warn(at + ": missing 'What to do' note");
  if (s.linkTag && !topics[s.linkTag]) warn(at + ": linkTag '" + s.linkTag + "' has no topic label");
  const t = plain(s.title || "").toLowerCase();
  if (seenTitle.has(t)) err(at + ": same headline as story " + seenTitle.get(t));
  seenTitle.set(t, i + 1);
});

// The lead story shown at the top must be the highest-impact story in the data.
if (stories.length) {
  let lead = stories[0];
  stories.forEach((s) => { if ((s.impact || 0) > (lead.impact || 0)) lead = s; });
  const leadM = /<div class="lead"[\s\S]*?<h2>([\s\S]*?)<span class="card-expand-hint"/.exec(html);
  if (!leadM) err("Lead story block not found");
  else if (plain(leadM[1]) !== plain(lead.title)) err("Lead headline on the page does not match the top-impact story in the data:\n      page: " + plain(leadM[1]) + "\n      data: " + plain(lead.title));
  if (lead.dateISO && pageDate && lead.dateISO > pageDate) err("Lead story is dated after the page date");
}
if (pageDate && stories.length) {
  const newest = stories.map((s) => s.dateISO).filter(validIso).sort().pop();
  if (newest && ageDays(newest) > maxAgeDays) err("Newest story is dated " + newest + " — nothing recent");
}

// ---- panels ----
const SEV = ["high", "elevated", "active"];
const DIR = ["up", "down", "flat"];
const SENT = ["good", "bad", "neutral"];
function checkRows(name, rows, required, opts) {
  opts = opts || {};
  if (!Array.isArray(rows) || !rows.length) { err(name + ": no rows"); return; }
  rows.forEach((r, i) => {
    const at = name + " row " + (i + 1) + " ('" + (r.name || r.action || "?").toString().slice(0, 40) + "')";
    required.forEach((k) => { if (r[k] == null || String(r[k]).trim() === "") err(at + ": '" + k + "' is empty"); });
    if (r.severity && !SEV.includes(r.severity)) err(at + ": unknown severity '" + r.severity + "'");
    if (r.dir && !DIR.includes(r.dir)) err(at + ": unknown dir '" + r.dir + "'");
    if (r.sentiment && !SENT.includes(r.sentiment)) err(at + ": unknown sentiment '" + r.sentiment + "'");
    ["asOf", "checked"].forEach((k) => {
      if (isoRe.test(String(r[k] || ""))) {
        if (!validIso(r[k])) err(at + ": " + k + " '" + r[k] + "' is not a real date");
        else if (ageDays(r[k]) < -1) err(at + ": " + k + " is in the future");
        else if (k === "asOf" && ageDays(r[k]) > (opts.staleDays || 10)) warn(at + ": data is " + ageDays(r[k]) + " days old (asOf " + r[k] + ")");
      }
    });
    if (isoRe.test(String(r.asOf || "")) && isoRe.test(String(r.checked || "")) && r.asOf > r.checked) err(at + ": asOf is after checked");
    if (r.linkTag && !topics[r.linkTag]) warn(at + ": linkTag '" + r.linkTag + "' has no topic label");
    if (Array.isArray(r.history)) {
      let prev = "";
      r.history.forEach((h) => {
        if (!validIso(h.d) || typeof h.v !== "number" || !isFinite(h.v)) err(at + ": bad history point " + JSON.stringify(h));
        else { if (h.d < prev) err(at + ": history dates out of order at " + h.d); prev = h.d; }
      });
    }
  });
}
// Minerals with no public daily price are marked priced:false and must say why instead.
const priced = (D.minerals || []).filter((m) => m.priced !== false);
const unpriced = (D.minerals || []).filter((m) => m.priced === false);
checkRows("Minerals", priced, ["name", "severity", "exchange", "val", "asOf", "checked", "priceStatus"], { staleDays: 21 });
checkRows("Minerals (no public price)", unpriced.length ? unpriced : [{ name: "-", reason: "-" }], ["name", "severity", "exchange", "reason", "checked"]);
(D.minerals || []).forEach((m) => {
  const r = m.risk || {};
  ["concentration", "policy", "disruption", "price"].forEach((k) => {
    if (!r[k] || typeof r[k].pts !== "number" || !r[k].why) err("Minerals '" + m.name + "': risk factor '" + k + "' is missing points or reason");
  });
  if (m.watch && !validIso(m.watch.date)) err("Minerals '" + m.name + "': watch date is not a real date");
});
checkRows("Freight & Energy", D.freightEnergy, ["pillar", "name", "val", "asOf", "chg", "dir", "severity"]);
checkRows("India Infrastructure", D.infrastructureWatch, ["pillar", "name", "ticker", "val", "asOf", "checked", "chg", "dir", "severity"]);
checkRows("Trade Policy", D.tradePolicy, ["action", "jurisdiction", "sector", "severity", "asOf", "checked", "note"], { staleDays: 45 });
checkRows("Chokepoints", D.chokepoints, ["name", "status", "cls", "note"]);
(D.chokepoints || []).forEach((c) => {
  if (!/^status-(high|elevated|active)$/.test(c.cls || "")) err("Chokepoint '" + c.name + "': unknown status class '" + c.cls + "'");
});
if (!Array.isArray(D.tickerItems) || D.tickerItems.length < 5) err("News ticker has fewer than 5 items");
(D.tickerItems || []).forEach((t, i) => {
  if (!t.label || !t.val) err("Ticker item " + (i + 1) + " is empty");
});

// ---- price data pipeline ----
try {
  const p = JSON.parse(fs.readFileSync(path.join(path.dirname(file), "data", "prices.json"), "utf8"));
  const hrs = (today - new Date(p.fetched_at)) / 3600000;
  if (isNaN(hrs)) err("data/prices.json has no valid fetched_at");
  else if (hrs > 48) err("Price data is " + Math.round(hrs) + " hours old");
  else if (hrs > 30) warn("Price data is " + Math.round(hrs) + " hours old");
  Object.entries(p.sources || {}).forEach(([k, v]) => {
    if (v.error) warn("Price source '" + k + "' failed: " + v.error);
  });
} catch (e) {
  warn("Could not read data/prices.json: " + e.message);
}

// ---- optional: are the story links still alive? ----
async function linkCheck() {
  const urls = [...new Set(stories.map((s) => s.url).filter(Boolean))];
  let idx = 0;
  async function worker() {
    while (idx < urls.length) {
      const u = urls[idx++];
      try {
        const ctl = new AbortController();
        const t = setTimeout(() => ctl.abort(), 15000);
        const r = await fetch(u, { redirect: "follow", signal: ctl.signal, headers: { "user-agent": "Mozilla/5.0 (compatible; GCB-link-check)" } });
        clearTimeout(t);
        if (r.status === 404 || r.status === 410) warn("Broken link (" + r.status + "): " + u);
        else if (r.status >= 500) warn("Link server error (" + r.status + "): " + u);
      } catch (e) {
        warn("Link did not respond: " + u);
      }
    }
  }
  await Promise.all([worker(), worker(), worker(), worker()]);
}

(async () => {
  if (checkLinks) await linkCheck();
  console.log("Checked " + file + " — issue " + issue + ", " + stories.length + " stories, date " + pageDate);
  warnings.forEach((w) => console.log("  WARN  " + w));
  errors.forEach((e) => console.log("  ERROR " + e));
  console.log(errors.length + " error(s), " + warnings.length + " warning(s)");
  if (process.env.GITHUB_STEP_SUMMARY) {
    const lines = ["### Site check: issue " + issue + " (" + pageDate + ")", errors.length + " error(s), " + warnings.length + " warning(s)", ""];
    errors.forEach((e) => lines.push("- ❌ " + e));
    warnings.forEach((w) => lines.push("- ⚠️ " + w));
    fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, lines.join("\n") + "\n");
  }
  process.exit(errors.length ? 1 : 0);
})();

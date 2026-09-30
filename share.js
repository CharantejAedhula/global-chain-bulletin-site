/*
 * Share buttons for the Global Supply Chain Bulletin.
 * Adds a "Share" button to the lead story and to every story card.
 * On phones it opens the phone's own share sheet; elsewhere it shows a small
 * panel with WhatsApp, Telegram, X, LinkedIn, Email and Copy link.
 * Kept in its own file so the daily copy of the bulletin never overwrites it.
 */
(function () {
  "use strict";

  var SITE_NAME = "Global Supply Chain Bulletin";
  var CANONICAL = "https://charantejaedhula.github.io/global-chain-bulletin-site/";

  var css =
    ".share-btn{background:0 0;border:1px solid var(--rule);color:var(--ink-faint);font-family:var(--font-mono);font-size:10px;letter-spacing:.06em;text-transform:uppercase;border-radius:999px;padding:3px 10px;cursor:pointer;margin-left:8px;vertical-align:middle;transition:border-color .15s,color .15s}" +
    ".share-btn:hover,.share-btn:focus-visible{border-color:var(--accent);color:var(--accent)}" +
    ".share-btn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}" +
    ".share-overlay{position:fixed;inset:0;background:rgba(0,0,0,.6);display:flex;align-items:flex-end;justify-content:center;z-index:200}" +
    ".share-overlay[hidden]{display:none}" +
    ".share-sheet{background:var(--surface);border:1px solid var(--rule);border-radius:14px 14px 0 0;width:100%;max-width:460px;padding:18px 20px 24px}" +
    "@media (min-width:600px){.share-overlay{align-items:center}.share-sheet{border-radius:14px}}" +
    ".share-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}" +
    ".share-head h3{margin:0;font-family:var(--font-display);font-size:18px;text-transform:uppercase;letter-spacing:.02em;color:var(--ink)}" +
    ".share-close{background:0 0;border:none;color:var(--ink-faint);font-size:22px;line-height:1;cursor:pointer;padding:4px}" +
    ".share-title{font-size:13px;color:var(--ink-dim);margin:0 0 14px;line-height:1.4}" +
    ".share-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}" +
    ".share-opt{display:block;text-align:center;text-decoration:none;font-family:var(--font-mono);font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:var(--ink);background:var(--surface-2);border:1px solid var(--rule);border-radius:10px;padding:12px 6px;cursor:pointer}" +
    ".share-opt:hover,.share-opt:focus-visible{border-color:var(--accent);color:var(--accent)}" +
    ".share-toast{font-family:var(--font-mono);font-size:11px;color:var(--teal);margin-top:12px;min-height:14px;text-align:center}" +
    "@media print{.share-btn,.share-overlay{display:none!important}}";
  var style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  function clean(s) {
    return (s || "").replace(/[›]/g, "").replace(/\s+/g, " ").trim();
  }

  // Link people land on: this issue's own address, without any #fragment.
  function pageUrl() {
    var u = location.href.split("#")[0].split("?")[0];
    return /^https?:/.test(u) ? u : CANONICAL;
  }

  // ---- the panel (built once, on first use) ----
  var overlay, titleEl, toastEl, links, current = { title: "", url: "" };

  function build() {
    overlay = document.createElement("div");
    overlay.className = "share-overlay";
    overlay.hidden = true;
    overlay.innerHTML =
      '<div class="share-sheet" role="dialog" aria-modal="true" aria-labelledby="shareHeading">' +
      '<div class="share-head"><h3 id="shareHeading">Share this story</h3>' +
      '<button type="button" class="share-close" aria-label="Close">&times;</button></div>' +
      '<p class="share-title"></p>' +
      '<div class="share-grid">' +
      '<a class="share-opt" data-k="wa" target="_blank" rel="noopener">WhatsApp</a>' +
      '<a class="share-opt" data-k="tg" target="_blank" rel="noopener">Telegram</a>' +
      '<a class="share-opt" data-k="x" target="_blank" rel="noopener">X</a>' +
      '<a class="share-opt" data-k="li" target="_blank" rel="noopener">LinkedIn</a>' +
      '<a class="share-opt" data-k="mail">Email</a>' +
      '<button type="button" class="share-opt" data-k="copy">Copy link</button>' +
      "</div>" +
      '<div class="share-toast" role="status" aria-live="polite"></div></div>';
    document.body.appendChild(overlay);
    titleEl = overlay.querySelector(".share-title");
    toastEl = overlay.querySelector(".share-toast");
    links = {};
    overlay.querySelectorAll("[data-k]").forEach(function (el) {
      links[el.getAttribute("data-k")] = el;
    });
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay || e.target.classList.contains("share-close")) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !overlay.hidden) close();
    });
    links.copy.addEventListener("click", function () {
      copy(current.title + "\n" + current.url).then(function (ok) {
        toastEl.textContent = ok ? "Link copied" : "Copy failed - select the link manually";
      });
    });
  }

  function copy(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return false; });
    }
    try {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      var ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return Promise.resolve(ok);
    } catch (e) {
      return Promise.resolve(false);
    }
  }

  var lastFocus = null;
  function open(title, url) {
    if (!overlay) build();
    current = { title: title, url: url };
    var text = title + " - " + SITE_NAME;
    titleEl.textContent = title;
    toastEl.textContent = "";
    links.wa.href = "https://wa.me/?text=" + encodeURIComponent(text + "\n" + url);
    links.tg.href = "https://t.me/share/url?url=" + encodeURIComponent(url) + "&text=" + encodeURIComponent(text);
    links.x.href = "https://twitter.com/intent/tweet?text=" + encodeURIComponent(text) + "&url=" + encodeURIComponent(url);
    links.li.href = "https://www.linkedin.com/sharing/share-offsite/?url=" + encodeURIComponent(url);
    links.mail.href = "mailto:?subject=" + encodeURIComponent(text) + "&body=" + encodeURIComponent(title + "\n\n" + url);
    lastFocus = document.activeElement;
    overlay.hidden = false;
    overlay.querySelector(".share-close").focus();
  }
  function close() {
    overlay.hidden = true;
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  function share(title) {
    var url = pageUrl();
    // Phones and some browsers have a built-in share sheet - use it when present.
    if (navigator.share) {
      navigator.share({ title: title, text: title + " - " + SITE_NAME, url: url }).catch(function (e) {
        if (!e || e.name !== "AbortError") open(title, url);
      });
    } else {
      open(title, url);
    }
  }

  // ---- add a button to each story ----
  function makeBtn(title) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "share-btn";
    b.textContent = "Share";
    b.setAttribute("aria-label", "Share: " + title);
    b.addEventListener("click", function (e) {
      e.stopPropagation(); // don't expand/collapse the story
      share(title);
    });
    return b;
  }

  function decorate() {
    document.querySelectorAll("article.card").forEach(function (card) {
      if (card.querySelector(".share-btn")) return;
      var h3 = card.querySelector("h3");
      var meta = card.querySelector(".meta");
      if (!h3 || !meta) return;
      meta.appendChild(makeBtn(clean(h3.textContent)));
    });
    var lead = document.querySelector(".lead");
    if (lead && !lead.querySelector(".share-btn")) {
      var h2 = lead.querySelector("h2");
      var by = lead.querySelector(".byline-meta");
      if (h2 && by) by.appendChild(makeBtn(clean(h2.textContent)));
    }
  }

  function start() {
    decorate();
    var river = document.getElementById("river");
    if (river && window.MutationObserver) {
      new MutationObserver(decorate).observe(river, { childList: true });
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();

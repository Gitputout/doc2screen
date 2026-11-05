#!/usr/bin/env node
/* Verify a doc2screen HTML reader at a target viewport. */
const path = require("path");
const fs = require("fs");
const puppeteer = require(path.join(__dirname, "..", "tools", "node_modules", "puppeteer-core"));

const [, , htmlPath, widthArg, heightArg, outJson] = process.argv;
if (!htmlPath) {
  console.error("usage: node verify_html.js <html> <width> <height> [out.json]");
  process.exit(2);
}
const width = parseInt(widthArg || "390", 10);
const height = parseInt(heightArg || "657", 10);

function chromePath() {
  const candidates = [
    process.env.CHROME_PATH,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
  ].filter(Boolean);
  for (const p of candidates) if (fs.existsSync(p)) return p;
  return null;
}

(async () => {
  const exe = chromePath();
  if (!exe) throw new Error("Chrome/Chromium not found. Set CHROME_PATH.");
  const browser = await puppeteer.launch({
    executablePath: exe,
    headless: "new",
    args: ["--hide-scrollbars", "--allow-file-access-from-files"]
  });
  const errors = [];
  try {
    const page = await browser.newPage();
    page.on("console", m => { if (m.type() === "error") errors.push("console: " + m.text()); });
    page.on("pageerror", e => errors.push("page: " + e.message));
    await page.setViewport({ width, height, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
    await page.goto("file://" + path.resolve(htmlPath), { waitUntil: "load", timeout: 120000 });
    await page.evaluate(() => document.querySelectorAll("img").forEach(i => { i.loading = "eager"; }));
    await page.evaluate(async () => {
      if (document.fonts && document.fonts.ready) await document.fonts.ready;
      await Promise.all([...document.images].map(i => i.decode ? i.decode().catch(() => {}) : Promise.resolve()));
    });
    await new Promise(r => setTimeout(r, 800));

    const info = await page.evaluate(() => {
      const root = document.documentElement;
      const figs = [...document.querySelectorAll(".shot")].map((f, i) => {
        const box = f.querySelector(".shot-box");
        const img = f.querySelector("img");
        return {
          i: i + 1, mode: f.getAttribute("data-mode"),
          box: box ? [box.clientWidth, box.clientHeight] : null,
          natural: img ? [img.naturalWidth, img.naturalHeight] : null,
          loaded: !!(img && img.complete && img.naturalWidth > 0)
        };
      });
      const tocLinks = [...document.querySelectorAll(".toc-list a")];
      const broken = tocLinks.filter(a => {
        const href = a.getAttribute("href") || "";
        if (!href.startsWith("#")) return false;
        return !document.getElementById(href.slice(1));
      }).map(a => a.getAttribute("href"));
      return {
        viewport: [innerWidth, innerHeight],
        docOverflow: root.scrollWidth - root.clientWidth,
        images: [...document.images].filter(i => i.getAttribute("src")).map(i => ({ ok: i.complete && i.naturalWidth > 0, w: i.naturalWidth, h: i.naturalHeight })),
        figures: figs,
        tocCount: tocLinks.length,
        brokenToc: broken,
        title: document.title
      };
    });
    // font size extremes
    const extremes = [];
    for (const fs of [15, 21]) {
      extremes.push(await page.evaluate((fs) => {
        document.documentElement.style.setProperty("--fs", fs + "px");
        const r = document.documentElement;
        return { fs, overflow: r.scrollWidth - r.clientWidth };
      }, fs));
    }
    const result = { ok: info.docOverflow === 0 && info.images.every(i => i.ok) &&
        info.figures.every(f => f.loaded && f.box && f.box[1] > 0) &&
        info.brokenToc.length === 0 && errors.length === 0 &&
        extremes.every(e => e.overflow === 0),
      errors, extremes, ...info };
    if (outJson) fs.writeFileSync(outJson, JSON.stringify(result, null, 1));
    console.log(JSON.stringify(result));
  } finally {
    await browser.close();
  }
})().catch(err => {
  console.error(JSON.stringify({ ok: false, error: String(err && err.stack || err) }));
  process.exit(1);
});

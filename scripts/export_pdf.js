#!/usr/bin/env node
/* Export a doc2screen HTML reader to PDF with Chrome headless. */
const path = require("path");
const fs = require("fs");
const puppeteer = require(path.join(__dirname, "..", "tools", "node_modules", "puppeteer-core"));

const [, , htmlPath, outPath, widthArg, heightArg, titleArg] = process.argv;
if (!htmlPath || !outPath) {
  console.error("usage: node export_pdf.js <html> <pdf> <width> <height> [title]");
  process.exit(2);
}
const width = parseInt(widthArg || "390", 10);
const height = parseInt(heightArg || "657", 10);
const title = titleArg || "doc2screen";

function chromePath() {
  const candidates = [
    process.env.CHROME_PATH,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"
  ].filter(Boolean);
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  return null;
}

(async () => {
  const exe = chromePath();
  if (!exe) throw new Error("Chrome/Chromium not found. Set CHROME_PATH.");
  const browser = await puppeteer.launch({
    executablePath: exe,
    headless: "new",
    args: ["--hide-scrollbars", "--allow-file-access-from-files", "--font-render-hinting=none"]
  });
  try {
    const page = await browser.newPage();
    await page.setViewport({ width, height, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
    await page.goto("file://" + path.resolve(htmlPath), { waitUntil: "load", timeout: 120000 });
    await page.evaluate(() => {
      try { localStorage.clear(); } catch (e) {}
      document.documentElement.setAttribute("data-theme", "light");
      document.querySelectorAll("img").forEach(i => { i.loading = "eager"; });
    });
    await page.evaluate(async () => {
      if (document.fonts && document.fonts.ready) await document.fonts.ready;
      await Promise.all([...document.images].map(i => i.decode ? i.decode().catch(() => {}) : Promise.resolve()));
    });
    await new Promise(r => setTimeout(r, 600));
    const footer = `<div style="width:100%;font-size:8px;color:#999;text-align:center;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif;">${title.replace(/[<>&]/g, "")}　<span class="pageNumber"></span> / <span class="totalPages"></span></div>`;
    await page.pdf({
      path: outPath,
      width: width + "px",
      height: height + "px",
      printBackground: true,
      preferCSSPageSize: false,
      displayHeaderFooter: true,
      headerTemplate: "<span></span>",
      footerTemplate: footer,
      margin: { top: "8px", bottom: "36px", left: "0px", right: "0px" }
    });
    console.log(JSON.stringify({ ok: true, out: outPath, width, height }));
  } finally {
    await browser.close();
  }
})().catch(err => {
  console.error(JSON.stringify({ ok: false, error: String(err && err.stack || err) }));
  process.exit(1);
});

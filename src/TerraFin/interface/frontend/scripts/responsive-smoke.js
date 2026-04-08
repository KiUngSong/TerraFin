const fs = require('fs/promises');
const path = require('path');
const puppeteer = require('puppeteer');

const VIEWPORTS = [
  { name: 'mobile-375x812', width: 375, height: 812 },
  { name: 'mobile-390x844', width: 390, height: 844 },
  { name: 'tablet-768x1024', width: 768, height: 1024 },
  { name: 'tablet-820x1180', width: 820, height: 1180 },
  { name: 'desktop-1024x768', width: 1024, height: 768 },
  { name: 'desktop-1280x800', width: 1280, height: 800 },
];

const BROWSER_CANDIDATES = [
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
];

async function detectExecutablePath() {
  if (process.env.PUPPETEER_EXECUTABLE_PATH) {
    return process.env.PUPPETEER_EXECUTABLE_PATH;
  }

  for (const candidate of BROWSER_CANDIDATES) {
    try {
      await fs.access(candidate);
      return candidate;
    } catch (_error) {
      // Keep scanning.
    }
  }

  return undefined;
}

async function main() {
  const baseUrl = process.env.RESPONSIVE_SMOKE_URL || 'http://127.0.0.1:8001/dashboard';
  const outputDir = process.env.RESPONSIVE_SMOKE_DIR || path.join(process.cwd(), 'artifacts', 'responsive-smoke');
  const executablePath = await detectExecutablePath();

  await fs.mkdir(outputDir, { recursive: true });

  const browser = await puppeteer.launch({
    headless: true,
    defaultViewport: null,
    executablePath,
  });

  const failures = [];

  try {
    for (const viewport of VIEWPORTS) {
      const page = await browser.newPage();
      await page.setViewport({ width: viewport.width, height: viewport.height, deviceScaleFactor: 1 });
      await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForSelector('main', { timeout: 20000 });
      await page.waitForFunction(
        () => Boolean(document.querySelector('header') && document.querySelector('main')),
        { timeout: 20000 }
      );
      await new Promise((resolve) => setTimeout(resolve, 1500));

      const result = await page.evaluate(() => {
        const selectorForElement = (element) => {
          if (!(element instanceof Element)) {
            return 'unknown';
          }
          if (element.id) {
            return `#${element.id}`;
          }
          const classes = Array.from(element.classList || []).slice(0, 2);
          if (classes.length > 0) {
            return `${element.tagName.toLowerCase()}.${classes.join('.')}`;
          }
          return element.tagName.toLowerCase();
        };

        const overflowing = Array.from(document.querySelectorAll('*'))
          .map((node) => {
            if (!(node instanceof Element)) {
              return null;
            }
            const rect = node.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) {
              return null;
            }
            if (rect.right <= window.innerWidth + 2) {
              return null;
            }
            return {
              selector: selectorForElement(node),
              right: rect.right,
            };
          })
          .filter(Boolean)
          .slice(0, 5);

        return {
          innerWidth: window.innerWidth,
          scrollWidth: document.documentElement.scrollWidth,
          overflowing,
        };
      });

      const screenshotPath = path.join(outputDir, `${viewport.name}.png`);
      await page.screenshot({ path: screenshotPath, fullPage: true });

      const overflowPixels = result.scrollWidth - result.innerWidth;
      if (overflowPixels > 2) {
        failures.push(
          `${viewport.name}: horizontal overflow ${overflowPixels}px` +
            (result.overflowing.length > 0
              ? `, sample offenders: ${result.overflowing.map((item) => item.selector).join(', ')}`
              : '')
        );
      }

      console.log(`[responsive-smoke] ${viewport.name} -> ${screenshotPath}`);
      await page.close();
    }
  } finally {
    await browser.close();
  }

  if (failures.length > 0) {
    throw new Error(`Responsive smoke test failed:\n${failures.join('\n')}`);
  }

  console.log('[responsive-smoke] All viewports passed without page-level horizontal overflow.');
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});

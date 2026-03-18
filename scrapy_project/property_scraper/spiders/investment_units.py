import json
import re
import scrapy
from scrapy_playwright.page import PageMethod
from pathlib import Path
from datetime import datetime

_STEALTH = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = {runtime: {}};
Object.defineProperty(navigator, 'languages', {get: () => ['pl-PL', 'pl', 'en-US', 'en']});
"""


def _pw_meta():
    return {
        "playwright": True,
        "playwright_context": "default",
        "playwright_page_init_callback": _page_init,
        "playwright_page_methods": [PageMethod("wait_for_load_state", "networkidle", timeout=30_000)],
    }


async def _page_init(page, request):
    await page.add_init_script(_STEALTH)


class InvestmentUnitsSpider(scrapy.Spider):
    name = "investment_units"
    custom_settings = {
        "LOG_LEVEL": "INFO",
        "ITEM_PIPELINES": {},
        "CONCURRENT_REQUESTS": 1,
    }

    def __init__(self, inv: str = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not inv:
            raise RuntimeError("Provide -a inv=/pl/inwestycja/...")
        # inv should be full path starting with /pl/inwestycja/...
        self.inv_path = inv
        # output file
        slug = inv.rstrip('/').split('-')[-1]
        self.out = Path(__file__).parents[3] / f"inwestycja_all_units_{slug}.jsonl"
        self.collected = set()

    async def start(self):
        # Try the investment page first to obtain buildId directly.
        invest_url = f"https://www.otodom.pl{self.inv_path}"
        yield scrapy.Request(invest_url, callback=self._got_build_from_investment, meta={"playwright": True, "playwright_page_init_callback": _page_init, "playwright_page_methods": [PageMethod("wait_for_load_state", "networkidle", timeout=30_000)]})

    def _got_build_from_investment(self, response):
        # Try to extract buildId from the investment page's __NEXT_DATA__.
        raw = response.css("script#__NEXT_DATA__::text").get() or response.text
        try:
            top = json.loads(raw)
        except Exception:
            self.logger.info("No __NEXT_DATA__ on investment page; falling back to search page")
            # fallback to search page
            search_url = (
                "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie"
                "/podkarpackie/mielecki/mielec/mielec"
            )
            yield scrapy.Request(search_url, callback=self._got_build, meta={"playwright": True, "playwright_page_init_callback": _page_init, "playwright_page_methods": [PageMethod("wait_for_load_state", "networkidle", timeout=30_000)]})
            return
        build_id = top.get("buildId") or top.get("props", {}).get("buildId")
        if not build_id:
            self.logger.info("No buildId on investment page; falling back to search page")
            search_url = (
                "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie"
                "/podkarpackie/mielecki/mielec/mielec"
            )
            yield scrapy.Request(search_url, callback=self._got_build, meta={"playwright": True, "playwright_page_init_callback": _page_init, "playwright_page_methods": [PageMethod("wait_for_load_state", "networkidle", timeout=30_000)]})
            return
        url = f"https://www.otodom.pl/_next/data/{build_id}{self.inv_path}.json?page=1"
        yield scrapy.Request(url, callback=self.parse_invest_page, meta={"page": 1, "build_id": build_id, "playwright": True, "playwright_page_init_callback": _page_init, "playwright_page_methods": [PageMethod("wait_for_load_state", "networkidle", timeout=30_000)]})

    def _got_build(self, response):
        raw = response.css("script#__NEXT_DATA__::text").get() or response.text
        try:
            top = json.loads(raw)
        except Exception:
            self.logger.error("Failed to parse __NEXT_DATA__ for buildId")
            return
        build_id = top.get("buildId") or top.get("props", {}).get("buildId")
        if not build_id:
            self.logger.error("No buildId found on search page")
            return
        # fetch page 1 of the investment via _next/data
        url = f"https://www.otodom.pl/_next/data/{build_id}{self.inv_path}.json?page=1"
        yield scrapy.Request(url, callback=self.parse_invest_page, meta={"page": 1, "build_id": build_id, "playwright": True, "playwright_page_init_callback": _page_init, "playwright_page_methods": [PageMethod("wait_for_load_state", "networkidle", timeout=30_000)]})

    def parse_invest_page(self, response):
        raw = response.css("pre::text").get() or response.text
        try:
            j = json.loads(raw)
        except Exception as e:
            self.logger.error("Failed to parse invest page JSON: %s", e)
            return
        ad = j.get("pageProps", {}).get("ad") or j.get("pageProps", {}).get("data", {}).get("ad") or j.get("pageProps", {})
        pag = (ad or {}).get("paginatedUnits", {})
        pagination = pag.get("pagination", {})
        total_pages = pagination.get("totalPages") or 1
        # collect items from this page
        units = pag.get("items", [])
        for u in units:
            url = u.get("url", "")
            m = re.search(r"-?(ID[A-Za-z0-9]+)$", url)
            if m:
                self.collected.add(m.group(1))
        self.logger.info("Collected %d units (page 1)", len(self.collected))
        build_id = response.meta.get("build_id")
        # schedule remaining pages
        for p in range(2, total_pages + 1):
            url = f"https://www.otodom.pl/_next/data/{build_id}{self.inv_path}.json?page={p}"
            yield scrapy.Request(url, callback=self.parse_next_invest_page, meta={"page": p, "total_pages": total_pages, "build_id": build_id, "playwright": True, "playwright_page_init_callback": _page_init, "playwright_page_methods": [PageMethod("wait_for_load_state", "networkidle", timeout=30_000)]})
        # if only 1 page, persist
        if total_pages == 1:
            self._persist()

    def parse_next_invest_page(self, response):
        raw = response.css("pre::text").get() or response.text
        try:
            j = json.loads(raw)
        except Exception as e:
            self.logger.warning("Failed to parse invest _next/data page %s: %s", response.meta.get('page'), e)
            return
        ad = j.get("pageProps", {}).get("ad") or j.get("pageProps", {}).get("data", {}).get("ad") or j.get("pageProps", {})
        pag = (ad or {}).get("paginatedUnits", {})
        units = pag.get("items", [])
        for u in units:
            url = u.get("url", "")
            m = re.search(r"-?(ID[A-Za-z0-9]+)$", url)
            if m:
                self.collected.add(m.group(1))
        self.logger.info("Collected %d units (after page %s)", len(self.collected), response.meta.get('page'))
        # if last page, persist
        if response.meta.get("page") == response.meta.get("total_pages"):
            self._persist()

    def _persist(self):
        rec = {
            "run_at": datetime.utcnow().isoformat(),
            "investment_path": self.inv_path,
            "unit_count": len(self.collected),
            "units": sorted(self.collected),
        }
        with open(self.out, "w", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.logger.info("Saved %d unit slugs to %s", len(self.collected), self.out)

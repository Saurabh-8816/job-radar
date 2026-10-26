"""Headless-browser fetch for pages built by JavaScript (SSC, NIELIT, MPSC, CG Health…).

Their HTML is an empty shell; the job list only exists after the page's scripts run.
Sources marked `render: true` are opened in Chromium (GitHub Actions) or, on a laptop
without Playwright's own Chromium, the installed Edge or Chrome.

Pages render 6 at a time in one browser, with images, fonts and media blocked: only
the links matter, and GitHub minutes are limited.
"""

import asyncio

from .fetch import USER_AGENT, Response

CONCURRENCY = 6
_SKIP = {"image", "media", "font"}


def available() -> bool:
    try:
        import playwright.async_api  # noqa: F401
        return True
    except ImportError:
        return False


async def _launch(p):
    errors = []
    for kwargs in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
        try:
            return await p.chromium.launch(headless=True, **kwargs)
        except Exception as e:  # this browser flavour isn't installed; try the next
            errors.append(f"{kwargs.get('channel', 'chromium')}: {e.__class__.__name__}")
    raise RuntimeError("no browser available (" + "; ".join(errors) + ")")


async def _until_links_settle(page, min_wait_ms: int, max_wait_ms: int = 12_000):
    """Job lists often arrive after the page 'loads' (an API call fills a table). Wait
    until the number of links stops changing, so a slow list isn't captured half-built."""
    await page.wait_for_timeout(min_wait_ms)
    waited, previous, stable = min_wait_ms, -1, 0
    while waited < max_wait_ms:
        count = await page.evaluate("document.links.length")
        stable = stable + 1 if count == previous else 0
        if stable >= 2 and count > 0:
            return
        previous = count
        await page.wait_for_timeout(1000)
        waited += 1000


async def _render_all(urls, timeout, settle_ms) -> dict[str, Response]:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        try:
            browser = await _launch(p)
        except RuntimeError as e:
            return {u: Response(u, False, error=str(e)) for u in urls}
        ctx = await browser.new_context(user_agent=USER_AGENT, locale="en-IN", ignore_https_errors=True)

        async def lean(route):
            if route.request.resource_type in _SKIP:
                await route.abort()
            else:
                await route.continue_()
        await ctx.route("**/*", lean)

        gate = asyncio.Semaphore(CONCURRENCY)

        async def one(url):
            async with gate:
                page = await ctx.new_page()
                try:
                    resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=8_000)
                    except Exception:
                        pass  # chatty sites never go idle; the stability check below still applies
                    await _until_links_settle(page, settle_ms)
                    status = resp.status if resp else 200
                    return url, Response(url, status < 400, status, text=await page.content(),
                                         content_type="text/html",
                                         error=None if status < 400 else f"HTTP {status}")
                except Exception as e:
                    return url, Response(url, False, error=f"render: {e.__class__.__name__}")
                finally:
                    await page.close()

        results = dict(await asyncio.gather(*(one(u) for u in urls)))
        await browser.close()
        return results


def render_many(urls, timeout: float = 40, settle_ms: int = 1500) -> dict[str, Response]:
    urls = list(dict.fromkeys(urls))
    if not urls:
        return {}
    if not available():
        return {u: Response(u, False, error="needs a browser: pip install playwright") for u in urls}
    return asyncio.run(_render_all(urls, timeout, settle_ms))

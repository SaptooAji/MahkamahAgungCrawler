# scraper/browser.py

from __future__ import annotations

import nodriver as uc


class BrowserManager:
    def __init__(self, *, headless: bool = False):
        self.headless = headless
        self.browser = None

    async def start(self):
        self.browser = await uc.start(
            headless=self.headless,
            browser_args=[
                "--start-maximized",
                "--disable-dev-shm-usage",
                "--mute-audio",
            ],
        )

        return self.browser

    async def stop(self):
        if self.browser is not None:
            self.browser.stop()
            self.browser = None
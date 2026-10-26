"""Playwright browser with an operator-supplied exact origin allowlist."""

import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def origin(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username:
        raise ValueError("Only HTTP(S) origins without credentials are permitted")
    return f"{parsed.scheme}://{parsed.hostname}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}"


def chromium_executable():
    return os.environ.get("AASS_CHROMIUM_EXECUTABLE") or shutil.which("chromium")


class ComputerUse:
    def __init__(self, allowed_origins):
        self.allowed = {origin(url) for url in allowed_origins}
        self.runtime = self.browser = self.context = self.page = None

    def __enter__(self):
        self.runtime = sync_playwright().start()
        try:
            self.browser = self.runtime.chromium.launch(
                headless=True, executable_path=chromium_executable()
            )
            self.context = self.browser.new_context(accept_downloads=False, service_workers="block")
            self.context.route("**/*", self._route)
            self.context.route_web_socket("**/*", lambda socket: socket.close())
            self.page = self.context.new_page()
            self.page.set_default_timeout(10_000)
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def _route(self, route):
        try:
            allowed = origin(route.request.url) in self.allowed
        except ValueError:
            allowed = False
        route.continue_() if allowed else route.abort()

    def navigate(self, url):
        if origin(url) not in self.allowed:
            raise PermissionError("Browser origin is not authorized")
        response = self.page.goto(url, wait_until="domcontentloaded")
        if response is None or not response.ok:
            raise RuntimeError("Navigation did not return a successful HTTP response")
        return {"status": response.status, "title": self.page.title()}

    def screenshot(self, path):
        self.page.screenshot(path=str(Path(path)), full_page=False)

    def click(self, selector=None, *, x=None, y=None):
        if selector:
            self.page.locator(selector).click()
        elif isinstance(x, (int, float)) and isinstance(y, (int, float)) and x >= 0 and y >= 0:
            self.page.mouse.click(x, y)
        else:
            raise ValueError("Provide a selector or nonnegative coordinates")

    def __exit__(self, *args):
        try:
            if self.context:
                self.context.close()
        finally:
            try:
                if self.browser:
                    self.browser.close()
            finally:
                if self.runtime:
                    self.runtime.stop()

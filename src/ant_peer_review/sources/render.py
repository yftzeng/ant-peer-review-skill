"""Headless-browser rendering for JS-rendered pages (D-0001, step 2).

Optional: needs the `render` extra (`pip install 'ant-peer-review[render]'` then
`playwright install chromium`). Used only for thin pages or `needs_js` site
profiles, after robots and the site profile were checked. The browser sends our
own User-Agent. Every request it makes, popups included, passes `allow` (the
crawler's address check) and is fetched by us without following redirects, so a
redirect is checked before the browser may follow it. Navigations (main frame,
iframes, popups) also pass `allow_navigation` (robots and the
site profile). WebSockets and
popups are refused. Requests are capped in number and by a total deadline.
"""
from __future__ import annotations

import importlib.util
import time
from typing import Callable, Protocol
from urllib.parse import urljoin

MAX_REQUESTS = 300


class RenderError(Exception):
    pass


class Renderer(Protocol):
    def render(self, url: str, *, allow: Callable[[str], bool],
               allow_navigation: Callable[[str], bool], user_agent: str, max_bytes: int,
               timeout: float) -> tuple[str, str]:
        """Return (rendered HTML, the URL the main frame ended on)."""


class PlaywrightRenderer:
    name = "playwright"

    def __init__(self, launch_args: tuple[str, ...] = ()):
        self.launch_args = list(launch_args)

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("playwright") is not None

    def render(self, url, *, allow, allow_navigation, user_agent, max_bytes,
               timeout) -> tuple[str, str]:  # pragma: no cover - needs a browser
        from playwright.sync_api import Error, sync_playwright

        deadline = time.monotonic() + timeout
        state = {"n": 0}

        def handler(route):
            req = route.request
            u = req.url
            if u.startswith(("data:", "blob:")):
                return route.continue_()  # no network
            state["n"] += 1
            nav = req.is_navigation_request()
            ok = state["n"] <= MAX_REQUESTS and time.monotonic() < deadline and allow(u) \
                and (not nav or allow_navigation(u))
            if not ok:
                return route.abort()
            try:
                resp = route.fetch(max_redirects=0,
                                   timeout=max(1.0, deadline - time.monotonic()) * 1000)
            except Error:
                return route.abort()
            if 300 <= resp.status < 400:
                target = urljoin(u, resp.headers.get("location", ""))
                if target == u or not allow(target) or (nav and not allow_navigation(target)):
                    return route.abort()
            route.fulfill(response=resp)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=self.launch_args)
                try:
                    ctx = browser.new_context(user_agent=user_agent, service_workers="block",
                                              java_script_enabled=True)
                    ctx.route("**/*", handler)
                    # A handler that never calls connect_to_server keeps every WebSocket
                    # off the network (closing it from the sync handler deadlocks).
                    ctx.route_web_socket("**/*", lambda ws: None)
                    page = ctx.new_page()
                    ctx.on("page", lambda popup: popup.close())
                    page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
                    html, final = page.content(), page.url
                finally:
                    browser.close()
        except Error as e:
            raise RenderError(str(e)[:300]) from e
        if len(html.encode("utf-8")) > max_bytes:
            raise RenderError(f"rendered page larger than {max_bytes} bytes")
        return html, final


def default_renderer() -> Renderer | None:
    return PlaywrightRenderer() if PlaywrightRenderer.available() else None

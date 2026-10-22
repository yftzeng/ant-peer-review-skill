"""Pages that arrive with HTTP 200 but are not the article (K-Dense paper-lookup:
"verify the shape of what you got, not just the status code")."""
from __future__ import annotations

import re

# Strong signs of an interstitial. Plain Cloudflare pages also embed
# /cdn-cgi/challenge-platform, so that alone never counts.
CHALLENGE = re.compile(r"cf-chl|just a moment\.\.\.|attention required|enable javascript and "
                       r"cookies|checking your browser|verify you are human|captcha|ddos protection",
                       re.I)
NOT_FOUND = re.compile(r"\b404\b|not found|page (?:does not|doesn't) exist|找不到|不存在|页面不存在",
                       re.I)
WALL = re.compile(r"(?:sign|log)\s*in to (?:continue|read)|subscribe to (?:continue|read)|"
                  r"members only|subscribers only|請登入|請先登入|登入後|登入以|訂閱(?:後|以)?閱讀|"
                  r"付費會員|请登录|登录后|会员专享", re.I)
SHORT = 600


def page_problem(raw_html: str, title: str, markdown: str) -> str | None:
    text = markdown.strip()
    n = len(text)
    head = (title + "\n" + "\n".join(text.splitlines()[:3]))
    if n < SHORT and CHALLENGE.search(raw_html[:20000] + "\n" + title):
        return "blocked_by_challenge"
    if n < SHORT and NOT_FOUND.search(head):
        return "soft_404"
    if n < SHORT + 200 and WALL.search(text):
        return "login_or_paywall"
    if n < 50:
        return "empty_page"
    return None

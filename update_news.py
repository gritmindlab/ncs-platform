#!/usr/bin/env python3
"""기관별로 검증된 공식 보도자료 게시판만 수집한다. 검색엔진 결과는 사용하지 않는다."""
from __future__ import annotations

import html
import json
import pathlib
import re
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "agencies.json"
OUTPUT_PATH = ROOT / "data" / "news.json"
USER_AGENT = "Mozilla/5.0 (compatible; GritmindlabOfficialPressBot/2.0)"


class AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.anchors = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self.current = {"href": dict(attrs).get("href", ""), "text": []}

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"].append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.current is not None:
            self.current["text"] = re.sub(r"\s+", " ", " ".join(self.current["text"])).strip()
            self.anchors.append(self.current)
            self.current = None


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def fetch_text(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"})
    with urllib.request.urlopen(request, timeout=40, context=ssl.create_default_context()) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace"), response.geturl()


def keywords(title):
    tags = ["보도자료"]
    for word in ("채용", "청년", "인재", "교육", "NCS", "일자리"):
        if word.lower() in title.lower():
            tags.append(word)
    return tags[:3]


def parse_official_anchor_list(agency, board):
    markup, final_url = fetch_text(board["url"])
    parser = AnchorParser()
    parser.feed(markup)
    title_re = re.compile(board["titlePattern"])
    date_re = re.compile(board["datePattern"])
    results = []
    for anchor in parser.anchors:
        text = html.unescape(anchor["text"])
        if not title_re.search(text):
            continue
        date_match = date_re.search(text)
        if not date_match:
            continue
        raw_date = date_match.group(0).rstrip(".")
        title = date_re.sub("", title_re.sub("", text)).strip(" -")
        href = urllib.parse.urljoin(final_url, anchor["href"])
        parsed = urllib.parse.urlparse(href)
        if parsed.hostname is None or not parsed.hostname.endswith(agency["officialDomain"]):
            continue
        results.append({
            "agency": agency["name"], "type": agency["type"], "date": raw_date,
            "title": title, "url": href, "source": "기관 공식 보도자료 게시판",
            "officialDomain": agency["officialDomain"], "tags": keywords(title),
        })
    return results


def strip_tags(markup):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()


def parse_kosaf_press_table(agency, board):
    markup, final_url = fetch_text(board["url"])
    title_re, date_re = re.compile(board["titlePattern"]), re.compile(board["datePattern"])
    results = []
    for row in re.findall(r"<tr\b[^>]*>([\s\S]*?)</tr>", markup, re.I):
        if not title_re.search(row):
            continue
        link = re.search(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>([\s\S]*?)(?:</a>|</td>)", row, re.I)
        date_match = date_re.search(strip_tags(row))
        if not link or not date_match:
            continue
        title = title_re.sub("", strip_tags(link.group(2))).strip(" -")
        href = urllib.parse.urljoin(final_url, html.unescape(link.group(1)))
        parsed = urllib.parse.urlparse(href)
        if parsed.hostname is None or not parsed.hostname.endswith(agency["officialDomain"]):
            continue
        results.append({
            "agency": agency["name"], "type": agency["type"], "date": date_match.group(0).rstrip("."),
            "title": title, "url": href, "source": "기관 공식 보도자료 게시판",
            "officialDomain": agency["officialDomain"], "tags": keywords(title),
        })
    return results


PARSERS = {"official_anchor_list": parse_official_anchor_list, "kosaf_press_table": parse_kosaf_press_table}


def main():
    agencies = load_config()
    items, health = [], []
    for agency in agencies:
        board = agency.get("board")
        if not board:
            health.append({"agency": agency["name"], "status": "not_configured", "message": agency.get("status", "공식 게시판 규칙 필요")})
            continue
        try:
            parser = PARSERS[board["parser"]]
            collected = parser(agency, board)
            if not collected:
                raise RuntimeError("공식 게시판에서 보도자료 항목을 찾지 못했습니다. 페이지 구조 변경 여부를 확인하세요.")
            items.extend(collected)
            health.append({"agency": agency["name"], "status": "ok", "itemCount": len(collected), "boardUrl": board["url"]})
        except Exception as exc:
            health.append({"agency": agency["name"], "status": "error", "message": str(exc)[:220], "boardUrl": board["url"]})
    unique = {(item["agency"], item["title"], item["date"]): item for item in items}
    ordered = sorted(unique.values(), key=lambda item: item["date"], reverse=True)
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "verified official press-release boards only",
        "configuredAgencyCount": sum(1 for agency in agencies if agency.get("board")),
        "totalAgencyCount": len(agencies), "itemCount": len(ordered),
        "health": health, "items": ordered,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(ordered)} verified official releases; {payload['configuredAgencyCount']}/{len(agencies)} agencies configured")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
기관별 보도자료 게시판(config/agencies.json)을 읽어서
공식 게시판 원문만 data/news.json 에 누적 저장한다.

- 사이트마다 다른 파서를 만드는 대신, 범용 규칙으로 대부분을 처리한다:
  1) jsonApi가 있으면: form을 POST해서 JSON 응답에서 리스트 추출
  2) 그 외: HTML을 받아서 <a href="..."> 목록 중
     - jsIdPattern이 있으면: onclick/href 안의 JS 함수 호출에서 id를 뽑아
       detailTemplate에 채워 상세 URL을 만든다
     - 없으면: href 자체를 상세 URL로 쓴다 (officialDomain 소속만 인정)
     날짜는 같은 표(tr) 또는 인접 텍스트에서 YYYY-MM-DD / YYYY.MM.DD 패턴으로 찾는다.
- 이미 저장된 자료는 절대 삭제하지 않고 계속 누적한다 (title+agency+date 기준 중복만 제거).
- 핵심정리(AI 요약) 기능은 사용하지 않는다. 공식 원문 링크만 제공한다.
"""
from __future__ import annotations

import html
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "agencies.json"
OUTPUT_PATH = ROOT / "data" / "news.json"

USER_AGENT = "Mozilla/5.0 (compatible; GritMindLabNewsBot/1.0; +https://gritmindlab.github.io/)"
TIMEOUT = 25
MAX_RETRIES = 3
RETRY_SLEEP = 2

DATE_RE = re.compile(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})")
SKIP_WORDS = ("검색", "로그인", "더보기", "이전", "다음", "목록", "맨위", "sitemap", "サイト")

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def http_get(url: str, attempt: int = 1) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CTX) as res:
            charset = res.headers.get_content_charset() or "utf-8"
            return res.read().decode(charset, errors="replace")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_SLEEP)
            return http_get(url, attempt + 1)
        raise RuntimeError(f"GET 실패: {exc}") from exc


def http_post_json(url: str, form: dict, attempt: int = 1) -> dict:
    data = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CTX) as res:
            charset = res.headers.get_content_charset() or "utf-8"
            return json.loads(res.read().decode(charset, errors="replace"))
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_SLEEP)
            return http_post_json(url, form, attempt + 1)
        raise RuntimeError(f"POST 실패: {exc}") from exc


def clean_text(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def looks_like_nav(title: str) -> bool:
    if not title or len(title) < 4:
        return True
    return any(w.lower() in title.lower() for w in SKIP_WORDS)


def make_tags(title: str) -> list[str]:
    tags = ["보도자료"]
    for word in ("채용", "청년", "인재", "교육", "NCS", "일자리", "협약", "안전"):
        if word in title:
            tags.append(word)
    return tags[:4]


def domain_ok(url: str, official_domain: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    return host.endswith(official_domain)


def extract_rows(markup: str) -> list[str]:
    """<tr>...</tr> 단위로 잘라서 반환. 표가 아닌 목록형이면 <li>로 대체 시도."""
    rows = re.findall(r"<tr\b[^>]*>([\s\S]*?)</tr>", markup, re.I)
    if len(rows) >= 3:
        return rows
    rows = re.findall(r"<li\b[^>]*>([\s\S]*?)</li>", markup, re.I)
    return rows


def find_date_in(text: str) -> str | None:
    m = DATE_RE.search(text)
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def collect_generic_html(agency: dict, board_url: str) -> list[dict]:
    markup = http_get(board_url)
    rows = extract_rows(markup)
    results = []
    js_pattern = re.compile(agency["jsIdPattern"]) if agency.get("jsIdPattern") else None
    for row in rows:
        link_match = re.search(
            r"<a\b([^>]*)href=[\"']([^\"']+)[\"']([^>]*)>([\s\S]*?)</a>", row, re.I
        )
        if not link_match:
            continue
        attrs_before, href_raw, attrs_after, inner = link_match.groups()
        title = clean_text(inner)
        if looks_like_nav(title):
            continue
        date_str = find_date_in(clean_text(row))
        if not date_str:
            continue
        href = html.unescape(href_raw)
        full_attrs = attrs_before + attrs_after
        detail_url = None
        if js_pattern and agency.get("detailTemplate"):
            m = js_pattern.search(full_attrs) or js_pattern.search(href)
            if m:
                detail_url = agency["detailTemplate"].format(id=m.group(1))
        if not detail_url:
            detail_url = urllib.parse.urljoin(board_url, href)
        if not domain_ok(detail_url, agency["domain"]):
            continue
        title = re.sub(r"^\s*\[?N(EW)?\]?\s*", "", title).strip()
        results.append(
            {
                "agency": agency["name"],
                "type": agency["type"],
                "date": date_str,
                "title": title,
                "url": detail_url,
                "source": "기관 공식 보도자료 게시판",
                "officialDomain": agency["domain"],
                "tags": make_tags(title),
            }
        )
    return results


def nested_value(obj, path: str):
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def collect_json_api(agency: dict) -> list[dict]:
    api = agency["jsonApi"]
    data = http_post_json(api["url"], api.get("form", {}))
    items = nested_value(data, api["listPath"]) or []
    results = []
    for item in items:
        title = clean_text(str(item.get(api["titleField"], "")))
        if looks_like_nav(title):
            continue
        raw_date = str(item.get(api["dateField"], ""))
        date_str = find_date_in(raw_date) or raw_date[:10]
        item_id = item.get(api["idField"])
        detail_url = api["detailTemplate"].format(id=item_id)
        if not domain_ok(detail_url, agency["domain"]):
            continue
        results.append(
            {
                "agency": agency["name"],
                "type": agency["type"],
                "date": date_str,
                "title": title,
                "url": detail_url,
                "source": "기관 공식 보도자료 게시판",
                "officialDomain": agency["domain"],
                "tags": make_tags(title),
            }
        )
    return results


def collect_agency(agency: dict) -> tuple[list[dict], dict]:
    name = agency["name"]
    try:
        if agency.get("jsonApi"):
            items = collect_json_api(agency)
        elif agency.get("boardUrls"):
            items = []
            for url in agency["boardUrls"]:
                items.extend(collect_generic_html(agency, url))
        else:
            return [], {
                "agency": name,
                "status": "not_configured",
                "message": "공식 게시판 규칙 미확인 (boardUrls 필요)",
            }
        if not items:
            return [], {
                "agency": name,
                "status": "error",
                "message": "게시판 구조에서 항목을 찾지 못함 (규칙 재확인 필요)",
            }
        return items, {"agency": name, "status": "ok", "itemCount": len(items)}
    except Exception as exc:  # noqa: BLE001
        return [], {"agency": name, "status": "error", "message": str(exc)[:200]}


def load_existing() -> dict:
    if OUTPUT_PATH.exists():
        try:
            return json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"items": []}


def dedupe_key(item: dict) -> tuple:
    return (item["agency"], item["title"], item["date"])


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if isinstance(config, list):
        agencies = config
        backfill_months = 4
        max_new_summaries = 40
    else:
        agencies = config["agencies"]
        backfill_months = config.get("backfillMonths", 4)
        max_new_summaries = config.get("maxNewSummariesPerRun", 40)
    cutoff = datetime.now(timezone.utc) - timedelta(days=backfill_months * 31)

    existing = load_existing()
    existing_items = existing.get("items", [])
    existing_keys = {dedupe_key(i) for i in existing_items}

    all_new_items: list[dict] = []
    health = []
    for agency in agencies:
        items, status = collect_agency(agency)
        health.append(status)
        for item in items:
            if dedupe_key(item) in existing_keys:
                continue
            existing_keys.add(dedupe_key(item))
            all_new_items.append(item)
        time.sleep(0.3)

    combined = existing_items + all_new_items
    combined.sort(key=lambda i: i.get("date", ""), reverse=True)

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "verified official press-release boards only",
        "configuredAgencyCount": sum(
            1 for a in agencies if a.get("boardUrls") or a.get("jsonApi")
        ),
        "totalAgencyCount": len(agencies),
        "successfulAgencyCount": sum(1 for h in health if h["status"] == "ok"),
        "itemCount": len(combined),
        "health": health,
        "items": combined,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"새 항목 {len(all_new_items)}건 추가, 누적 {len(combined)}건 "
        f"({payload['successfulAgencyCount']}/{len(agencies)} 기관 정상)"
    )


if __name__ == "__main__":
    main()

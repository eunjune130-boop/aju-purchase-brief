from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
import json
import re

import feedparser
import requests
from bs4 import BeautifulSoup


# ============================================================
# AJU 구매팀 브리핑 자동수집
#
# [환율]
# 연합뉴스 서울외환시장 관련 기사 별도 검색
# → 당일 USD/KRW
# → 전 거래일
# → 등락
# → 기사/출처 저장
#
# [구매 뉴스]
# 시멘트·슬래그 / 유연탄·에너지 / 골재·모래
# 철강·PHC / 물류 / 건설시장 / 공급사
#
# [뉴스 최신성]
# 오늘·어제 → 최근 3일 → 최근 7일 → 특이사항 없음
# ============================================================


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_FILE = DATA_DIR / "latest.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}


# ============================================================
# 기본 함수
# ============================================================

def now_kst():
    return datetime.utcnow() + timedelta(hours=9)


def normalize(text):
    if not text:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(text).lower()
    ).strip()


# ============================================================
# Google News RSS
# ============================================================

def google_news_search(query, days=2, limit=30):

    encoded_query = quote(
        f"{query} when:{days}d"
    )

    url = (
        "https://news.google.com/rss/search"
        f"?q={encoded_query}"
        "&hl=ko"
        "&gl=KR"
        "&ceid=KR:ko"
    )

    feed = feedparser.parse(url)

    results = []

    for entry in feed.entries[:limit]:

        source = ""

        try:
            if "source" in entry:
                source = entry.source.title
        except Exception:
            pass

        results.append({
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "published": entry.get("published", ""),
            "source": source,
        })

    return results


# ============================================================
# 일반 구매뉴스 관련성 평가
# ============================================================

def score_article(article, rule):

    title = normalize(
        article.get("title", "")
    )

    source = normalize(
        article.get("source", "")
    )

    text = f"{title} {source}"

    score = 0

    for keyword in rule.get(
        "strong_keywords", []
    ):
        if normalize(keyword) in text:
            score += 4

    for keyword in rule.get(
        "keywords", []
    ):
        if normalize(keyword) in text:
            score += 2

    for keyword in rule.get(
        "support_keywords", []
    ):
        if normalize(keyword) in text:
            score += 1

    for media in rule.get(
        "preferred_sources", []
    ):
        if normalize(media) in source:
            score += 1

    return score


def remove_duplicates(articles):

    seen = set()
    result = []

    for article in articles:

        title = normalize(
            article.get("title", "")
        )

        key = re.sub(
            r"\s*-\s*[^-]+$",
            "",
            title
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(article)

    return result


def filter_articles(
    articles,
    rule,
    minimum_score=3,
    limit=5
):

    result = []

    for article in articles:

        score = score_article(
            article,
            rule
        )

        if score < minimum_score:
            continue

        item = dict(article)
        item["relevance_score"] = score

        result.append(item)

    result.sort(
        key=lambda x: x[
            "relevance_score"
        ],
        reverse=True
    )

    result = remove_duplicates(result)

    return result[:limit]


def collect_with_freshness(
    query,
    rule
):

    ranges = [
        (2, "오늘·어제"),
        (3, "최근 3일"),
        (7, "최근 7일"),
    ]

    for days, label in ranges:

        articles = google_news_search(
            query,
            days=days,
            limit=30
        )

        articles = filter_articles(
            articles,
            rule,
            minimum_score=3,
            limit=5
        )

        if articles:
            return {
                "freshness": label,
                "articles": articles,
            }

    return {
        "freshness": "특이사항 없음",
        "articles": [],
    }


# ============================================================
# 구매뉴스 7개 영역
# ============================================================

CATEGORY_RULES = {

    "cement_slag": {
        "name": "시멘트·슬래그",

        "query":
            "시멘트 슬래그 고로슬래그 "
            "가격 공급 생산 정비",

        "strong_keywords": [
            "시멘트",
            "슬래그",
            "고로슬래그",
        ],

        "keywords": [
            "가격 인상",
            "가격 조정",
            "출하",
            "생산중단",
            "정기보수",
            "공장",
            "가동률",
        ],

        "support_keywords": [
            "전력비",
            "환경규제",
            "탄소",
            "원가",
            "건설경기",
        ],

        "preferred_sources": [
            "연합뉴스",
            "대한경제",
            "뉴스핌",
            "뉴시스",
        ],
    },


    "energy": {
        "name": "유연탄·에너지",

        "query":
            "유연탄 석탄 브렌트유 "
            "국제유가 LNG 에너지 가격",

        "strong_keywords": [
            "유연탄",
            "석탄",
            "브렌트",
            "국제유가",
            "lng",
        ],

        "keywords": [
            "원유",
            "유가",
            "에너지 가격",
            "전력요금",
            "천연가스",
        ],

        "support_keywords": [
            "운송비",
            "연료비",
            "수입가격",
            "원가",
        ],

        "preferred_sources": [
            "연합뉴스",
            "로이터",
            "뉴스1",
            "한국경제",
        ],
    },


    "aggregate": {
        "name": "골재·모래",

        "query":
            "골재 모래 레미콘 "
            "채취허가 공급 가격",

        "strong_keywords": [
            "골재",
            "모래",
            "채취허가",
            "석산",
        ],

        "keywords": [
            "레미콘",
            "골재 가격",
            "공급 부족",
            "공급 차질",
            "채석",
        ],

        "support_keywords": [
            "운송거리",
            "환경규제",
            "수도권",
            "건설자재",
        ],

        "preferred_sources": [
            "연합뉴스",
            "대한경제",
            "뉴시스",
        ],
    },


    "steel_phc": {
        "name": "철강·PHC",

        "query":
            "PC강봉 선재 철근 철스크랩 "
            "철광석 PHC 철강 가격",

        "strong_keywords": [
            "pc강봉",
            "phc",
            "철강",
            "철근",
            "선재",
            "철광석",
        ],

        "keywords": [
            "철스크랩",
            "고철",
            "중국 철강",
            "강재",
            "철강 가격",
        ],

        "support_keywords": [
            "원자재",
            "수입",
            "가격",
            "공급",
        ],

        "preferred_sources": [
            "스틸데일리",
            "철강금속신문",
            "연합뉴스",
            "뉴스핌",
        ],
    },


    "logistics": {
        "name": "물류",

        "query":
            "BDI 벌크 해상운임 "
            "물류 운송비 항만",

        "strong_keywords": [
            "bdi",
            "해상운임",
            "벌크선",
            "운임",
        ],

        "keywords": [
            "물류",
            "항만",
            "선박",
            "운송비",
            "해운",
        ],

        "support_keywords": [
            "석탄",
            "철광석",
            "수입",
            "운송",
        ],

        "preferred_sources": [
            "쉬핑뉴스넷",
            "해사신문",
            "연합뉴스",
            "한국경제",
        ],
    },


    "construction": {
        "name": "건설시장",

        "query":
            "건설수주 착공 SOC "
            "건설경기 건설투자",

        "strong_keywords": [
            "건설수주",
            "착공",
            "건설투자",
            "soc",
        ],

        "keywords": [
            "주택",
            "건설경기",
            "인프라",
            "공공공사",
            "민간공사",
        ],

        "support_keywords": [
            "레미콘",
            "건자재",
            "시멘트",
            "phc",
        ],

        "preferred_sources": [
            "국토교통부",
            "통계청",
            "KDI",
            "연합뉴스",
            "대한경제",
        ],
    },


    "suppliers": {
        "name": "공급사",

        "query":
            "시멘트 골재 레미콘 "
            "삼표 유진기업 공급 생산 가격",

        "strong_keywords": [
            "삼표",
            "유진기업",
            "시멘트",
            "레미콘",
            "골재",
        ],

        "keywords": [
            "한일시멘트",
            "쌍용c&e",
            "아세아시멘트",
            "성신양회",
            "삼표시멘트",
            "현대제철",
            "포스코",
        ],

        "support_keywords": [
            "가격",
            "공급",
            "생산",
            "공장",
            "정비",
            "파업",
        ],

        "preferred_sources": [
            "연합뉴스",
            "뉴스핌",
            "뉴시스",
            "대한경제",
        ],
    },
}


def collect_purchase_news():

    collected = {}

    for key, rule in CATEGORY_RULES.items():

        print(
            f"[구매뉴스] {rule['name']}"
        )

        result = collect_with_freshness(
            rule["query"],
            rule
        )

        collected[key] = {
            "name": rule["name"],
            "freshness":
                result["freshness"],
            "articles":
                result["articles"],
        }

        print(
            " →",
            result["freshness"],
            len(result["articles"]),
            "건"
        )

    return collected


# ============================================================
# 환율 전용 수집
# ============================================================

def find_yonhap_fx_articles():

    queries = [
        (
            "연합뉴스 원 달러 환율 "
            "서울외환시장"
        ),
        (
            "연합뉴스 원달러 환율 "
            "서울 외환시장"
        ),
    ]

    candidates = []

    for query in queries:

        articles = google_news_search(
            query,
            days=2,
            limit=30
        )

        for article in articles:

            source = normalize(
                article.get(
                    "source",
                    ""
                )
            )

            title = normalize(
                article.get(
                    "title",
                    ""
                )
            )

            # 연합뉴스 기사만 사용
            if "연합뉴스" not in source:
                continue

            # 환율 관련 기사만 사용
            if not (
                "환율" in title
                or "원/달러" in title
                or "원달러" in title
                or "달러" in title
            ):
                continue

            candidates.append(
                article
            )

    candidates = remove_duplicates(
        candidates
    )

    return candidates


def resolve_google_news_url(url):

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20,
            allow_redirects=True
        )

        return response.url

    except Exception:
        return url


def fetch_article_text(url):

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20,
            allow_redirects=True
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        # script/style 제거
        for tag in soup(
            ["script", "style"]
        ):
            tag.decompose()

        return soup.get_text(
            " ",
            strip=True
        )

    except Exception as exc:

        print(
            "[환율 기사 본문 읽기 실패]",
            exc
        )

        return ""


def parse_number(value):

    try:
        return float(
            value.replace(",", "")
        )
    except Exception:
        return None


def format_rate(value):

    if value is None:
        return None

    return (
        f"{value:,.2f}"
        .rstrip("0")
        .rstrip(".")
        + "원"
    )


def extract_fx_market_data(text):

    result = {
        "current_rate": None,
        "previous_rate": None,
        "change": None,
        "direction": None,
    }

    if not text:
        return result

    # --------------------------------------------------------
    # 1. "전 거래일보다 1.5원 내린 1,383.3원"
    #    형태 우선
    # --------------------------------------------------------

    pattern1 = re.search(
        r"전\s*거래일(?:보다|에\s*비해)?"
        r".{0,35}?"
        r"(\d+(?:\.\d+)?)원"
        r".{0,12}?"
        r"(내린|하락한|떨어진|오른|상승한)"
        r".{0,35}?"
        r"(1,\d{3}(?:\.\d+)?)원",
        text
    )

    if pattern1:

        change_value = float(
            pattern1.group(1)
        )

        direction_word = (
            pattern1.group(2)
        )

        current = parse_number(
            pattern1.group(3)
        )

        direction = (
            "down"
            if direction_word in [
                "내린",
                "하락한",
                "떨어진",
            ]
            else "up"
        )

        previous = None

        if current is not None:

            if direction == "down":
                previous = (
                    current
                    + change_value
                )
            else:
                previous = (
                    current
                    - change_value
                )

        result.update({
            "current_rate":
                format_rate(current),

            "previous_rate":
                format_rate(previous),

            "change":
                f"{change_value:g}원",

            "direction":
                direction,
        })

        return result

    # --------------------------------------------------------
    # 2. "1,383.3원으로 전 거래일보다 1.5원 내렸다"
    # --------------------------------------------------------

    pattern2 = re.search(
        r"(1,\d{3}(?:\.\d+)?)원"
        r".{0,50}?"
        r"전\s*거래일(?:보다|에\s*비해)?"
        r".{0,30}?"
        r"(\d+(?:\.\d+)?)원"
        r".{0,10}?"
        r"(내렸|하락|떨어졌|올랐|상승)",
        text
    )

    if pattern2:

        current = parse_number(
            pattern2.group(1)
        )

        change_value = float(
            pattern2.group(2)
        )

        direction_word = (
            pattern2.group(3)
        )

        direction = (
            "down"
            if direction_word in [
                "내렸",
                "하락",
                "떨어졌",
            ]
            else "up"
        )

        previous = None

        if current is not None:

            if direction == "down":
                previous = (
                    current
                    + change_value
                )
            else:
                previous = (
                    current
                    - change_value
                )

        result.update({
            "current_rate":
                format_rate(current),

            "previous_rate":
                format_rate(previous),

            "change":
                f"{change_value:g}원",

            "direction":
                direction,
        })

        return result

    return result


def collect_fx():

    print(
        "[환율] 연합뉴스 "
        "서울외환시장 검색"
    )

    articles = (
        find_yonhap_fx_articles()
    )

    for article in articles:

        original_url = (
            article.get(
                "link",
                ""
            )
        )

        resolved_url = (
            resolve_google_news_url(
                original_url
            )
        )

        text = fetch_article_text(
            resolved_url
        )

        fx = extract_fx_market_data(
            text
        )

        if fx["current_rate"]:

            fx.update({
                "status":
                    "확인 완료",

                "source":
                    "연합뉴스",

                "source_url":
                    resolved_url,

                "article_title":
                    article.get(
                        "title",
                        ""
                    ),

                "published":
                    article.get(
                        "published",
                        ""
                    ),
            })

            print(
                " → 환율 추출 성공:",
                fx["current_rate"]
            )

            return fx

    # 실패 시 이전 값 사용 금지
    print(
        " → 환율 자동추출 실패"
    )

    return {
        "current_rate": None,
        "previous_rate": None,
        "change": None,
        "direction": None,
        "status": "확인 필요",
        "source": "연합뉴스",
        "source_url": None,
        "article_title": None,
        "published": None,
    }


# ============================================================
# JSON 저장
# ============================================================

def save_result(data):

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    OUTPUT_FILE.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


# ============================================================
# 실행
# ============================================================

def main():

    current_time = now_kst()

    print("=" * 60)
    print(
        "AJU 구매팀 브리핑 "
        "자동수집"
    )
    print(
        "실행:",
        current_time.strftime(
            "%Y-%m-%d %H:%M KST"
        )
    )
    print("=" * 60)

    # 환율은 뉴스와 별도 수집
    fx = collect_fx()

    # 구매 관련 뉴스 7개 영역
    purchase_news = (
        collect_purchase_news()
    )

    result = {

        "generated_at_kst":
            current_time.strftime(
                "%Y-%m-%d %H:%M"
            ),

        "status":
            "AJU 구매 브리핑 데이터 수집 완료",

        "market_data": {
            "fx": fx
        },

        "news":
            purchase_news,
    }

    save_result(result)

    print("")
    print("[환율 결과]")
    print(
        json.dumps(
            fx,
            ensure_ascii=False,
            indent=2
        )
    )

    print("")
    print(
        "저장 완료:",
        OUTPUT_FILE
    )


if __name__ == "__main__":
    main()

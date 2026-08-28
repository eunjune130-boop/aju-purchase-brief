from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
import json
import re

import feedparser
import requests


# ============================================================
# AJU 구매팀 브리핑 자동수집
#
# [환율]
# Frankfurter API 사용
# → 최신 USD/KRW
# → 직전 영업일 USD/KRW
# → 등락
# → 출처 저장
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
        key=lambda x: x["relevance_score"],
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
# 환율 전용 수집 - Frankfurter API
# ============================================================

def collect_fx():

    print(
        "[환율] Frankfurter API "
        "USD/KRW 수집"
    )

    try:

        today = now_kst().date()

        start_date = (
            today
            - timedelta(days=10)
        )

        url = (
            "https://api.frankfurter.dev/v1/"
            f"{start_date.isoformat()}.."
            f"{today.isoformat()}"
            "?base=USD&symbols=KRW"
        )

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20
        )

        response.raise_for_status()

        data = response.json()

        rates = data.get(
            "rates",
            {}
        )

        rows = []

        for date, values in sorted(
            rates.items()
        ):

            krw = values.get(
                "KRW"
            )

            if krw is None:
                continue

            rows.append(
                (
                    date,
                    float(krw)
                )
            )

        if len(rows) < 2:

            raise ValueError(
                "비교 가능한 환율 데이터가 "
                "2건 미만입니다."
            )

        previous_date, previous_rate = (
            rows[-2]
        )

        current_date, current_rate = (
            rows[-1]
        )

        change_value = (
            current_rate
            - previous_rate
        )

        if change_value > 0:
            direction = "up"

        elif change_value < 0:
            direction = "down"

        else:
            direction = "flat"

        result = {

            "current_rate":
                f"{current_rate:,.2f}원",

            "previous_rate":
                f"{previous_rate:,.2f}원",

            "change":
                f"{abs(change_value):,.2f}원",

            "direction":
                direction,

            "current_date":
                current_date,

            "previous_date":
                previous_date,

            "status":
                "확인 완료",

            "source":
                "Frankfurter API",

            "source_url":
                "https://frankfurter.dev/",

            "note":
                "중앙은행 데이터 기반 "
                "USD/KRW 일일 기준 환율",
        }

        print(
            " → 현재:",
            result["current_rate"]
        )

        print(
            " → 전 거래일:",
            result["previous_rate"]
        )

        print(
            " → 변동:",
            result["change"],
            result["direction"]
        )

        return result

    except Exception as exc:

        print(
            " → 환율 수집 실패:",
            exc
        )

        return {

            "current_rate": None,

            "previous_rate": None,

            "change": None,

            "direction": None,

            "current_date": None,

            "previous_date": None,

            "status":
                "확인 필요",

            "source":
                "Frankfurter API",

            "source_url":
                "https://frankfurter.dev/",

            "note":
                "환율 자동수집 실패",
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

    # 환율
    fx = collect_fx()

    # 구매 뉴스
    purchase_news = (
        collect_purchase_news()
    )

    result = {

        "generated_at_kst":
            current_time.strftime(
                "%Y-%m-%d %H:%M"
            ),

        "status":
            "AJU 구매 브리핑 "
            "데이터 수집 완료",

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

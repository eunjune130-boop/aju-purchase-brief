from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
import json
import re

import feedparser
import requests


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_FILE = DATA_DIR / "latest.json"

KST = timezone(timedelta(hours=9))

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
    return datetime.now(KST)


def normalize(text):
    if not text:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(text).lower()
    ).strip()


def format_rate(value):
    if value is None:
        return None

    return f"{float(value):,.2f}원"


def format_change(value):
    if value is None:
        return None

    return f"{abs(float(value)):,.2f}원"


# ============================================================
# Google News RSS
# ============================================================

def google_news_search(query, days=2, limit=20):

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
# 뉴스 관련성 평가
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


def collect_category(
    rule
):

    ranges = [
        (2, "오늘·어제"),
        (3, "최근 3일"),
        (7, "최근 7일"),
    ]

    for days, label in ranges:

        all_articles = []

        # 검색어를 하나씩 따로 검색
        for query in rule["queries"]:

            found = google_news_search(
                query=query,
                days=days,
                limit=20
            )

            all_articles.extend(
                found
            )

        # 중복 제거
        all_articles = remove_duplicates(
            all_articles
        )

        scored = []

        for article in all_articles:

            score = score_article(
                article,
                rule
            )

            # 기존보다 조금 완화
            if score < 2:
                continue

            item = dict(article)
            item["relevance_score"] = score

            scored.append(item)

        scored.sort(
            key=lambda x: x[
                "relevance_score"
            ],
            reverse=True
        )

        if scored:

            return {
                "freshness": label,
                "articles": scored[:5],
                "raw_count":
                    len(all_articles),
            }

    return {
        "freshness":
            "특이사항 없음",

        "articles": [],

        "raw_count": 0,
    }


# ============================================================
# 구매 뉴스 7개 영역
# ============================================================

CATEGORY_RULES = {

    "cement_slag": {

        "name":
            "시멘트·슬래그",

        "queries": [
            "시멘트 가격",
            "시멘트 공급",
            "시멘트 출하",
            "시멘트 생산",
            "시멘트 공장 정비",
            "고로슬래그 가격",
            "슬래그 시멘트",
        ],

        "strong_keywords": [
            "시멘트",
            "고로슬래그",
            "슬래그",
        ],

        "keywords": [
            "가격",
            "공급",
            "출하",
            "생산",
            "정비",
            "공장",
            "가동",
        ],

        "support_keywords": [
            "전력비",
            "환경규제",
            "원가",
            "탄소",
        ],

        "preferred_sources": [
            "연합뉴스",
            "대한경제",
            "뉴시스",
            "뉴스핌",
        ],
    },


    "energy": {

        "name":
            "유연탄·에너지",

        "queries": [
            "유연탄 가격",
            "석탄 가격",
            "Newcastle Coal",
            "브렌트유 가격",
            "국제유가",
            "LNG 가격",
            "천연가스 가격",
        ],

        "strong_keywords": [
            "유연탄",
            "석탄",
            "브렌트",
            "국제유가",
            "lng",
            "천연가스",
        ],

        "keywords": [
            "가격",
            "유가",
            "원유",
            "에너지",
        ],

        "support_keywords": [
            "운송비",
            "연료비",
            "수입",
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

        "name":
            "골재·모래",

        "queries": [
            "골재 가격",
            "골재 공급",
            "골재 부족",
            "골재 채취허가",
            "석산 골재",
            "모래 가격 건설",
            "레미콘 골재",
        ],

        "strong_keywords": [
            "골재",
            "석산",
            "채취허가",
            "레미콘",
        ],

        "keywords": [
            "모래",
            "가격",
            "공급",
            "채석",
        ],

        "support_keywords": [
            "운송",
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

        "name":
            "철강·PHC",

        "queries": [
            "PC강봉 가격",
            "PHC 파일 원자재",
            "선재 가격",
            "철근 가격",
            "철스크랩 가격",
            "철광석 가격",
            "중국 철강 가격",
        ],

        "strong_keywords": [
            "pc강봉",
            "phc",
            "철강",
            "철근",
            "선재",
            "철광석",
            "철스크랩",
        ],

        "keywords": [
            "고철",
            "강재",
            "가격",
            "공급",
        ],

        "support_keywords": [
            "원자재",
            "수입",
            "중국",
        ],

        "preferred_sources": [
            "스틸데일리",
            "철강금속신문",
            "연합뉴스",
            "뉴스핌",
        ],
    },


    "logistics": {

        "name":
            "물류",

        "queries": [
            "BDI 지수",
            "Baltic Dry Index",
            "벌크선 운임",
            "해상운임",
            "철광석 해상운임",
            "석탄 해상운임",
            "항만 물류",
        ],

        "strong_keywords": [
            "bdi",
            "baltic dry",
            "벌크선",
            "해상운임",
        ],

        "keywords": [
            "운임",
            "물류",
            "항만",
            "해운",
            "선박",
        ],

        "support_keywords": [
            "석탄",
            "철광석",
            "수입",
        ],

        "preferred_sources": [
            "쉬핑뉴스넷",
            "해사신문",
            "연합뉴스",
            "한국경제",
        ],
    },


    "construction": {

        "name":
            "건설시장",

        "queries": [
            "건설수주",
            "건설 착공",
            "건설투자",
            "SOC 투자",
            "공공공사 발주",
            "민간 건설경기",
            "주택 착공",
        ],

        "strong_keywords": [
            "건설수주",
            "착공",
            "건설투자",
            "soc",
        ],

        "keywords": [
            "건설경기",
            "공공공사",
            "민간공사",
            "주택",
            "인프라",
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

        "name":
            "공급사",

        "queries": [
            "삼표시멘트 가격",
            "한일시멘트 공급",
            "쌍용C&E 시멘트",
            "아세아시멘트 가격",
            "성신양회 시멘트",
            "유진기업 레미콘",
            "삼표 골재",
            "현대제철 선재",
            "포스코 철강 가격",
        ],

        "strong_keywords": [
            "삼표",
            "유진기업",
            "한일시멘트",
            "쌍용c&e",
            "아세아시멘트",
            "성신양회",
            "현대제철",
            "포스코",
        ],

        "keywords": [
            "시멘트",
            "레미콘",
            "골재",
            "철강",
            "가격",
            "공급",
        ],

        "support_keywords": [
            "생산",
            "공장",
            "정비",
            "파업",
        ],

        "preferred_sources": [
            "연합뉴스",
            "대한경제",
            "뉴스핌",
            "뉴시스",
        ],
    },
}


def collect_purchase_news():

    collected = {}

    for key, rule in (
        CATEGORY_RULES.items()
    ):

        print(
            f"[구매뉴스] "
            f"{rule['name']}"
        )

        result = collect_category(
            rule
        )

        collected[key] = {

            "name":
                rule["name"],

            "freshness":
                result["freshness"],

            "articles":
                result["articles"],

            "raw_count":
                result["raw_count"],
        }

        print(
            " →",
            result["freshness"],
            len(result["articles"]),
            "건 / 검색결과",
            result["raw_count"],
            "건"
        )

    return collected


# ============================================================
# 환율 1순위 - Yahoo Finance
# ============================================================

def collect_fx_yahoo():

    print(
        "[환율 1순위] "
        "Yahoo Finance USD/KRW"
    )

    try:

        intraday_url = (
            "https://query1.finance.yahoo.com/"
            "v8/finance/chart/KRW=X"
            "?range=1d&interval=5m"
        )

        response = requests.get(
            intraday_url,
            headers=HEADERS,
            timeout=20
        )

        response.raise_for_status()

        data = response.json()

        result = (
            data["chart"]["result"][0]
        )

        meta = result["meta"]

        current_rate = (
            meta.get(
                "regularMarketPrice"
            )
        )

        market_time = (
            meta.get(
                "regularMarketTime"
            )
        )

        if current_rate is None:

            raise ValueError(
                "Yahoo 현재 환율 없음"
            )


        daily_url = (
            "https://query1.finance.yahoo.com/"
            "v8/finance/chart/KRW=X"
            "?range=5d&interval=1d"
        )

        response2 = requests.get(
            daily_url,
            headers=HEADERS,
            timeout=20
        )

        response2.raise_for_status()

        daily_data = response2.json()

        daily_result = (
            daily_data[
                "chart"
            ][
                "result"
            ][0]
        )

        timestamps = (
            daily_result.get(
                "timestamp",
                []
            )
        )

        quote_data = (
            daily_result[
                "indicators"
            ][
                "quote"
            ][0]
        )

        closes = (
            quote_data.get(
                "close",
                []
            )
        )

        daily_rows = []

        for ts, close in zip(
            timestamps,
            closes
        ):

            if close is None:
                continue

            date_kst = (
                datetime
                .fromtimestamp(
                    ts,
                    timezone.utc
                )
                .astimezone(
                    KST
                )
                .date()
            )

            daily_rows.append(
                (
                    date_kst,
                    float(close)
                )
            )


        if not daily_rows:

            raise ValueError(
                "Yahoo 전 거래일 환율 없음"
            )


        if market_time:

            current_datetime = (
                datetime
                .fromtimestamp(
                    market_time,
                    timezone.utc
                )
                .astimezone(
                    KST
                )
            )

        else:

            current_datetime = (
                now_kst()
            )


        current_date = (
            current_datetime.date()
        )


        if (
            daily_rows[-1][0]
            == current_date
            and len(daily_rows) >= 2
        ):

            previous_date = (
                daily_rows[-2][0]
            )

            previous_rate = (
                daily_rows[-2][1]
            )

        else:

            previous_date = (
                daily_rows[-1][0]
            )

            previous_rate = (
                daily_rows[-1][1]
            )


        change_value = (
            float(current_rate)
            - float(previous_rate)
        )


        if change_value > 0:
            direction = "up"

        elif change_value < 0:
            direction = "down"

        else:
            direction = "flat"


        return {

            "current_rate":
                format_rate(
                    current_rate
                ),

            "previous_rate":
                format_rate(
                    previous_rate
                ),

            "change":
                format_change(
                    change_value
                ),

            "direction":
                direction,

            "current_date":
                current_date.isoformat(),

            "current_time":
                current_datetime.strftime(
                    "%H:%M"
                ),

            "previous_date":
                previous_date.isoformat(),

            "status":
                "확인 완료",

            "data_type":
                "장중 환율",

            "source":
                "Yahoo Finance",

            "source_url":
                "https://finance.yahoo.com/"
                "quote/KRW=X/",

            "note":
                "USD/KRW 장중 환율 및 "
                "전 거래일 종가 기준",
        }


    except Exception as exc:

        print(
            " → Yahoo 환율 수집 실패:",
            exc
        )

        return None


# ============================================================
# 환율 2순위 - Frankfurter
# ============================================================

def collect_fx_frankfurter():

    print(
        "[환율 2순위] "
        "Frankfurter API"
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

        rates = (
            data.get(
                "rates",
                {}
            )
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
                "Frankfurter 환율 부족"
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


        return {

            "current_rate":
                format_rate(
                    current_rate
                ),

            "previous_rate":
                format_rate(
                    previous_rate
                ),

            "change":
                format_change(
                    change_value
                ),

            "direction":
                direction,

            "current_date":
                current_date,

            "current_time":
                None,

            "previous_date":
                previous_date,

            "status":
                "확인 완료",

            "data_type":
                "일일 기준 환율",

            "source":
                "Frankfurter API",

            "source_url":
                "https://frankfurter.dev/",

            "note":
                "Yahoo Finance 실패 시 "
                "사용하는 일일 기준 환율",
        }


    except Exception as exc:

        print(
            " → Frankfurter 실패:",
            exc
        )

        return None


def collect_fx():

    yahoo = collect_fx_yahoo()

    if yahoo:
        return yahoo

    frankfurter = (
        collect_fx_frankfurter()
    )

    if frankfurter:
        return frankfurter


    return {

        "current_rate": None,
        "previous_rate": None,
        "change": None,
        "direction": None,
        "current_date": None,
        "current_time": None,
        "previous_date": None,
        "status": "확인 필요",
        "data_type": None,
        "source": None,
        "source_url": None,
        "note": "환율 자동수집 실패",
    }


# ============================================================
# 저장
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


def main():

    current_time = now_kst()

    print("=" * 60)
    print("AJU 구매팀 브리핑 자동수집")

    print(
        "실행:",
        current_time.strftime(
            "%Y-%m-%d %H:%M KST"
        )
    )

    print("=" * 60)


    fx = collect_fx()

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


    save_result(
        result
    )


    print("")
    print("[최종 환율 결과]")

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

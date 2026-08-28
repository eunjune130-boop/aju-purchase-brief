from datetime import datetime, timedelta, timezone
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
# 1순위 : Yahoo Finance USD/KRW 장중 환율
# 2순위 : Frankfurter API 일일 기준 환율
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

    result = remove_duplicates(
        result
    )

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
# 구매 뉴스 7개 영역
# ============================================================

CATEGORY_RULES = {

    "cement_slag": {

        "name":
            "시멘트·슬래그",

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

        "name":
            "유연탄·에너지",

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

        "name":
            "골재·모래",

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

        "name":
            "철강·PHC",

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

        "name":
            "물류",

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

        "name":
            "건설시장",

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

        "name":
            "공급사",

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

    for key, rule in (
        CATEGORY_RULES.items()
    ):

        print(
            f"[구매뉴스] "
            f"{rule['name']}"
        )

        result = (
            collect_with_freshness(
                rule["query"],
                rule
            )
        )

        collected[key] = {

            "name":
                rule["name"],

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
# 환율 1순위
# Yahoo Finance USD/KRW 장중 환율
# ============================================================

def collect_fx_yahoo():

    print(
        "[환율 1순위] "
        "Yahoo Finance USD/KRW"
    )

    try:

        # ----------------------------------------------------
        # 현재 장중 환율
        # ----------------------------------------------------

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
                "Yahoo 현재 환율이 없습니다."
            )


        # ----------------------------------------------------
        # 최근 거래일 종가
        # ----------------------------------------------------

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
                "Yahoo 이전 거래일 "
                "환율이 없습니다."
            )


        # ----------------------------------------------------
        # 현재 환율의 날짜
        # ----------------------------------------------------

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


        # ----------------------------------------------------
        # 전 거래일 종가 선택
        #
        # 일봉 마지막 날짜가 오늘이라면
        # 그 전 값을 사용
        #
        # 일봉 마지막 날짜가 이전 거래일이면
        # 마지막 값을 사용
        # ----------------------------------------------------

        previous_rate = None
        previous_date = None

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


        # ----------------------------------------------------
        # 등락 계산
        # ----------------------------------------------------

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


        result = {

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
                "USD/KRW 장중 환율 "
                "및 전 거래일 종가 기준",
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
            " → Yahoo 환율 수집 실패:",
            exc
        )

        return None


# ============================================================
# 환율 2순위
# Frankfurter API
# ============================================================

def collect_fx_frankfurter():

    print(
        "[환율 2순위] "
        "Frankfurter API"
    )

    try:

        today = (
            now_kst().date()
        )

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
                "Frankfurter 환율 데이터 "
                "부족"
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
                "Yahoo Finance 수집 실패 시 "
                "사용하는 일일 기준 환율",
        }

        print(
            " → 현재:",
            result["current_rate"]
        )

        return result


    except Exception as exc:

        print(
            " → Frankfurter 환율 "
            "수집 실패:",
            exc
        )

        return None


# ============================================================
# 최종 환율 수집
# ============================================================

def collect_fx():

    # 1순위
    yahoo = (
        collect_fx_yahoo()
    )

    if yahoo:
        return yahoo


    # 2순위
    frankfurter = (
        collect_fx_frankfurter()
    )

    if frankfurter:
        return frankfurter


    # 둘 다 실패
    return {

        "current_rate": None,

        "previous_rate": None,

        "change": None,

        "direction": None,

        "current_date": None,

        "current_time": None,

        "previous_date": None,

        "status":
            "확인 필요",

        "data_type":
            None,

        "source":
            None,

        "source_url":
            None,

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

    current_time = (
        now_kst()
    )

    print("=" * 60)

    print(
        "AJU 구매팀 브리핑 "
        "자동수집"
    )

    print(
        "실행:",
        current_time.strftime(
            "%Y-%m-%d "
            "%H:%M KST"
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

            "fx":
                fx
        },

        "news":
            purchase_news,
    }


    save_result(
        result
    )


    print("")

    print(
        "[최종 환율 결과]"
    )

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

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
import json
import re
import difflib

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

    text = str(text).lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[\"'“”‘’]", "", text)
    return text.strip()


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

    encoded_query = quote(f"{query} when:{days}d")

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
# 뉴스 필터
# ============================================================

GLOBAL_EXCLUDE_KEYWORDS = [
    "주가",
    "증시",
    "코스피",
    "코스닥",
    "목표주가",
    "배당",
    "상한가",
    "하한가",
    "급등주",
    "테마주",
    "증권사",
    "매수 추천",
    "비트코인",
    "가상자산",
    "암호화폐",
    "etf",
    "교통사고",
    "사망",
    "부상",
    "추돌",
    "충돌",
    "범죄",
    "절도",
    "폭행",
    "불법매립",
    "폐기물 불법",
    "관광",
    "축제",
    "해수욕장",
    "스포츠",
]


PURCHASE_CORE_KEYWORDS = [
    "가격",
    "인상",
    "인하",
    "하락",
    "상승",
    "공급",
    "수급",
    "출하",
    "생산",
    "가동",
    "정비",
    "보수",
    "원가",
    "재고",
    "수입",
    "수출",
    "운임",
    "운송",
    "계약",
    "부족",
    "차질",
    "중단",
    "투자",
    "착공",
    "수주",
    "발주",
    "원료",
    "원자재",
    "채취",
    "허가",
]


def contains_any(text, keywords):
    text = normalize(text)

    for keyword in keywords:
        if normalize(keyword) in text:
            return True

    return False


def article_is_excluded(article, rule):

    title = normalize(article.get("title", ""))

    exclude_words = (
        GLOBAL_EXCLUDE_KEYWORDS
        + rule.get("exclude_keywords", [])
    )

    return contains_any(title, exclude_words)


def article_has_purchase_core(article):

    title = normalize(article.get("title", ""))

    return contains_any(
        title,
        PURCHASE_CORE_KEYWORDS
    )


def score_article(article, rule):

    title = normalize(article.get("title", ""))
    source = normalize(article.get("source", ""))

    text = f"{title} {source}"
    score = 0

    for keyword in rule.get("strong_keywords", []):
        if normalize(keyword) in text:
            score += 5

    for keyword in rule.get("keywords", []):
        if normalize(keyword) in text:
            score += 2

    for keyword in rule.get("support_keywords", []):
        if normalize(keyword) in text:
            score += 1

    for media in rule.get("preferred_sources", []):
        if normalize(media) in source:
            score += 1

    if article_has_purchase_core(article):
        score += 3

    return score


# ============================================================
# 중복기사 제거
# ============================================================

def clean_title_for_similarity(title):

    text = normalize(title)

    text = re.sub(
        r"\s*-\s*[^-]+$",
        "",
        text
    )

    text = re.sub(
        r"[\[\]\(\)〈〉<>]",
        " ",
        text
    )

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def is_similar_title(title_a, title_b, threshold=0.68):

    a = clean_title_for_similarity(title_a)
    b = clean_title_for_similarity(title_b)

    if not a or not b:
        return False

    ratio = difflib.SequenceMatcher(
        None,
        a,
        b
    ).ratio()

    return ratio >= threshold


def remove_similar_articles(articles):

    selected = []

    for article in articles:

        duplicate = False

        for existing in selected:

            if is_similar_title(
                article.get("title", ""),
                existing.get("title", "")
            ):
                duplicate = True
                break

        if not duplicate:
            selected.append(article)

    return selected


# ============================================================
# 카테고리별 뉴스 수집
# ============================================================

def collect_category(rule):

    search_ranges = [
        (2, "오늘·어제"),
        (3, "최근 3일"),
        (7, "최근 7일"),
    ]

    last_raw_count = 0

    for days, label in search_ranges:

        all_articles = []

        for query in rule["queries"]:

            found = google_news_search(
                query=query,
                days=days,
                limit=20
            )

            all_articles.extend(found)

        raw_count = len(all_articles)
        last_raw_count = raw_count

        filtered = []

        for article in all_articles:

            if article_is_excluded(article, rule):
                continue

            title = normalize(
                article.get("title", "")
            )

            category_match = (
                contains_any(
                    title,
                    rule.get("strong_keywords", [])
                )
                or contains_any(
                    title,
                    rule.get("keywords", [])
                )
            )

            if not category_match:
                continue

            # 일반 카테고리는 구매 핵심어를 요구하지만,
            # 골재는 시장 기사 자체가 적어 별도 완화 조건 적용
            if rule.get("relaxed_purchase_filter", False):

                strong_match = contains_any(
                    title,
                    rule.get("strong_keywords", [])
                )

                purchase_match = article_has_purchase_core(
                    article
                )

                if not strong_match:
                    continue

                if not (
                    purchase_match
                    or contains_any(
                        title,
                        rule.get(
                            "aggregate_context_keywords",
                            []
                        )
                    )
                ):
                    continue

            else:

                if not article_has_purchase_core(article):

                    strong_count = 0

                    for keyword in rule.get(
                        "strong_keywords",
                        []
                    ):
                        if normalize(keyword) in title:
                            strong_count += 1

                    if strong_count < 2:
                        continue

            score = score_article(
                article,
                rule
            )

            minimum_score = rule.get(
                "minimum_score",
                6
            )

            if score < minimum_score:
                continue

            item = dict(article)
            item["relevance_score"] = score

            filtered.append(item)

        filtered.sort(
            key=lambda x: x["relevance_score"],
            reverse=True
        )

        filtered = remove_similar_articles(
            filtered
        )

        if filtered:

            return {
                "freshness": label,
                "articles": filtered[:5],
                "raw_count": raw_count,
                "selected_count": min(
                    len(filtered),
                    5
                ),
            }

    return {
        "freshness": "특이사항 없음",
        "articles": [],
        "raw_count": last_raw_count,
        "selected_count": 0,
    }


# ============================================================
# 뉴스 카테고리
# ============================================================

CATEGORY_RULES = {

    "cement_slag": {

        "name": "시멘트·슬래그",

        "queries": [
            "시멘트 가격",
            "시멘트 공급",
            "시멘트 출하",
            "시멘트 생산",
            "시멘트 공장 정비",
            "고로슬래그 가격",
            "슬래그 시멘트 가격",
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
            "원가",
        ],

        "support_keywords": [
            "전력비",
            "환경규제",
            "탄소",
            "건설경기",
        ],

        "exclude_keywords": [
            "ai 도입",
            "스마트공장 홍보",
            "취임",
            "대표이사",
            "사회공헌",
            "봉사활동",
        ],

        "preferred_sources": [
            "연합뉴스",
            "대한경제",
            "뉴시스",
            "뉴스핌",
        ],
    },


    "energy": {

        "name": "유연탄·에너지",

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
            "수입",
        ],

        "support_keywords": [
            "운송비",
            "연료비",
            "원가",
        ],

        "exclude_keywords": [
            "주유소 행사",
            "전기차 판매",
        ],

        "preferred_sources": [
            "연합뉴스",
            "로이터",
            "뉴스1",
            "한국경제",
        ],
    },


    # ========================================================
    # #8 핵심 변경 부분 : 골재·모래
    # ========================================================

    "aggregate": {

        "name": "골재·모래",
"queries": [
    "골재 가격 건설",
    "골재 공급 건설",
    "골재 수급",
    "골재 부족",
    "레미콘 골재",
    "골재 채취",
    "골재 채취 허가",
    "석산 골재",
    "석산 개발",
    "석산 운영",
    "석산 채취 허가",
    "토석 채취",
    "토석 채취 허가",
    "채석장 운영",
    "모래 골재 건설",
    "바닷모래 골재",
    "바닷모래 채취",
    "순환골재 건설",
    "골재 환경규제",
    "석산 환경규제",
],
        
      "strong_keywords": [
    "골재",
    "바닷모래",
    "순환골재",
    "석산",
    "토석",
    "채석장",
    "채취허가",
    "채취 허가",
],
        "keywords": [
            "가격",
            "공급",
            "수급",
            "부족",
            "채취",
            "허가",
            "모래",
            "레미콘",
            "건설자재",
            "개발",
"운영",
"환경규제",
"민원",
        ],

        "support_keywords": [
            "운송",
            "수도권",
            "건설",
            "공사",
            "환경규제",
            "원가",
        ],

        "aggregate_context_keywords": [
            "레미콘",
            "건설",
            "건설자재",
            "채취",
            "허가",
            "수급",
            "공급",
            "가격",
            "부족",
            "운송",
        ],

      "exclude_keywords": [
    "교통사고",
    "사망",
    "부상",
    "충돌",
    "추돌",
    "덤프트럭 사고",
    "전신주",
    "불법매립",
    "폐기물",
    "쓰레기",
    "범죄",
    "공장 철거",
    "전격 철거",
    "악취",
],

        "preferred_sources": [
            "연합뉴스",
            "대한경제",
            "뉴시스",
            "건설경제",
            "건설신문",
        ],

        "relaxed_purchase_filter": True,
        "minimum_score": 6,
    },


    "steel_phc": {

        "name": "철강·PHC",

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
            "원료",
        ],

        "support_keywords": [
            "원자재",
            "수입",
            "중국",
            "원가",
        ],

        "exclude_keywords": [
            "배당",
            "실적 발표",
            "주주",
            "영업이익",
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
            "운송",
        ],

        "exclude_keywords": [
            "택배 이벤트",
            "배달앱",
            "쇼핑",
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
            "공공공사",
        ],

        "keywords": [
            "건설경기",
            "민간공사",
            "주택",
            "인프라",
            "발주",
        ],

        "support_keywords": [
            "레미콘",
            "건자재",
            "시멘트",
            "phc",
        ],

        "exclude_keywords": [
            "분양 광고",
            "청약 경쟁률",
            "아파트 시세",
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
            "원가",
        ],

        "exclude_keywords": [
            "사회공헌",
            "기부",
            "봉사",
            "인사",
            "취임",
            "채용",
        ],

        "preferred_sources": [
            "연합뉴스",
            "대한경제",
            "뉴스핌",
            "뉴시스",
        ],
    },
}


# ============================================================
# 구매 뉴스 실행
# ============================================================

def collect_purchase_news():

    collected = {}

    for key, rule in CATEGORY_RULES.items():

        print(
            f"[구매뉴스] {rule['name']}"
        )

        result = collect_category(
            rule
        )

        collected[key] = {
            "name": rule["name"],
            "freshness": result["freshness"],
            "articles": result["articles"],
            "raw_count": result["raw_count"],
            "selected_count": result["selected_count"],
        }

        print(
            " →",
            result["freshness"],
            result["selected_count"],
            "건 선택 / 검색결과",
            result["raw_count"],
            "건"
        )

    return collected


# ============================================================
# USD/KRW - Yahoo Finance
# ============================================================

def collect_fx_yahoo():

    print(
        "[환율 1순위] Yahoo Finance USD/KRW"
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

        result = (
            response.json()
            ["chart"]["result"][0]
        )

        meta = result["meta"]

        current_rate = meta.get(
            "regularMarketPrice"
        )

        market_time = meta.get(
            "regularMarketTime"
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

        daily_result = (
            response2.json()
            ["chart"]["result"][0]
        )

        timestamps = daily_result.get(
            "timestamp",
            []
        )

        closes = (
            daily_result["indicators"]
            ["quote"][0]
            .get("close", [])
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
                .astimezone(KST)
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
                .astimezone(KST)
            )

        else:
            current_datetime = now_kst()

        current_date = (
            current_datetime.date()
        )

        if (
            daily_rows[-1][0]
            == current_date
            and len(daily_rows) >= 2
        ):
            previous_date = daily_rows[-2][0]
            previous_rate = daily_rows[-2][1]

        else:
            previous_date = daily_rows[-1][0]
            previous_rate = daily_rows[-1][1]

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
                format_rate(current_rate),

            "previous_rate":
                format_rate(previous_rate),

            "change":
                format_change(change_value),

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
                "https://finance.yahoo.com/quote/KRW=X/",

            "note":
                "USD/KRW 장중 환율 및 전 거래일 종가 기준",
        }

    except Exception as exc:

        print(
            " → Yahoo 환율 수집 실패:",
            exc
        )

        return None


# ============================================================
# 환율 보조 - Frankfurter
# ============================================================

def collect_fx_frankfurter():

    print(
        "[환율 2순위] Frankfurter API"
    )

    try:

        today = now_kst().date()

        start_date = (
            today - timedelta(days=10)
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

        rates = response.json().get(
            "rates",
            {}
        )

        rows = []

        for date, values in sorted(
            rates.items()
        ):

            krw = values.get("KRW")

            if krw is not None:
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
            current_rate - previous_rate
        )

        if change_value > 0:
            direction = "up"
        elif change_value < 0:
            direction = "down"
        else:
            direction = "flat"

        return {
            "current_rate":
                format_rate(current_rate),

            "previous_rate":
                format_rate(previous_rate),

            "change":
                format_change(change_value),

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
                "Yahoo Finance 실패 시 사용하는 일일 기준 환율",
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
# ============================================================
# 시장지표 자동수집
# Brent - Yahoo Finance
# ============================================================

def collect_brent_yahoo():

    print("[시장지표] Brent Crude Oil")

    try:

        symbol = "BZ=F"

        url = (
            "https://query1.finance.yahoo.com/"
            f"v8/finance/chart/{symbol}"
            "?range=5d&interval=1d"
        )

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20
        )

        response.raise_for_status()

        data = response.json()

        result = data["chart"]["result"][0]

        timestamps = result.get(
            "timestamp",
            []
        )

        closes = (
            result["indicators"]
            ["quote"][0]
            .get("close", [])
        )

        rows = []

        for ts, close in zip(
            timestamps,
            closes
        ):

            if close is None:
                continue

            market_date = (
                datetime
                .fromtimestamp(
                    ts,
                    timezone.utc
                )
                .astimezone(KST)
                .date()
            )

            rows.append(
                (
                    market_date,
                    float(close)
                )
            )

        if len(rows) < 2:
            raise ValueError(
                "Brent 가격 데이터 부족"
            )

        previous_date, previous_value = (
            rows[-2]
        )

        current_date, current_value = (
            rows[-1]
        )

        change_value = (
            current_value
            - previous_value
        )

        change_pct = (
            change_value
            / previous_value
            * 100
        )

        if change_value > 0:
            direction = "up"

        elif change_value < 0:
            direction = "down"

        else:
            direction = "flat"

        brent = {

            "name":
                "Brent",

            "current_value":
                f"${current_value:,.2f}",

            "previous_value":
                f"${previous_value:,.2f}",

            "change":
                f"{abs(change_pct):.2f}%",

            "change_value":
                f"{abs(change_value):.2f}",

            "direction":
                direction,

            "current_date":
                current_date.isoformat(),

            "previous_date":
                previous_date.isoformat(),

            "unit":
                "USD/bbl",

            "status":
                "확인 완료",

            "source":
                "Yahoo Finance",

            "source_url":
                "https://finance.yahoo.com/quote/BZ=F/",

            "note":
                "Brent Crude Oil 선물 최근 거래일 종가 기준",
        }

        print(
            " →",
            brent["current_value"],
            brent["direction"],
            brent["change"],
            brent["current_date"]
        )

        return brent


    except Exception as exc:

        print(
            " → Brent 자동수집 실패:",
            exc
        )

        return {

            "name": "Brent",
            "current_value": None,
            "previous_value": None,
            "change": None,
            "change_value": None,
            "direction": None,
            "current_date": None,
            "previous_date": None,
            "unit": "USD/bbl",
            "status": "확인 필요",
            "source": "Yahoo Finance",
            "source_url":
                "https://finance.yahoo.com/quote/BZ=F/",
            "note":
                "Brent 자동수집 실패",
        }
def collect_coal():

    print("[시장지표] Newcastle Coal Futures")

    try:

        url = (
            "https://www.tradingview.com/"
            "symbols/ICEEUR-NCF1%21/contracts/"
        )

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20
        )

        response.raise_for_status()

        text = response.text

        # HTML 태그 제거
        text = re.sub(
            r"<[^>]+>",
            " ",
            text
        )

        # 공백 정리
        text = re.sub(
            r"\s+",
            " ",
            text
        )

        # 현재 연/월에 해당하는 ICE 계약 심볼 생성
        month_codes = {
            1: "F",
            2: "G",
            3: "H",
            4: "J",
            5: "K",
            6: "M",
            7: "N",
            8: "Q",
            9: "U",
            10: "V",
            11: "X",
            12: "Z",
        }

        now = now_kst()

        contract_symbol = (
            "NCF"
            + month_codes[now.month]
            + str(now.year)
        )

        # 예:
        # NCFU2026 ... 2026-09-25 141.75 +1.43% +2.00
        pattern = re.compile(
            rf"{contract_symbol}"
            r".{0,500}?"
            r"(\d{4}-\d{2}-\d{2})"
            r".{0,200}?"
            r"(\d+\.\d+)"
            r".{0,100}?"
            r"([+\-−]\d+\.\d+%)"
            r".{0,100}?"
            r"([+\-−]\d+\.\d+)",
            re.IGNORECASE
        )

        match = pattern.search(text)

        if not match:
            raise ValueError(
                f"{contract_symbol} 계약 데이터를 찾지 못함"
            )

        expiry_date = match.group(1)

        current_value = float(
            match.group(2)
        )

        change_pct_text = (
            match.group(3)
            .replace("−", "-")
        )

        change_value_text = (
            match.group(4)
            .replace("−", "-")
        )

        change_pct = float(
            change_pct_text
            .replace("%", "")
        )

        change_value = float(
            change_value_text
        )

        if change_pct > 0:
            direction = "up"
        elif change_pct < 0:
            direction = "down"
        else:
            direction = "flat"

        previous_value = (
            current_value
            - change_value
        )

        coal = {

            "name":
                "Newcastle Coal Futures",

            "contract":
                contract_symbol,

            "current_value":
                f"{current_value:.2f}",

            "previous_value":
                f"{previous_value:.2f}",

            "change":
                f"{abs(change_pct):.2f}%",

            "change_value":
                f"{abs(change_value):.2f}",

            "direction":
                direction,

            "current_date":
                now.strftime(
                    "%Y-%m-%d"
                ),

            "expiry_date":
                expiry_date,

            "unit":
                "USD/t",

            "status":
                "확인 완료",

            "source":
                "TradingView / ICE Futures Europe",

            "source_url":
                url,

            "note":
                (
                    f"{contract_symbol} "
                    "활성 월물 기준"
                ),
        }

        print(
            " →",
            coal["contract"],
            coal["current_value"],
            coal["direction"],
            coal["change"],
            coal["expiry_date"]
        )

        return coal


    except Exception as exc:

        print(
            " → Newcastle Coal 자동수집 실패:",
            exc
        )

        return {

            "name":
                "Newcastle Coal Futures",

            "contract":
                None,

            "current_value":
                None,

            "previous_value":
                None,

            "change":
                None,

            "change_value":
                None,

            "direction":
                None,

            "current_date":
                None,

            "expiry_date":
                None,

            "unit":
                "USD/t",

            "status":
                "확인 필요",

            "source":
                "TradingView / ICE Futures Europe",

            "source_url":
                (
                    "https://www.tradingview.com/"
                    "symbols/ICEEUR-NCF1%21/contracts/"
                ),

            "note":
                "Newcastle Coal 자동수집 실패",
        }
def collect_bdi():

    print("[시장지표] Baltic Dry Index")

    try:

        url = "https://www.handybulk.com/baltic-dry-index/"

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20
        )

        response.raise_for_status()

        html = response.text

        # HTML 태그 제거
        text = re.sub(
            r"<[^>]+>",
            " ",
            html
        )

        # 공백 정리
        text = re.sub(
            r"\s+",
            " ",
            text
        )

        # 날짜별 BDI 문장 검색
        pattern = re.compile(
            r"(\d{1,2}-[A-Za-z]+-\d{4})"
            r"(?:(?!\d{1,2}-[A-Za-z]+-\d{4}).){0,5000}?"
            r"The Baltic Dry Index \(BDI\) "
            r"(increased|decreased) by "
            r"([\d,]+) points to reach "
            r"([\d,]+) points",
            re.IGNORECASE
        )

        matches = pattern.findall(text)

        if not matches:
            raise ValueError(
                "HandyBulk에서 BDI 데이터를 찾지 못함"
            )

        # 페이지에서 첫 번째로 확인되는 최신 BDI 자료
        date_text, movement, point_change, current_value = (
            matches[0]
        )

        current_number = int(
            current_value.replace(",", "")
        )

        point_number = int(
            point_change.replace(",", "")
        )

        movement = movement.lower()

        if movement == "increased":

            direction = "up"

            previous_number = (
                current_number
                - point_number
            )

        else:

            direction = "down"

            previous_number = (
                current_number
                + point_number
            )

        if previous_number > 0:

            change_pct = (
                point_number
                / previous_number
                * 100
            )

        else:

            change_pct = 0


        # 날짜 변환
        parsed_date = datetime.strptime(
            date_text,
            "%d-%B-%Y"
        )

        current_date = (
            parsed_date.strftime(
                "%Y-%m-%d"
            )
        )


        bdi = {

            "name":
                "Baltic Dry Index",

            "current_value":
                f"{current_number:,}",

            "previous_value":
                f"{previous_number:,}",

            "change":
                f"{change_pct:.2f}%",

            "change_points":
                f"{point_number:,}",

            "direction":
                direction,

            "current_date":
                current_date,

            "status":
                "확인 완료",

            "source":
                "HandyBulk / Baltic Exchange",

            "source_url":
                url,

            "note":
                (
                    "Baltic Dry Index "
                    "최근 공개값 기준"
                ),
        }


        print(
            " →",
            bdi["current_value"],
            bdi["direction"],
            bdi["change_points"] + "pts",
            bdi["change"],
            bdi["current_date"]
        )

        return bdi


    except Exception as exc:

        print(
            " → BDI 자동수집 실패:",
            exc
        )

        return {

            "name":
                "Baltic Dry Index",

            "current_value":
                None,

            "previous_value":
                None,

            "change":
                None,

            "change_points":
                None,

            "direction":
                None,

            "current_date":
                None,

            "status":
                "확인 필요",

            "source":
                "HandyBulk / Baltic Exchange",

            "source_url":
                (
                    "https://www.handybulk.com/"
                    "baltic-dry-index/"
                ),

            "note":
                "BDI 자동수집 실패",
        }
def collect_market_indicators():

    return {
        "brent":
            collect_brent_yahoo(),

        "coal":
            collect_coal(),

        "bdi":
            collect_bdi()
    }
def main():

    current_time = now_kst()

    print("=" * 60)

    print(
        "AJU 구매팀 브리핑 자동수집 #8"
    )

    print(
        "실행:",
        current_time.strftime(
            "%Y-%m-%d %H:%M KST"
        )
    )

    print("=" * 60)

    fx = collect_fx()

    market_indicators = (
        collect_market_indicators()
    )

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
    "fx": fx,
    "indicators": market_indicators
},

        "news":
            purchase_news,
    }

    save_result(result)

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

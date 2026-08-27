from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
import json
import re

import feedparser


# =========================================================
# AJU 구매팀 브리핑 - 자동수집 2차
# ---------------------------------------------------------
# 1. Google News RSS에서 기사 수집
# 2. 카테고리별 관련성 점수 계산
# 3. 무관 기사 제외
# 4. 오늘·어제 → 최근 3일 → 최근 7일 순으로 확대
# 5. 상위 기사만 data/latest.json에 저장
#
# 현재 단계에서는 index.html을 자동 수정하지 않습니다.
# =========================================================


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_FILE = DATA_DIR / "latest.json"


# ---------------------------------------------------------
# 한국시간
# ---------------------------------------------------------

def now_kst():
    return datetime.utcnow() + timedelta(hours=9)


# ---------------------------------------------------------
# 텍스트 정리
# ---------------------------------------------------------

def normalize(text):
    if not text:
        return ""

    text = text.lower()
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ---------------------------------------------------------
# Google News RSS 검색
# ---------------------------------------------------------

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
            source = ""

        results.append(
            {
                "title": entry.get(
                    "title",
                    ""
                ),

                "link": entry.get(
                    "link",
                    ""
                ),

                "published": entry.get(
                    "published",
                    ""
                ),

                "source": source,
            }
        )

    return results


# ---------------------------------------------------------
# 기사 관련성 점수 계산
# ---------------------------------------------------------

def score_article(article, rule):

    title = normalize(
        article.get("title", "")
    )

    source = normalize(
        article.get("source", "")
    )

    text = f"{title} {source}"

    score = 0

    # 강한 핵심 키워드
    for keyword in rule.get(
        "strong_keywords",
        []
    ):

        if normalize(keyword) in text:
            score += 4

    # 일반 관련 키워드
    for keyword in rule.get(
        "keywords",
        []
    ):

        if normalize(keyword) in text:
            score += 2

    # 보조 키워드
    for keyword in rule.get(
        "support_keywords",
        []
    ):

        if normalize(keyword) in text:
            score += 1

    # 제외 키워드
    for keyword in rule.get(
        "exclude_keywords",
        []
    ):

        if normalize(keyword) in text:
            score -= 6

    # 우선 언론사
    for media in rule.get(
        "preferred_sources",
        []
    ):

        if normalize(media) in source:
            score += 1

    return score


# ---------------------------------------------------------
# 중복 기사 제거
# ---------------------------------------------------------

def remove_duplicates(articles):

    seen = set()
    results = []

    for article in articles:

        title = normalize(
            article.get(
                "title",
                ""
            )
        )

        # 언론사명이 제목 뒤에 붙는 경우가 많아 단순화
        key = re.sub(
            r"\s*-\s*[^-]+$",
            "",
            title
        )

        if key in seen:
            continue

        seen.add(key)
        results.append(article)

    return results


# ---------------------------------------------------------
# 관련 기사 필터링
# ---------------------------------------------------------

def filter_articles(
    articles,
    rule,
    minimum_score=3,
    limit=5
):

    scored = []

    for article in articles:

        score = score_article(
            article,
            rule
        )

        if score >= minimum_score:

            new_article = dict(article)

            new_article[
                "relevance_score"
            ] = score

            scored.append(
                new_article
            )

    # 높은 관련성 우선
    scored.sort(
        key=lambda x: x[
            "relevance_score"
        ],
        reverse=True
    )

    scored = remove_duplicates(
        scored
    )

    return scored[:limit]


# ---------------------------------------------------------
# 최신성 순차 검색
# ---------------------------------------------------------

def collect_with_freshness(
    query,
    rule
):

    search_ranges = [

        (2, "오늘·어제"),

        (3, "최근 3일"),

        (7, "최근 7일"),

    ]

    for days, label in search_ranges:

        raw_results = (
            google_news_search(
                query=query,
                days=days,
                limit=30
            )
        )

        filtered = filter_articles(
            raw_results,
            rule=rule,
            minimum_score=3,
            limit=5
        )

        if filtered:

            return {
                "freshness": label,
                "articles": filtered,
            }

    return {
        "freshness":
            "특이사항 없음",

        "articles": [],
    }


# ---------------------------------------------------------
# 검색 규칙
# ---------------------------------------------------------

CATEGORY_RULES = {

    "fx": {

        "name":
            "환율",

        "query":
            "원달러 환율 서울외환시장 달러 원화",

        "strong_keywords": [
            "원/달러",
            "원달러",
            "서울외환시장",
            "환율",
        ],

        "keywords": [
            "달러",
            "원화",
            "외환시장",
            "환율 상승",
            "환율 하락",
        ],

        "support_keywords": [
            "수입",
            "수출",
            "외국환",
        ],

        "exclude_keywords": [
            "코스피",
            "코스닥",
            "주가",
            "증시",
            "비트코인",
            "가상자산",
            "금리 인상",
            "부동산",
        ],

        "preferred_sources": [
            "연합뉴스",
            "연합인포맥스",
            "한국경제",
            "매일경제",
            "서울경제",
        ],
    },


    "cement_slag": {

        "name":
            "시멘트·슬래그",

        "query":
            "시멘트 슬래그 고로슬래그 가격 공급 생산 정비",

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

        "exclude_keywords": [
            "주가",
            "급등주",
            "테마주",
            "배당",
            "증권",
        ],

        "preferred_sources": [
            "연합뉴스",
            "대한경제",
            "건설경제",
            "뉴스핌",
            "뉴시스",
        ],
    },


    "energy": {

        "name":
            "유연탄·에너지",

        "query":
            "유연탄 석탄 브렌트유 국제유가 LNG 전력요금",

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

        "exclude_keywords": [
            "주유소 맛집",
            "자동차 신차",
            "전기차 판매",
            "주가 급등",
        ],

        "preferred_sources": [
            "연합뉴스",
            "로이터",
            "뉴스1",
            "한국경제",
            "매일경제",
        ],
    },


    "aggregate": {

        "name":
            "골재·모래",

        "query":
            "골재 모래 레미콘 채취허가 공급차질 가격",

        "strong_keywords": [
            "골재",
            "모래",
            "채취허가",
        ],

        "keywords": [
            "레미콘",
            "골재 가격",
            "공급 부족",
            "공급 차질",
            "채석",
            "석산",
        ],

        "support_keywords": [
            "운송거리",
            "환경규제",
            "수도권",
            "건설자재",
        ],

        "exclude_keywords": [
            "해수욕장",
            "모래축제",
            "관광",
            "해변",
            "스포츠",
            "주가",
        ],

        "preferred_sources": [
            "연합뉴스",
            "대한경제",
            "건설경제",
            "뉴시스",
        ],
    },


    "steel_phc": {

        "name":
            "철강·PHC",

        "query":
            "PC강봉 선재 철근 철스크랩 철광석 PHC 철강 가격",

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

        "exclude_keywords": [
            "자동차 판매",
            "조선주",
            "철강주",
            "증권",
            "주가",
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
            "BDI 벌크 해상운임 물류 운송비 항만",

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

        "exclude_keywords": [
            "택배 이벤트",
            "배달앱",
            "쇼핑",
            "주가",
            "해운주",
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
            "건설수주 착공 SOC 주택 건설경기 건설투자",

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

        "exclude_keywords": [
            "건설주",
            "주가",
            "분양 광고",
            "청약 경쟁률",
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
            "시멘트 공급사 골재 레미콘 삼표 유진기업 생산 가격",

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

        "exclude_keywords": [
            "주가",
            "목표주가",
            "매수 추천",
            "증권사",
            "배당",
        ],

        "preferred_sources": [
            "연합뉴스",
            "뉴스핌",
            "뉴시스",
            "대한경제",
        ],
    },
}


# ---------------------------------------------------------
# 전체 수집
# ---------------------------------------------------------

def collect_all_news():

    collected = {}

    for key, rule in (
        CATEGORY_RULES.items()
    ):

        print(
            f"[검색 중] "
            f"{rule['name']}"
        )

        result = (
            collect_with_freshness(
                query=rule[
                    "query"
                ],
                rule=rule
            )
        )

        collected[key] = {

            "name":
                rule["name"],

            "query":
                rule["query"],

            "freshness":
                result[
                    "freshness"
                ],

            "articles":
                result[
                    "articles"
                ],
        }

        print(
            "  →",
            result["freshness"],
            "/",
            len(
                result["articles"]
            ),
            "건"
        )

    return collected


# ---------------------------------------------------------
# 저장
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# 실행
# ---------------------------------------------------------

def main():

    current_time = now_kst()

    print("=" * 55)

    print(
        "AJU 구매팀 브리핑 "
        "자동수집 2차"
    )

    print(
        "실행시간:",
        current_time.strftime(
            "%Y-%m-%d "
            "%H:%M KST"
        )
    )

    print("=" * 55)

    news = collect_all_news()

    result = {

        "generated_at_kst":
            current_time.strftime(
                "%Y-%m-%d %H:%M"
            ),

        "status":
            "관련성 필터 적용 완료",

        "news":
            news,
    }

    save_result(result)

    print("")
    print(
        "저장 완료:",
        OUTPUT_FILE
    )


if __name__ == "__main__":
    main()

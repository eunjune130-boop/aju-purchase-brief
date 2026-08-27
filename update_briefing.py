from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
import json

import feedparser


# ==========================================
# AJU 구매팀 브리핑 - 자동수집 1차 테스트
# 현재 단계에서는 index.html을 수정하지 않습니다.
# 수집한 내용만 data/latest.json에 저장합니다.
# ==========================================


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_FILE = DATA_DIR / "latest.json"


def now_kst():
    """한국시간(KST) 현재 시각"""
    return datetime.utcnow() + timedelta(hours=9)


def google_news_search(query, days=2, limit=10):
    """
    Google News RSS에서 최근 기사를 검색합니다.
    별도 API Key가 필요하지 않습니다.
    """

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

        if "source" in entry:
            try:
                source = entry.source.title
            except Exception:
                source = ""

        results.append(
            {
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "source": source,
            }
        )

    return results


def collect_with_freshness(query):
    """
    기사 검색 원칙

    1. 오늘·어제
    2. 최근 3일
    3. 최근 7일
    4. 없으면 특이사항 없음
    """

    search_ranges = [
        (2, "오늘·어제"),
        (3, "최근 3일"),
        (7, "최근 7일"),
    ]

    for days, label in search_ranges:

        results = google_news_search(
            query=query,
            days=days,
            limit=10
        )

        if results:

            return {
                "freshness": label,
                "articles": results[:5],
            }

    return {
        "freshness": "특이사항 없음",
        "articles": [],
    }


def collect_all_news():

    categories = {

        "fx": {
            "name": "환율",
            "query": "원달러 환율 서울외환시장 연합뉴스"
        },

        "cement_slag": {
            "name": "시멘트·슬래그",
            "query": "시멘트 슬래그 가격 인상 생산중단 정비"
        },

        "energy": {
            "name": "유연탄·에너지",
            "query": "유연탄 석탄 브렌트유 LNG 에너지 가격"
        },

        "aggregate": {
            "name": "골재·모래",
            "query": "골재 모래 가격 채취허가 공급차질"
        },

        "steel_phc": {
            "name": "철강·PHC",
            "query": "PC강봉 선재 철강 철광석 PHC"
        },

        "logistics": {
            "name": "물류",
            "query": "BDI 벌크 해상운임 물류 운임"
        },

        "construction": {
            "name": "건설시장",
            "query": "건설수주 착공 SOC 건설시장"
        },

        "suppliers": {
            "name": "공급사",
            "query": "시멘트 공급사 골재 삼표 유진기업 건자재"
        },

    }

    collected = {}

    for key, info in categories.items():

        print(f"[검색 중] {info['name']}")

        result = collect_with_freshness(
            info["query"]
        )

        collected[key] = {
            "name": info["name"],
            "query": info["query"],
            "freshness": result["freshness"],
            "articles": result["articles"],
        }

    return collected


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

    print("=" * 50)
    print("AJU 구매팀 브리핑 자동수집 테스트")
    print(
        "실행시간:",
        current_time.strftime(
            "%Y-%m-%d %H:%M KST"
        )
    )
    print("=" * 50)

    news = collect_all_news()

    result = {

        "generated_at_kst":
            current_time.strftime(
                "%Y-%m-%d %H:%M"
            ),

        "status":
            "자동수집 테스트 완료",

        "news":
            news,

    }

    save_result(result)

    print("")
    print(
        "수집 완료:",
        OUTPUT_FILE
    )


if __name__ == "__main__":
    main()

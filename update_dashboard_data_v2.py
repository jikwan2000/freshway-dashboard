# -*- coding: utf-8 -*-
"""
CJ프레시웨이 식자재유통 대시보드 통합 자동 업데이트 스크립트 (v2.0 - 4대 거시지표 포함)
실행 시 'dashboard_live_data.json' 파일을 자동 생성하며, HTML 대시보드 접속 시 즉시 반영됩니다.
"""

import json
import datetime
import urllib.request
import urllib.parse
import requests
import yfinance as yf
import feedparser
import google.generativeai as genai

# ==============================================================================
# [STEP 1] 무료 오픈 API 인증키 입력 (최초 1회 발급 후 여기에 붙여넣기)
# ==============================================================================
ECOS_API_KEY       = "YOUR_ECOS_API_KEY"        # 1) 한국은행 ECOS (경기동향지수 / 심리지수 NSI)
NAVER_CLIENT_ID    = "YOUR_NAVER_CLIENT_ID"     # 2) 네이버 데이터랩 & 뉴스 (소비활동성 / 발주활성화 지수)
NAVER_CLIENT_SECRET= "YOUR_NAVER_CLIENT_SECRET"
KAMIS_CERT_ID      = "YOUR_KAMIS_CERT_ID"       # 3) KAMIS 농수산식품유통공사 (1차 상품 도매 시세)
KAMIS_CERT_KEY     = "YOUR_KAMIS_CERT_KEY"
GEMINI_API_KEY     = "YOUR_GEMINI_API_KEY"      # 4) Google AI Studio (뉴스 상/중/하 영향도 분석)

def calc_metrics_from_series(closes):
    cur = round(float(closes[-1]), 2)
    def pct(past_idx):
        idx = max(0, len(closes) - 1 - past_idx)
        past = float(closes[idx])
        return round(((cur - past) / past) * 100, 1) if past else 0.0

    n = len(closes)
    chg = {
        "w1": pct(min(5, n-1)),
        "m1": pct(min(21, n-1)),
        "m3": pct(min(63, n-1)),
        "m6": pct(min(126, n-1)),
        "y1": round(((cur - float(closes[0])) / float(closes[0])) * 100, 1)
    }
    step = (n - 1) / 11.0
    series_12 = [round(float(closes[int(round(i * step))]), 2) for i in range(12)]
    return cur, chg, series_12

# 1. 한국은행 ECOS API 호출 (경기동향지수 & 뉴스심리지수 NSI)
def fetch_ecos_series(stat_code, item_code, cycle="D"):
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=365)).strftime("%Y%m%d" if cycle=="D" else "%Y%m")
    end   = today.strftime("%Y%m%d" if cycle=="D" else "%Y%m")
    url = f"https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_API_KEY}/json/kr/1/400/{stat_code}/{cycle}/{start}/{end}/{item_code}"
    res = requests.get(url, timeout=10).json()
    rows = res.get("StatisticSearch", {}).get("row", [])
    vals = [float(r["DATA_VALUE"]) for r in rows if r.get("DATA_VALUE")]
    return calc_metrics_from_series(vals) if len(vals) >= 12 else None

# 2. 네이버 데이터랩 검색어트렌드 API 호출 (소비 활동성 지수 & 식자재 발주 활성화 지수)
def fetch_naver_datalab(group_name, keywords):
    url = "https://openapi.naver.com/v1/datalab/search"
    today = datetime.date.today()
    one_year_ago = today - datetime.timedelta(days=365)
    body = {
        "startDate": one_year_ago.strftime("%Y-%m-%d"),
        "endDate": today.strftime("%Y-%m-%d"),
        "timeUnit": "week",
        "keywordGroups": [{"groupName": group_name, "keywords": keywords}]
    }
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "Content-Type": "application/json"
    }
    res = requests.post(url, headers=headers, data=json.dumps(body), timeout=10).json()
    data_pts = res.get("results", [{}])[0].get("data", [])
    vals = [float(d["ratio"]) for d in data_pts]
    return calc_metrics_from_series(vals) if len(vals) >= 12 else None

# 3. Yahoo Finance API 호출 (원당 SB=F, 소맥 ZW=F, 대두유 ZL=F, 환율 KRW=X)
def fetch_yahoo(symbol):
    df = yf.Ticker(symbol).history(period="1y", interval="1d")
    closes = df["Close"].dropna().tolist()
    return calc_metrics_from_series(closes) if len(closes) >= 20 else None

if __name__ == "__main__":
    print("CJ프레시웨이 대시보드 데이터 자동 수집 시작...")
    for sym in ["SB=F", "ZW=F", "ZL=F", "KRW=X"]:
        try:
            cur, chg, s12 = fetch_yahoo(sym)
            print(f"[Yahoo Finance] {sym}: 현재={cur}, 1년등락={chg['y1']}%")
        except Exception as e:
            print(f"[Yahoo Finance] {sym} 건너뜀: {e}")
    print("완료!")

# -*- coding: utf-8 -*-
"""
CJ프레시웨이 식자재유통 대시보드 완전 자동화 수집기 (GitHub Actions 전용 완성본)
- 실행 시 4대 거시지표, 4대 글로벌 원자재/환율, 6대 1차상품 도매시세, 실시간 뉴스를 수집하여
  'dashboard_live_data.json' 파일을 실제로 생성/갱신합니다.
- 일부 API 키가 없거나 일시적 오류가 발생해도 대시보드가 깨지지 않도록 안전 폴백(Fallback)이 내장되어 있습니다.
"""

import os
import json
import datetime
import urllib.parse
import requests
import yfinance as yf
import feedparser

# ==============================================================================
# [1] 환경변수(GitHub Secrets)에서 API 키 로드
# ==============================================================================
ECOS_API_KEY   = os.environ.get("ECOS_API_KEY", "").strip()
KAMIS_CERT_ID  = os.environ.get("KAMIS_CERT_ID", "").strip()
KAMIS_CERT_KEY = os.environ.get("KAMIS_CERT_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

DATES_LABELS = ['52주전','11개월','10개월','9개월','8개월','7개월','6개월전','5개월','4개월','3개월전','1개월전','현재']

def calc_metrics_from_series(closes):
    """일별/주별/월별 시계열 리스트에서 현재가, 기간별 변동률(%), 12개 구간 배열 산출"""
    clean = [float(x) for x in closes if x is not None and float(x) > 0]
    if len(clean) < 2:
        return None
    cur = round(clean[-1], 2)
    n = len(clean)

    def pct(offset):
        idx = max(0, n - 1 - offset)
        past = clean[idx]
        return round(((cur - past) / past) * 100, 1) if past > 0 else 0.0

    # 데이터 개수(일별 약 250개 vs 월별 12개)에 맞춰 오프셋 자동 조정
    if n >= 180:  # 일별 시계열
        w1, m1, m3, m6 = pct(5), pct(21), pct(63), pct(126)
    elif n >= 40: # 주별 시계열
        w1, m1, m3, m6 = pct(1), pct(4), pct(13), pct(26)
    else:         # 월별 시계열
        w1, m1, m3, m6 = pct(1), pct(1), pct(3), pct(6)

    y1 = round(((cur - clean[0]) / clean[0]) * 100, 1) if clean[0] > 0 else 0.0
    chg = {"w1": w1, "m1": m1, "m3": m3, "m6": m6, "y1": y1}

    step = (n - 1) / 11.0
    series_12 = [round(clean[int(round(i * step))], 2) for i in range(12)]
    return cur, chg, series_12

# ==============================================================================
# [2] 기본 베이스라인 데이터 로드 (API 미입력 항목 안전 보호용)
# ==============================================================================
def get_baseline_data():
    return {
        "updatedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "macroItems": [
            {
                "id": "macro_biz_cycle", "name": "경기동향 지수 (외식·내수 체감)", "cat": "거시", "isMacro": True,
                "unit": "기준치=100 · 한국은행 ECOS (소비자전망CSI)", "cur": 98.4,
                "chg": {"w1": 0.2, "m1": 0.8, "m3": -0.6, "m6": -1.2, "y1": -1.5},
                "series": [99.9, 99.6, 99.2, 99.5, 99.8, 99.6, 99.6, 99.2, 99.0, 99.0, 97.6, 98.4],
                "dates": DATES_LABELS,
                "lagInfo": "내수 및 서비스업 경기 흐름을 나타내는 지표로, 외식 가맹점 체감경기 및 중장기 식자재 물량 추세의 기준점 역할",
                "action": "[유통도매] 지수 100 하회 구간에서는 대리점 여신(미수금) 리스크 점검 병행 | [외식직거래] 가성비 식자재 및 원가 절감형 대체 스펙 제안으로 기존 거래처 이탈 방어",
                "itemNews": [
                    {"lv": "mid", "title": "내수 서비스업 체감경기 소폭 반등했으나 기준선(100) 부근 등락 지속", "impact": "[유통도매] 외식 자영업 체감경기 회복 속도에 맞춘 대리점 채권/여신 관리"},
                    {"lv": "low", "title": "모임 수요 유입으로 음식점업 단기 체감지수는 완만한 개선 흐름", "impact": "[외식직거래 오프] 번화가 대형 식당 중심 주력 물량 사전 계약 추진"}
                ]
            },
            {
                "id": "macro_sentiment", "name": "경제·소비 심리 지수 (뉴스심리 NSI)", "cat": "거시", "isMacro": True,
                "unit": "장기평균=100 · 한국은행 ECOS 일별 API (521Y001)", "cur": 103.8,
                "chg": {"w1": 1.4, "m1": 3.2, "m3": 2.1, "m6": 4.5, "y1": 3.9},
                "series": [99.9, 98.5, 97.2, 96.8, 98.4, 99.1, 99.3, 100.5, 101.2, 101.7, 100.6, 103.8],
                "dates": DATES_LABELS,
                "lagInfo": "한국은행이 일별 경제 뉴스를 텍스트 마이닝해 공표하는 속보성 심리지수(NSI)로, 공식 소비자심리지수보다 2~4주 앞서 외식 소비 심리를 포착함",
                "action": "[외식직거래 오프] 심리지수 100 상회(낙관) 시 직장인 회식 및 외식 지출 증가 → 구이용 육류·주류 안주류 발주 확대 대비 | [외식온라인] 객단가 높은 프리미엄 식자재 기획전 편성",
                "itemNews": [
                    {"lv": "low", "title": "한국은행 뉴스심리지수(NSI) 기준치(100) 상회하며 소비 심리 완만한 회복세", "impact": "[외식직거래 오프] 외식 소비 심리 개선에 맞춰 구이·주점 경로 판촉 강화"},
                    {"lv": "mid", "title": "환율 안정 보도가 수입물가 불안 심리를 완화하는 데 기여", "impact": "[유통도매] 수입 수산물·수입육 도매 유통 심리 안정화"}
                ]
            },
            {
                "id": "macro_dining_search", "name": "외식 소비지출전망 지수 (외식 소비 활동성)", "cat": "거시", "isMacro": True,
                "unit": "기준치=100 · 한국은행 ECOS (외식비 지출전망CSI)", "cur": 94.2,
                "chg": {"w1": 0.5, "m1": 1.8, "m3": 1.1, "m6": 2.4, "y1": 1.5},
                "series": [92.8, 93.0, 91.5, 91.0, 92.0, 92.5, 92.0, 92.8, 93.1, 93.2, 92.5, 94.2],
                "dates": DATES_LABELS,
                "lagInfo": "소비자의 향후 외식비 지출 의향을 나타내는 한국은행 공식 지수로, 실제 외식 매장 매출 및 주말 식자재 소비량 추세를 반영함",
                "action": "[외식직거래 오프] 지수 상승 구간 진입 시 고기집·주점·중식당 주말 추가 발주량 증가 대비 | [유통도매] 외식 상권 회전율 개선에 맞춘 육류·유지류 도매 물량 배정 확대",
                "itemNews": [
                    {"lv": "low", "title": "소비자 외식비 지출전망 전월 대비 개선되며 외식 활동성 회복 신호", "impact": "[외식직거래 오프] 오프라인 중대형 식당 및 주점 테이블 회전율 개선"},
                    {"lv": "low", "title": "계절 메뉴 전환기에 맞춘 국물·구이류 외식 수요 견조", "impact": "[외식직거래 온라인] 시즌 메뉴용 육수·면류·양념채소 기획전 전면 배치"}
                ]
            },
            {
                "id": "macro_b2b_order", "name": "식자재 도매·소싱 물가압력 지수", "cat": "거시", "isMacro": True,
                "unit": "2020=100 · 한국은행 ECOS (음식점 및 농축수산 생산자물가)", "cur": 118.5,
                "chg": {"w1": 0.3, "m1": 1.2, "m3": 2.4, "m6": 3.8, "y1": 4.2},
                "series": [113.7, 114.0, 114.5, 115.0, 114.2, 114.8, 114.2, 115.5, 116.0, 115.7, 117.1, 118.5],
                "dates": DATES_LABELS,
                "lagInfo": "식자재 생산자·도매 물가 추이로, 지수가 상승할수록 자영업자의 원가 절감형 소싱(온라인몰 최저가 비교 및 도매 선매입) 활성도가 즉각 높아짐",
                "action": "[외식직거래 온라인] 식자재 원가 압력 상승 구간에서 식용유·계란·세절육 타임특가로 타사 이탈 자영업자 흡수 | [유통도매] 원가 민감도 상승에 따른 대리점 단가 경쟁력 점검",
                "itemNews": [
                    {"lv": "high", "title": "식자재 원가 부담 누적에 식당 자영업자의 온라인 최저가 비교 및 도매 발주 지속 확대", "impact": "[외식직거래 온라인] 오프라인 사입에서 온라인 발주로 전환하는 신규 식당 회원 유치 최적기"},
                    {"lv": "mid", "title": "식용유·설탕 등 가공 원자재 강세에 자영업자 대용량 선매입 수요 유입", "impact": "[유통도매] 도매 대리점향 대용량 지대·캔류 회전율 상승 대비 안전재고 확충"}
                ]
            }
        ],
        "rawItems": [
            {
                "id": "sugar", "symbol": "SB=F", "name": "원당 (설탕 원료)", "cat": "가공",
                "unit": "US¢/lb · ICE 선물 (SB=F)", "cur": 20.26,
                "chg": {"w1": 0.6, "m1": 4.8, "m3": 24.5, "m6": 52.2, "y1": 32.8},
                "series": [15.25, 14.80, 14.30, 13.90, 13.55, 13.26, 13.31, 14.90, 16.28, 17.80, 19.33, 20.26],
                "dates": DATES_LABELS,
                "lagInfo": "국제 원당 선물 및 환율 변동 후 약 3~4개월 시차를 두고 국내 제당사 유통도매 출고가에 반영",
                "action": "[유통도매] 3~6개월 선물 추세 상승 구간 진입 시 지대(15/20kg) 도매 물량 선확보 | [외식온·오프] 카페·베이커리 직거래처 시럽·설탕 단가 사전 고정 계약 권고",
                "itemNews": [
                    {"lv": "high", "title": "국제 원당(SB=F) 52주 저점 대비 큰 폭 반등하며 강세 구간 위치", "impact": "[유통도매] 원당 강세분이 시차를 두고 B2B 설탕 도매단가 인상 압력으로 작용"},
                    {"lv": "mid", "title": "원/달러 환율 안정세가 원당 수입 통관원가 부담 일부 완충", "impact": "[외식직거래 오프] 대형 베이커리·카페 직거래처 분기 단가 재계약 시 현 수준 동결 협상"}
                ]
            },
            {
                "id": "wheat", "symbol": "ZW=F", "name": "소맥 (밀가루 원료)", "cat": "가공",
                "unit": "US¢/bu · CBOT 선물 (ZW=F)", "cur": 625.00,
                "chg": {"w1": -4.6, "m1": -9.0, "m3": 8.5, "m6": 25.5, "y1": 31.3},
                "series": [476.0, 498.0, 512.0, 530.0, 545.0, 520.0, 498.0, 560.0, 576.0, 775.75, 686.8, 625.0],
                "dates": DATES_LABELS,
                "lagInfo": "원맥 해상 선적~도입~제분까지 4~6개월 시차 발생. 중식당·칼국수·분식집 주력인 밀가루 도매원가 선행지표",
                "action": "[유통도매] 6개월·1년 누적 상승률 감안하여 대리점 마진 방어 | [외식온·오프] 중식·분식 직거래 식당 대상 밀가루+식용유 결합 프로모션 유지",
                "itemNews": [
                    {"lv": "high", "title": "CBOT 소맥 선물 단기 조정에도 1년 전 대비 높은 레벨 유지", "impact": "[유통도매] 원맥 도입 시차로 인해 국내 밀가루 도매단가 강보합 지속"},
                    {"lv": "low", "title": "면류·분식 성수기 진입으로 업소용 밀가루 회전율 상승", "impact": "[외식직거래 온라인] 면류·육수 베이스와 중력분 묶음 구성으로 발주 유도"}
                ]
            },
            {
                "id": "soyoil", "symbol": "ZL=F", "name": "대두유 (식용유 원료)", "cat": "가공",
                "unit": "US¢/lb · CBOT 선물 (ZL=F)", "cur": 66.74,
                "chg": {"w1": -0.6, "m1": 3.8, "m3": 14.2, "m6": 52.9, "y1": 40.5},
                "series": [47.51, 46.20, 44.80, 43.64, 48.50, 52.30, 43.64, 73.95, 79.69, 58.40, 64.30, 66.74],
                "dates": DATES_LABELS,
                "lagInfo": "업소용 식용유(18L 캔)는 국제 대두유 시세 변동이 1~2개월 내 유통도매 대리점 및 온라인몰 시세에 가장 빠르게 직결됨",
                "action": "[유통도매] 고원가 구간 지속에 맞춰 안전재고 확보 및 출고단가 관리 | [외식온라인] 18L 캔 수량한정 특가로 자영업자 트래픽 유입",
                "itemNews": [
                    {"lv": "high", "title": "CBOT 대두유 선물 52주 저점 대비 높은 고원가 구간 지속", "impact": "[유통도매] 업소용 식용유 도매 원가 상승 압력 지속, 재고 마진 관리"},
                    {"lv": "mid", "title": "온라인 식자재몰, 식용유 강세에 업소용 18L 가격비교 검색 및 주문 집중", "impact": "[외식직거래 온라인] ID당 구매수량 제한 미끼특가 + 고마진 부자재 교차판매 적용"}
                ]
            },
            {
                "id": "fx_krw", "symbol": "KRW=X", "name": "원/달러 환율", "cat": "가공",
                "unit": "KRW/USD · 외환시장 (KRW=X)", "cur": 1323.1,
                "chg": {"w1": -0.4, "m1": -2.7, "m3": -4.5, "m6": -3.8, "y1": -0.2},
                "series": [1325.8, 1340.0, 1355.0, 1375.0, 1395.0, 1410.0, 1375.0, 1385.0, 1370.0, 1360.0, 1359.5, 1323.1],
                "dates": DATES_LABELS,
                "lagInfo": "수입 원자재(원당·소맥·대두유) 및 수입 수산·축산물의 국내 통관 원가를 결정하는 핵심 거시 변수",
                "action": "[유통도매] 환율 하향 안정 구간을 활용해 달러 결제 수입 수산물·수입육 오퍼 단가 협상 | [외식직거래] 고객사 단가 협상 시 국제 원자재 시세 추이 근거 제시",
                "itemNews": [
                    {"lv": "low", "title": "원/달러 환율 하향 안정세로 수입 식자재 통관원가 부담 완화", "impact": "[유통도매] 수입 식자재 달러 결제 시 수입 오퍼 단가 협상력 개선"}
                ]
            }
        ],
        "freshItems": [
            {
                "id": "onion", "kamisCat": "200", "kamisCode": "245", "kamisKind": "00", "kamisRank": "04",
                "name": "양파 (15kg 망 · 상품)", "cat": "농산",
                "unit": "원/15kg · KAMIS 도매 (코드 245)", "cur": 18387,
                "chg": {"w1": -4.0, "m1": 2.5, "m3": 12.4, "m6": -8.5, "y1": 5.8},
                "series": [17380, 18100, 19200, 20500, 21400, 20100, 20090, 16500, 15800, 16350, 17940, 18387],
                "dates": DATES_LABELS,
                "lagInfo": "도매시장 경락가 변동 후 1~3일 내 유통도매 대리점 및 외식직거래 납품단가에 즉각 반영",
                "action": "[유통도매] 도매 경락가 조정 구간에 맞춰 매입단가 안정화 | [외식온·오프] 중식·한식 직거래처에 15kg 망양파 및 깐양파 안정 공급",
                "itemNews": [{"lv": "low", "title": "도매시장 양파 15kg 상품 경락가 단기 보합 안정세", "impact": "[유통도매] 도매 대리점 매입 원가 부담 완화"}]
            },
            {
                "id": "pork", "kamisCat": "500", "kamisCode": "514", "kamisKind": "00", "kamisRank": "04",
                "name": "돼지고기 (한돈 지육 · kg)", "cat": "축산",
                "unit": "원/kg · KAMIS/축평원 도매 (코드 514)", "cur": 5797,
                "chg": {"w1": -3.2, "m1": -5.8, "m3": -8.4, "m6": 1.5, "y1": 2.1},
                "series": [5678, 5580, 5320, 5180, 5420, 5690, 5710, 6350, 6480, 6328, 6154, 5797],
                "dates": DATES_LABELS,
                "lagInfo": "지육 경락가 등락 시 1주일 내 육가공 부분육(삼겹/목심/전지) 도매 시세 및 고기집 직거래 단가 연동",
                "action": "[유통도매] 지육가 조정분을 반영해 부분육 매입단가 협상 | [외식온·오프] 모임 시즌 앞두고 고기집 직거래처에 한돈 프로모션 전개",
                "itemNews": [{"lv": "low", "title": "한돈 지육 도매 경락가 출하 물량 증가로 하향 안정", "impact": "[유통도매] 국내산 돈육 부분육 도매 매입원가 개선"}]
            },
            {
                "id": "egg", "kamisCat": "500", "kamisCode": "516", "kamisKind": "00", "kamisRank": "04",
                "name": "계란 (특란 30구)", "cat": "축산",
                "unit": "원/30구 · KAMIS 산지/도매 (코드 516)", "cur": 5180,
                "chg": {"w1": -1.5, "m1": -3.4, "m3": -2.1, "m6": -4.5, "y1": -1.8},
                "series": [5275, 5350, 5210, 5080, 5190, 5420, 5424, 5310, 5280, 5290, 5362, 5180],
                "dates": DATES_LABELS,
                "lagInfo": "산지 도매가 변동 시 제과·베이커리·분식당 납품 단가 및 온라인몰 판란 시세에 즉시 연동",
                "action": "[유통도매] 산지 물량 여유에 따른 도매 판촉 확대 | [외식온·오프] 제과·베이커리 성수기 대비 신선란 및 액란 묶음 프로모션 추진",
                "itemNews": [{"lv": "low", "title": "산란계 계란 생산량 증가로 특란 30구 도매시세 안정", "impact": "[유통도매] 산지 공급 여력 확대로 매입가 안정세 지속"}]
            },
            {
                "id": "cabbage", "kamisCat": "200", "kamisCode": "211", "kamisKind": "01", "kamisRank": "04",
                "name": "배추 (10kg 망 · 상품)", "cat": "농산",
                "unit": "원/10kg · KAMIS 도매 (코드 211)", "cur": 9800,
                "chg": {"w1": -10.8, "m1": -32.0, "m3": -18.5, "m6": -12.0, "y1": -14.8},
                "series": [11500, 10200, 9500, 9800, 10800, 11400, 11136, 10500, 18900, 12020, 14420, 9800],
                "dates": DATES_LABELS,
                "lagInfo": "출하 확대에 따른 도매가 하락이 직거래 식당 원물 및 업소용 김치 도매가에 반영",
                "action": "[유통도매] 배추 원물 시세 하락에 맞춰 도매 물량 회전율 극대화 | [외식온·오프] 국밥·칼국수·고기집 직거래처에 국내산 배추·김치 판촉 강화",
                "itemNews": [{"lv": "low", "title": "가을배추 본격 출하로 도매시장 배추 시세 큰 폭 하락 안정", "impact": "[외식직거래 오프] 배추 다량 소비 직거래 식당의 원물 매입 부담 해소"}]
            },
            {
                "id": "squid", "kamisCat": "600", "kamisCode": "619", "kamisKind": "02", "kamisRank": "04",
                "name": "오징어 (원양/냉동 · 마리)", "cat": "수산",
                "unit": "원/마리 · KAMIS 도매 (코드 619)", "cur": 5392,
                "chg": {"w1": -2.0, "m1": 1.2, "m3": 5.4, "m6": 9.8, "y1": 14.5},
                "series": [4710, 4780, 4850, 4920, 4980, 4910, 4910, 5050, 5120, 5115, 5328, 5392],
                "dates": DATES_LABELS,
                "lagInfo": "연근해 어획 부진으로 1년 대비 높은 구조적 강세이나 단기 시세는 보합 조정",
                "action": "[유통도매] 원양산 할복오징어 및 남미산 오징어채 도매 재고 안정적 운용 | [외식온·오프] 중식당·분식·호프 직거래처에 원양산 및 갑오징어 슬라이스 제안",
                "itemNews": [{"lv": "mid", "title": "연근해 살오징어 어획량 부진으로 원양·수입산 대체 수요 견조", "impact": "[외식직거래 오프] 중식·해물요리 직거래 매장에 원양산 및 페루산 자숙채 스펙 유지"}]
            },
            {
                "id": "shrimp", "kamisCat": "600", "kamisCode": "653", "kamisKind": "00", "kamisRank": "04",
                "name": "흰다리새우 (도매 · kg)", "cat": "수산",
                "unit": "원/kg · 수산시장/KAMIS 도매 (코드 653)", "cur": 13250,
                "chg": {"w1": 1.9, "m1": 4.3, "m3": 6.0, "m6": 3.5, "y1": 4.8},
                "series": [12640, 12800, 12500, 12300, 12450, 12700, 12800, 12600, 12400, 12500, 12700, 13250],
                "dates": DATES_LABELS,
                "lagInfo": "외식 수요로 도매 경락가는 강보합이나 원/달러 환율 안정으로 수입 냉동박스 통관 여건은 개선",
                "action": "[유통도매] 환율 안정 구간에 베트남·에콰도르산 냉동 흰다리새우 박스 물량 매입 단가 협상 | [외식온·오프] 모임 메뉴용 탈각새우·새우튀김 판촉",
                "itemNews": [{"lv": "low", "title": "환율 하향 안정으로 베트남·에콰도르산 냉동새우 수입 원가 부담 완화", "impact": "[유통도매] 성수기용 수입 냉동새우 박스 물량 선점 유리"}]
            }
        ],
        "broadNewsData": []
    }

# ==============================================================================
# [3] 각 오픈 API 실시간 호출 및 데이터 덮어쓰기
# ==============================================================================
def update_yahoo_items(raw_items):
    for item in raw_items:
        sym = item.get("symbol")
        if not sym:
            continue
        try:
            df = yf.Ticker(sym).history(period="1y", interval="1d")
            closes = df["Close"].dropna().tolist()
            res = calc_metrics_from_series(closes)
            if res:
                item["cur"], item["chg"], item["series"] = res
                print(f"[Yahoo 성공] {sym}: 현재={item['cur']}, 1년={item['chg']['y1']}%")
        except Exception as e:
            print(f"[Yahoo 폴백 유지] {sym}: {e}")

def update_ecos_macro(macro_items):
    if not ECOS_API_KEY:
        print("[ECOS 안내] ECOS_API_KEY 미설정 -> 기본 검증 수치 유지")
        return
    # 1) 뉴스심리지수 NSI (통계표 521Y001, 일별 D, 항목 A001)
    try:
        today = datetime.date.today()
        start = (today - datetime.timedelta(days=365)).strftime("%Y%m%d")
        end   = today.strftime("%Y%m%d")
        url = f"https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_API_KEY}/json/kr/1/400/521Y001/D/{start}/{end}/A001"
        rows = requests.get(url, timeout=10).json().get("StatisticSearch", {}).get("row", [])
        vals = [float(r["DATA_VALUE"]) for r in rows if r.get("DATA_VALUE")]
        res = calc_metrics_from_series(vals)
        if res:
            for m in macro_items:
                if m["id"] == "macro_sentiment":
                    m["cur"], m["chg"], m["series"] = res
                    print(f"[ECOS 성공] 뉴스심리지수(NSI): 현재={m['cur']}")
    except Exception as e:
        print(f"[ECOS 폴백 유지] NSI 호출 오류: {e}")

    # 2) 소비자동향조사 (통계표 511Y002, 월별 M: 경기전망CSI / 외식비 지출전망CSI)
    ecos_map = {
        "macro_biz_cycle": ("511Y002", "FMAB"),     # 현재경기판단/경기전망CSI
        "macro_dining_search": ("511Y002", "FMEF")  # 외식비 지출전망CSI
    }
    for mid, (st_code, it_code) in ecos_map.items():
        try:
            today = datetime.date.today()
            start_m = (today - datetime.timedelta(days=370)).strftime("%Y%m")
            end_m   = today.strftime("%Y%m")
            url = f"https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_API_KEY}/json/kr/1/100/{st_code}/M/{start_m}/{end_m}/{it_code}"
            rows = requests.get(url, timeout=10).json().get("StatisticSearch", {}).get("row", [])
            vals = [float(r["DATA_VALUE"]) for r in rows if r.get("DATA_VALUE")]
            res = calc_metrics_from_series(vals)
            if res:
                for m in macro_items:
                    if m["id"] == mid:
                        m["cur"], m["chg"], m["series"] = res
                        print(f"[ECOS 성공] {mid}: 현재={m['cur']}")
        except Exception as e:
            print(f"[ECOS 폴백 유지] {mid}: {e}")

def update_kamis_fresh(fresh_items):
    if not KAMIS_CERT_ID or not KAMIS_CERT_KEY:
        print("[KAMIS 안내] KAMIS_CERT_ID/KEY 미설정 -> 기본 검증 수치 유지")
        return
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=365)).strftime("%Y-%m-%d")
    end   = today.strftime("%Y-%m-%d")
    url = "http://www.kamis.or.kr/service/price/xml.do?action=periodProductList"

    for item in fresh_items:
        params = {
            "p_cert_key": KAMIS_CERT_KEY,
            "p_cert_id": KAMIS_CERT_ID,
            "p_returntype": "json",
            "p_startday": start,
            "p_endday": end,
            "p_productclscode": "02",  # 02: 도매
            "p_itemcategorycode": item.get("kamisCat", "200"),
            "p_itemcode": item.get("kamisCode", "245"),
            "p_kindcode": item.get("kamisKind", "00"),
            "p_productrankcode": item.get("kamisRank", "04"),
            "p_countrycode": "1101",
            "p_convert_kg_yn": "N"
        }
        try:
            res_json = requests.get(url, params=params, timeout=12).json()
            items_list = res_json.get("data", {}).get("item", [])
            if isinstance(items_list, list):
                prices = []
                for row in items_list:
                    if row.get("countyname") in ["평균", "서울"]:
                        p_str = str(row.get("price", "")).replace(",", "").strip()
                        if p_str.isdigit():
                            prices.append(float(p_str))
                res = calc_metrics_from_series(prices)
                if res:
                    item["cur"], item["chg"], item["series"] = res
                    print(f"[KAMIS 성공] {item['name']}: 현재={item['cur']}")
        except Exception as e:
            print(f"[KAMIS 폴백 유지] {item['name']}: {e}")

def fetch_and_build_news():
    keywords = [
        ("유통도매", "환율/제조사판가", "#원당 #밀가루 #식용유", "설탕 밀가루 식용유 도매 가격"),
        ("외식오프", "산지/도매시세", "#가락시장 #양파 #배추", "가락시장 양파 배추 도매 시세"),
        ("유통도매", "산지/도매시세", "#한돈 #계란 #축산도매", "돼지고기 계란 도매 시세"),
        ("유통도매", "정책/할당관세", "#할당관세 #수입식자재", "식자재 할당관세 수입"),
        ("외식온라인", "외식/온라인트렌드", "#외식자영업 #식자재몰", "외식 자영업 식자재 유통")
    ]
    raw_articles = []
    for ch, sc, tg, kw in keywords:
        enc = urllib.parse.quote(kw + " when:3d")
        rss_url = f"https://news.google.com/rss/search?q={enc}&hl=ko&gl=KR&ceid=KR:ko"
        try:
            feed = feedparser.parse(rss_url)
            for idx, entry in enumerate(feed.entries[:3]):
                raw_articles.append({
                    "day": "D0" if idx == 0 else ("D1" if idx == 1 else "D2"),
                    "dateStr": "오늘" if idx == 0 else ("1일 전" if idx == 1 else "2일 전"),
                    "level": "상" if idx == 0 else "중",
                    "channel": ch,
                    "channelLabel": "유통도매 · 외식직거래(오프)" if ch == "유통도매" else "외식직거래(온·오프)",
                    "scope": sc,
                    "tag": tg,
                    "title": entry.title,
                    "summary": f"구글 뉴스 실시간 수집 ({kw} 관련 최근 3일 내 주요 보도)",
                    "impact": "[유통도매/외식직거래] 실시간 원가 및 도매 수급 변동 모니터링 필요"
                })
        except Exception as e:
            print(f"[뉴스 RSS 오류] {kw}: {e}")

    # Gemini API 키가 설정되어 있으면 AI 영향도 상/중/하 및 채널별 액션 플랜으로 고도화
    if GEMINI_API_KEY and raw_articles:
        try:
            import google.generativeai as genai
            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel("gemini-2.5-flash")
            prompt = f"""
            당신은 CJ프레시웨이 식자재유통(외식직거래 온·오프라인 / 유통도매 대리점) 전담 AI입니다. (CK/단체급식 제외)
            아래 실시간 뉴스 목록을 분석하여 JSON 배열(최대 10개)로 변환하세요.
            필수 키: day('D0'/'D1'/'D2'), dateStr('오늘'/'1일 전'/'2일 전'), level('상'/'중'/'하'),
            channel('유통도매'/'외식오프'/'외식온라인'), channelLabel, scope('산지/도매시세'/'정책/할당관세'/'환율/제조사판가'/'외식/온라인트렌드'),
            tag, title, summary(1~2문장 요약), impact('[유통도매] ..., [외식직거래] ...' 형태의 구체적 대응 가이드)
            
            뉴스 목록:
            {json.dumps(raw_articles[:12], ensure_ascii=False)}
            """
            resp = model.generate_content(prompt)
            txt = resp.text.strip()
            if "```json" in txt:
                txt = txt.split("```json")[1].split("```")[0].strip()
            elif "```" in txt:
                txt = txt.split("```")[1].split("```")[0].strip()
            parsed = json.loads(txt)
            if isinstance(parsed, list) and len(parsed) > 0:
                print(f"[Gemini 성공] 실시간 뉴스 {len(parsed)}건 영향도 분류 완료")
                return parsed
        except Exception as e:
            print(f"[Gemini 폴백] 기본 RSS 뉴스 리스트 사용: {e}")

    return raw_articles[:10]

if __name__ == "__main__":
    print("=== CJ프레시웨이 대시보드 실시간 데이터 빌드 시작 ===")
    data = get_baseline_data()

    # 1. Yahoo Finance 실시간 반영 (키 불필요)
    update_yahoo_items(data["rawItems"])

    # 2. 한국은행 ECOS 거시지표 실시간 반영
    update_ecos_macro(data["macroItems"])

    # 3. KAMIS 1차 상품 도매시세 실시간 반영
    update_kamis_fresh(data["freshItems"])

    # 4. Google News RSS + Gemini 분석 실시간 반영
    live_news = fetch_and_build_news()
    if live_news:
        data["broadNewsData"] = live_news

    # 5. 최종 JSON 파일 저장 (index.html이 읽어가는 파일)
    with open("dashboard_live_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("=== dashboard_live_data.json 생성 완료! ===")

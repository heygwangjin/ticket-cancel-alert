"""NOL티켓(nol.yanolja.com, 구 인터파크 티켓) 잔여석 조회.

상품 페이지가 브라우저에서 호출하는 비로그인 JSON API를 그대로 사용한다.
  1) 상품 페이지 HTML  → goodsKey(상품코드:공연장코드), 공연명, 공연 기간
  2) GET /ticket/products/api/schedules?goodsKey=&playStartDate=&playEndDate=  → 회차 목록
  3) GET /ticket/products/api/remaining-seats?goodsCode=&playSeq=              → 등급별 잔여석
로그인·대기열·예매 단계의 API 는 사용하지 않는다.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import groupby
from typing import Callable
from zoneinfo import ZoneInfo

import httpx

from config import Settings, Target
from sites.base import SeatAvailability, SiteError, grade_matches, http_get, make_client, polite_sleep

log = logging.getLogger(__name__)

BASE_URL = "https://nol.yanolja.com"
PRODUCT_URL = BASE_URL + "/ticket/products/{code}"
SCHEDULES_API = BASE_URL + "/ticket/products/api/schedules"
REMAINING_API = BASE_URL + "/ticket/products/api/remaining-seats"

GOODS_INFO_TTL_SEC = 6 * 3600   # 공연명·기간은 자주 바뀌지 않으므로 6시간 캐시
SCHEDULE_WINDOW_DAYS = 60       # 웹 페이지처럼 회차 목록을 약 2달 단위로 나눠 조회
KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class GoodsInfo:
    code: str
    key: str            # "26015024:26001292"
    name: str
    play_start: str     # "YYYY-MM-DD"
    play_end: str


@dataclass(frozen=True)
class Schedule:
    play_seq: str       # "001" — 상품 전체에서의 회차 번호
    date: str
    time: str
    round: int          # 그날의 몇 번째 회차인지 (1부터)
    sale_close: str     # "YYYY-MM-DD HH:MM:SS"


# ---------------------------------------------------------------- 파싱 (순수 함수)

def parse_goods_id(url_or_id: str) -> str:
    """공연 URL 또는 상품 ID에서 상품코드(숫자)를 꺼낸다."""
    s = str(url_or_id).strip()
    if s.isdigit():
        return s
    m = re.search(r"/(?:products|goods)/(\d+)", s) or re.search(r"[?&]goodsCode=(\d+)", s, re.I)
    if not m:
        raise ValueError(f"상품 ID를 찾을 수 없는 주소입니다: {s}")
    return m.group(1)


def _decode_next_payload(html: str) -> str:
    """Next.js 가 self.__next_f.push([1,"..."]) 로 심어둔 데이터를 이어 붙여 디코딩."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', html, re.S)
    return "".join(json.loads(f'"{c}"') for c in chunks)


def parse_goods_page(html: str, code: str) -> GoodsInfo:
    text = _decode_next_payload(html) or html

    def find(field: str, value_pattern: str = r'(?:[^"\\]|\\.)*') -> str | None:
        m = re.search(rf'"{field}":"({value_pattern})"', text)
        return json.loads(f'"{m.group(1)}"') if m else None

    key = find("goodsKey", rf"{code}:\d+")
    start = find("playStartDate", r"\d{4}-\d{2}-\d{2}")
    end = find("playEndDate", r"\d{4}-\d{2}-\d{2}")
    if not (key and start and end):
        raise SiteError(f"상품 {code} 페이지에서 공연 정보를 찾지 못했습니다 (페이지 구조 변경 가능성).")
    return GoodsInfo(code=code, key=key, name=find("goodsName") or code, play_start=start, play_end=end)


def parse_schedules(data: dict) -> list[Schedule]:
    try:
        rows = sorted(data["content"], key=lambda r: (r["playDate"], r["playTime"]))
        result = []
        for day, items in groupby(rows, key=lambda r: r["playDate"]):
            for i, r in enumerate(items, start=1):
                result.append(Schedule(
                    play_seq=str(r["playSeq"]), date=day, time=r.get("playTime", ""),
                    round=i, sale_close=r.get("saleCloseTime", ""),
                ))
        return result
    except (KeyError, TypeError) as e:
        raise SiteError(f"회차 응답 형식이 예상과 다릅니다: {e!r}") from None


def parse_remaining(data: dict) -> list[tuple[str, int]]:
    """[(등급명, 잔여수량), ...]"""
    try:
        return [(r["seatGradeName"], int(r["remainCnt"])) for r in data["remainSeat"]]
    except (KeyError, TypeError, ValueError) as e:
        raise SiteError(f"잔여석 응답 형식이 예상과 다릅니다: {e!r}") from None


def _json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except ValueError:
        raise SiteError(f"JSON 이 아닌 응답: {resp.text[:120]!r}") from None


# ---------------------------------------------------------------- 조회

class NolSite:
    def __init__(self, settings: Settings, client: httpx.Client | None = None,
                 sleep: Callable[[], None] | None = None,
                 now: Callable[[], datetime] = lambda: datetime.now(KST)):
        self._settings = settings
        self._client = client or make_client(referer=BASE_URL + "/ticket")
        self._sleep = sleep or (lambda: polite_sleep(settings))
        self._now = now
        self._goods_cache: dict[str, tuple[float, GoodsInfo]] = {}

    def fetch_goods_info(self, code: str) -> GoodsInfo:
        cached = self._goods_cache.get(code)
        if cached and time.monotonic() - cached[0] < GOODS_INFO_TTL_SEC:
            return cached[1]
        resp = http_get(self._client, PRODUCT_URL.format(code=code))
        info = parse_goods_page(resp.text, code)
        self._goods_cache[code] = (time.monotonic(), info)
        self._sleep()
        return info

    def fetch_schedules(self, info: GoodsInfo, start: date, end: date) -> list[Schedule]:
        schedules: list[Schedule] = []
        win_start = start
        while win_start <= end:
            win_end = min(win_start + timedelta(days=SCHEDULE_WINDOW_DAYS - 1), end)
            resp = http_get(self._client, SCHEDULES_API, params={
                "goodsKey": info.key,
                "playStartDate": win_start.isoformat(),
                "playEndDate": win_end.isoformat(),
            })
            schedules += parse_schedules(_json(resp))
            win_start = win_end + timedelta(days=1)
            if win_start <= end:
                self._sleep()
        return schedules

    def fetch_remaining(self, code: str, play_seq: str) -> list[tuple[str, int]]:
        resp = http_get(self._client, REMAINING_API, params={"goodsCode": code, "playSeq": play_seq})
        return parse_remaining(_json(resp))

    def fetch(self, target: Target) -> list[SeatAvailability]:
        code = parse_goods_id(target.goods)
        info = self.fetch_goods_info(code)
        now = self._now()

        # 조회 기간: 공연 기간 ∩ 오늘 이후 ∩ config 의 dates 범위
        start = max(date.fromisoformat(info.play_start), now.date())
        end = date.fromisoformat(info.play_end)
        if target.dates:
            start = max(start, date.fromisoformat(min(target.dates)))
            end = min(end, date.fromisoformat(max(target.dates)))
        if start > end:
            log.info("[%s] 조회할 남은 공연일이 없습니다.", target.name or info.name)
            return []

        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        schedules = [
            s for s in self.fetch_schedules(info, start, end)
            if (not target.dates or s.date in target.dates)
            and (not target.rounds or s.round in target.rounds)
            and (not s.sale_close or s.sale_close > now_str)   # 예매 마감된 회차 제외
        ]
        limit = self._settings.max_rounds_per_target
        if len(schedules) > limit:
            log.warning("[%s] 회차 %d개 중 앞의 %d개만 조회합니다. dates/rounds 로 범위를 좁히세요.",
                        target.name or info.name, len(schedules), limit)
            schedules = schedules[:limit]

        title = target.name or info.name
        url = PRODUCT_URL.format(code=code)
        result: list[SeatAvailability] = []
        for s in schedules:
            self._sleep()
            for grade, remain in self.fetch_remaining(code, s.play_seq):
                if grade_matches(target.grades, grade):
                    result.append(SeatAvailability(
                        title=title, date=s.date, round=s.round, time=s.time,
                        grade=grade, remain=remain, booking_url=url,
                    ))
        return result


if __name__ == "__main__":
    # 사용법: python -m sites.nol <공연 URL 또는 상품 ID> [YYYY-MM-DD ...]
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if len(sys.argv) < 2:
        sys.exit("사용법: python -m sites.nol <공연 URL 또는 상품 ID> [YYYY-MM-DD ...]")
    target = Target(site="nol", goods=sys.argv[1], dates=tuple(sys.argv[2:]))
    try:
        seats = NolSite(Settings()).fetch(target)
    except (SiteError, ValueError) as e:
        sys.exit(f"조회 실패: {e}")
    if not seats:
        print("조회된 회차가 없습니다.")
    else:
        print(f"\n{seats[0].title}  {seats[0].booking_url}")
        for s in seats:
            print(f"  {s.date} {s.round}회 {s.time}  {s.grade:<10} 잔여 {s.remain}")

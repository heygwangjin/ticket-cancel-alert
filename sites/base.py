"""사이트 모듈이 공통으로 쓰는 데이터 타입과 HTTP 도우미."""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from config import Settings, Target

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_RETRIES = 2


class SiteError(Exception):
    """조회 실패 (네트워크 오류, 예상과 다른 응답 등)."""


@dataclass(frozen=True)
class SeatAvailability:
    title: str          # 공연명
    date: str           # "YYYY-MM-DD"
    round: int          # 그날의 회차 (1, 2, ...)
    time: str           # "19:30"
    grade: str          # 좌석 등급명
    remain: int         # 잔여 수량
    booking_url: str


class Site(Protocol):
    def fetch(self, target: Target) -> list[SeatAvailability]:
        """대상의 (필터 적용된) 회차·등급별 잔여석을 반환. 실패하면 SiteError."""
        ...


def make_client(referer: str) -> httpx.Client:
    return httpx.Client(
        timeout=15,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Referer": referer, "Accept-Language": "ko-KR,ko;q=0.9"},
    )


def polite_sleep(settings: Settings) -> None:
    """서버 부담을 줄이기 위해 요청 사이에 무작위로 쉰다."""
    time.sleep(random.uniform(*settings.request_delay_sec))


def http_get(client: httpx.Client, url: str, params: dict | None = None) -> httpx.Response:
    """GET 요청. 429/5xx 는 지수 백오프로 최대 MAX_RETRIES 회 재시도."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = client.get(url, params=params)
        except httpx.HTTPError as e:
            err = f"{type(e).__name__}: {e}"
        else:
            if resp.status_code == 200:
                return resp
            err = f"HTTP {resp.status_code}"
            if resp.status_code not in RETRY_STATUS:
                break
        if attempt < MAX_RETRIES:
            wait = 5 * 2**attempt + random.uniform(0, 2)
            log.warning("%s 실패(%s), %.0f초 후 재시도", url, err, wait)
            time.sleep(wait)
    raise SiteError(f"{url} 요청 실패: {err}")


def _norm_grade(name: str) -> str:
    name = name.replace(" ", "").upper()
    return name[:-1] if name.endswith("석") and len(name) > 1 else name


def grade_matches(wanted: tuple[str, ...], grade_name: str) -> bool:
    """config 의 등급("VIP", "R석", "지정석 R")이 사이트 등급명과 맞는지.

    전체 이름 또는 공백으로 나눈 단어 중 하나와 같으면 일치로 본다.
    예) "R" → "지정석 R" 일치, "플로어" → "플로어석" 일치, "R" → "VIP" 불일치
    """
    if not wanted:
        return True
    candidates = {_norm_grade(grade_name), *(_norm_grade(t) for t in grade_name.split())}
    return any(_norm_grade(w) in candidates for w in wanted)

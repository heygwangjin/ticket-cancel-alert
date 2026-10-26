"""config.yaml(감시 대상·설정)과 .env(비밀값)를 읽어 검증된 객체로 만든다."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


class ConfigError(Exception):
    pass


WINDOW_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d")


@dataclass(frozen=True)
class Target:
    site: str
    goods: str                      # 상품 URL 또는 상품 ID
    name: str = ""                  # 비우면 사이트에서 가져온 공연명 사용
    dates: tuple[str, ...] = ()     # "YYYY-MM-DD", 비우면 전체
    rounds: tuple[int, ...] = ()    # 회차 번호, 비우면 전체
    grades: tuple[str, ...] = ()    # 좌석 등급명, 비우면 전체

    @property
    def id(self) -> str:
        return f"{self.site}:{self.goods}"


@dataclass(frozen=True)
class Settings:
    interval_min_sec: float = 180
    interval_max_sec: float = 300
    request_delay_sec: tuple[float, float] = (2, 6)
    failure_alert_threshold: int = 3
    max_rounds_per_target: int = 20  # 한 대상에서 한 번에 조회할 회차 수 상한 (요청 폭주 방지)
    app_open_page: str = ""          # 앱 열기 중계 페이지 주소 (docs/open.html 을 배포한 URL)
    # 집중 감시: 아래 시간대에는 focus_interval_sec 간격으로 점검
    focus_interval_sec: float = 60
    focus_windows: tuple[str, ...] = ()       # 매일 반복, 한국 시간 "HH:MM-HH:MM" (자정 넘김 가능)
    focus_before_cancel_close_min: int = 0    # 감시 회차의 취소 마감 N분 전 ~ 마감 (0이면 사용 안 함)


@dataclass(frozen=True)
class Config:
    settings: Settings
    targets: tuple[Target, ...]
    telegram_token: str = field(repr=False)
    telegram_chat_id: str


def load_telegram_credentials() -> tuple[str, str]:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise ConfigError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 .env 또는 환경변수에 없습니다.")
    return token, chat_id


def _parse_settings(raw: dict) -> Settings:
    s = Settings(
        interval_min_sec=float(raw.get("interval_min_sec", Settings.interval_min_sec)),
        interval_max_sec=float(raw.get("interval_max_sec", Settings.interval_max_sec)),
        request_delay_sec=tuple(float(x) for x in raw.get("request_delay_sec", Settings.request_delay_sec)),
        failure_alert_threshold=int(raw.get("failure_alert_threshold", Settings.failure_alert_threshold)),
        max_rounds_per_target=int(raw.get("max_rounds_per_target", Settings.max_rounds_per_target)),
        app_open_page=str(raw.get("app_open_page") or "").strip(),
        focus_interval_sec=float(raw.get("focus_interval_sec", Settings.focus_interval_sec)),
        focus_windows=tuple(str(w).replace(" ", "") for w in raw.get("focus_windows") or ()),
        focus_before_cancel_close_min=int(raw.get("focus_before_cancel_close_min", 0)),
    )
    if len(s.request_delay_sec) != 2 or s.request_delay_sec[0] > s.request_delay_sec[1]:
        raise ConfigError("request_delay_sec 는 [최소, 최대] 형식이어야 합니다.")
    if s.interval_min_sec < 60 or s.interval_min_sec > s.interval_max_sec:
        raise ConfigError("interval_min_sec 는 60초 이상이고 interval_max_sec 이하여야 합니다.")
    if s.failure_alert_threshold < 1:
        raise ConfigError("failure_alert_threshold 는 1 이상이어야 합니다.")
    if not 1 <= s.max_rounds_per_target <= 50:
        raise ConfigError("max_rounds_per_target 는 1~50 사이여야 합니다.")
    if s.app_open_page and not s.app_open_page.startswith("https://"):
        raise ConfigError("app_open_page 는 https:// 주소여야 합니다 (텔레그램 버튼 제약).")
    if s.focus_interval_sec < 60:
        raise ConfigError("focus_interval_sec 는 60초 이상이어야 합니다.")
    for w in s.focus_windows:
        if not WINDOW_RE.fullmatch(w):
            raise ConfigError(f'focus_windows 형식 오류: {w!r} (예: "23:50-00:20")')
    if s.focus_before_cancel_close_min < 0:
        raise ConfigError("focus_before_cancel_close_min 는 0 이상이어야 합니다.")
    return s


def _parse_target(raw: dict, index: int) -> Target:
    if not isinstance(raw, dict) or not raw.get("goods"):
        raise ConfigError(f"targets[{index}] 에 goods(공연 URL 또는 상품 ID)가 없습니다.")
    return Target(
        site=str(raw.get("site", "nol")),
        goods=str(raw["goods"]).strip(),
        name=str(raw.get("name") or ""),
        # YAML 은 따옴표 없는 2026-11-15 를 date 로 읽으므로 str() 로 통일
        dates=tuple(str(d) for d in raw.get("dates") or ()),
        rounds=tuple(int(r) for r in raw.get("rounds") or ()),
        grades=tuple(str(g).strip() for g in raw.get("grades") or ()),
    )


def load_config(path: str | Path = "config.yaml") -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"{path} 가 없습니다. config.example.yaml 을 복사해 만드세요.")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    targets = tuple(_parse_target(t, i) for i, t in enumerate(raw.get("targets") or ()))
    if not targets:
        raise ConfigError("targets 에 감시 대상이 하나도 없습니다.")
    token, chat_id = load_telegram_credentials()
    return Config(
        settings=_parse_settings(raw.get("settings") or {}),
        targets=targets,
        telegram_token=token,
        telegram_chat_id=chat_id,
    )

"""점검 1회: 대상별로 잔여석을 조회하고, 새로 생긴 좌석만 텔레그램으로 알린다."""
from __future__ import annotations

import html
import logging
import random
import time
from collections import defaultdict
from datetime import date
from typing import Callable
from urllib.parse import quote

from config import Config, Target
from notifier import NotifyError, TelegramNotifier
from sites import get_site
from sites.base import SeatAvailability, Site
from state import State, seat_key

log = logging.getLogger(__name__)

WEEKDAYS = "월화수목금토일"


def target_label(target: Target) -> str:
    return target.name or target.goods


def format_seat_alert(seats: list[SeatAvailability]) -> str:
    first = seats[0]
    lines = ["🎫 <b>취소표 발견!</b>", f"<b>{html.escape(first.title)}</b>", ""]
    for s in seats:
        wd = WEEKDAYS[date.fromisoformat(s.date).weekday()]
        lines.append(f"• {s.date} ({wd}) {s.round}회 {s.time} — {html.escape(s.grade)} <b>{s.remain}매</b>")
    return "\n".join(lines)


def booking_buttons(booking_url: str, app_open_page: str = "") -> list[tuple[str, str]]:
    """웹 링크 버튼, 그리고 중계 페이지가 설정돼 있으면 앱 열기 버튼."""
    buttons = [("🌐 웹에서 열기", booking_url)]
    if app_open_page:
        buttons.insert(0, ("📱 NOL 앱에서 열기", f"{app_open_page}?url={quote(booking_url, safe='')}"))
    return buttons


def format_failure_alert(target: Target, count: int, error: Exception) -> str:
    return (f"⚠️ <b>감시 오류</b>: {html.escape(target_label(target))}\n"
            f"연속 {count}회 조회에 실패했습니다.\n"
            f"마지막 오류: <code>{html.escape(str(error)[:300])}</code>")


def format_recovery_alert(target: Target) -> str:
    return f"✅ <b>감시 복구</b>: {html.escape(target_label(target))} 조회가 다시 정상입니다."


class Monitor:
    def __init__(self, config: Config, state: State, notifier: TelegramNotifier,
                 site_factory: Callable = get_site, sleep: Callable[[], None] | None = None):
        self.config = config
        self.state = state
        self.notifier = notifier
        self._site_factory = site_factory
        self._sites: dict[str, Site] = {}   # 루프 실행 시 사이트 객체(캐시 포함)를 재사용
        self._sleep = sleep or (lambda: time.sleep(random.uniform(*config.settings.request_delay_sec)))

    def _site(self, name: str) -> Site:
        if name not in self._sites:
            self._sites[name] = self._site_factory(name, self.config.settings)
        return self._sites[name]

    def run_cycle(self) -> None:
        """모든 대상을 한 번씩 점검하고 상태를 저장한다. 예외를 밖으로 던지지 않는다."""
        self.state.prune_seats({t.id for t in self.config.targets})
        for i, target in enumerate(self.config.targets):
            if i:
                self._sleep()
            try:
                self._check(target)
            except Exception as e:  # 한 대상의 오류가 다른 대상·봇 전체를 멈추지 않게
                log.exception("[%s] 점검 실패", target_label(target))
                self._on_failure(target, e)
        try:
            self.state.save()
        except OSError:
            log.exception("상태 저장 실패")

    def _check(self, target: Target) -> None:
        seats = self._site(target.site).fetch(target)
        newly = [s for s in seats
                 if self.state.is_newly_available(seat_key(target.id, s.date, s.round, s.grade), s.remain)]
        log.info("[%s] 좌석 %d건 확인, 새 잔여석 %d건",
                 seats[0].title if seats else target_label(target), len(seats), len(newly))

        sent = True
        if newly:
            try:
                self._send_grouped(newly)
            except NotifyError:
                # 알림을 못 보냈으면 해당 좌석은 상태를 갱신하지 않아 다음 점검 때 다시 시도
                log.exception("[%s] 잔여석 알림 전송 실패, 다음 점검에서 재시도", target_label(target))
                sent = False
        for s in seats:
            if sent or s not in newly:
                self.state.set_seat(seat_key(target.id, s.date, s.round, s.grade), s.remain)

        if self.state.record_success(target.id):
            self._notify_quietly(format_recovery_alert(target))

    def _send_grouped(self, seats: list[SeatAvailability]) -> None:
        by_show: dict[str, list[SeatAvailability]] = defaultdict(list)
        for s in seats:
            by_show[s.booking_url].append(s)
        for url, group in by_show.items():
            self.notifier.send(format_seat_alert(group),
                               buttons=booking_buttons(url, self.config.settings.app_open_page))

    def _on_failure(self, target: Target, error: Exception) -> None:
        count = self.state.record_failure(target.id)
        threshold = self.config.settings.failure_alert_threshold
        if count >= threshold and not self.state.failure_alerted(target.id):
            if self._notify_quietly(format_failure_alert(target, count, error)):
                self.state.mark_failure_alerted(target.id)

    def _notify_quietly(self, text: str) -> bool:
        try:
            self.notifier.send(text)
            return True
        except NotifyError:
            log.exception("텔레그램 전송 실패")
            return False


if __name__ == "__main__":
    # 사용법: python -m monitor  → config.yaml 의 대상을 한 번 점검 (state.json 사용)
    from config import load_config

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = load_config()
    Monitor(cfg, State.load("state.json"), TelegramNotifier(cfg.telegram_token, cfg.telegram_chat_id)).run_cycle()

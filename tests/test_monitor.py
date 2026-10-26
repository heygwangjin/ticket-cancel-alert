import json

import pytest

from config import Config, Settings, Target
from monitor import Monitor
from notifier import NotifyError
from sites.base import SeatAvailability, SiteError
from state import State

TARGET = Target(site="fake", goods="100", name="테스트 공연")
URL = "https://nol.yanolja.com/ticket/products/100"


def seat(grade="R석", remain=0, date="2027-01-16", round_=1):
    return SeatAvailability(title="테스트 공연", date=date, round=round_, time="19:00",
                            grade=grade, remain=remain, booking_url=URL)


class FakeSite:
    def __init__(self):
        self.result = []          # list[SeatAvailability] 또는 Exception

    def fetch(self, target):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeNotifier:
    def __init__(self):
        self.sent = []
        self.buttons = []
        self.fail = False

    def send(self, text, buttons=None):
        if self.fail:
            raise NotifyError("down")
        self.sent.append(text)
        self.buttons.append(buttons)


@pytest.fixture
def env(tmp_path):
    site, notifier = FakeSite(), FakeNotifier()
    cfg = Config(settings=Settings(failure_alert_threshold=3, app_open_page="https://me.github.io/r/open.html"),
                 targets=(TARGET,),
                 telegram_token="T", telegram_chat_id="1")
    state_path = tmp_path / "state.json"

    def run(result):
        # 매번 파일에서 상태를 다시 읽어 --once(Actions) 실행과 같은 조건으로 확인
        site.result = result
        Monitor(cfg, State.load(state_path), notifier,
                site_factory=lambda name, s: site, sleep=lambda: None).run_cycle()
        return notifier.sent

    return run, notifier, state_path


def test_new_seat_alerts_once(env):
    run, notifier, _ = env
    run([seat(remain=0)])
    assert notifier.sent == []
    run([seat(remain=2)])                       # 0 → 2: 알림
    assert len(notifier.sent) == 1
    assert "R석 <b>2매</b>" in notifier.sent[0] and "2027-01-16 (토) 1회" in notifier.sent[0]
    assert notifier.buttons[0] == [
        ("📱 NOL 앱에서 열기",
         "https://me.github.io/r/open.html?url=https%3A%2F%2Fnol.yanolja.com%2Fticket%2Fproducts%2F100"),
        ("🌐 웹에서 열기", URL),
    ]
    run([seat(remain=1)])                       # 2 → 1: 알림 없음
    run([seat(remain=2)])                       # 1 → 2: 알림 없음 (계속 남아 있던 좌석)
    assert len(notifier.sent) == 1


def test_seat_reappearing_after_soldout_alerts_again(env):
    run, notifier, _ = env
    run([seat(remain=1)])
    run([seat(remain=0)])
    run([seat(remain=3)])                       # 1 → 0 → 3: 재알림
    assert len(notifier.sent) == 2


def test_multiple_new_seats_grouped_into_one_message(env):
    run, notifier, _ = env
    run([seat("R석", 1), seat("S석", 2), seat("VIP석", 0)])
    assert len(notifier.sent) == 1
    assert "R석" in notifier.sent[0] and "S석" in notifier.sent[0] and "VIP석" not in notifier.sent[0]


def test_failed_send_is_retried_next_cycle(env):
    run, notifier, _ = env
    notifier.fail = True
    run([seat(remain=2)])
    notifier.fail = False
    run([seat(remain=2)])                       # 직전 전송 실패 → 이번에 전송
    run([seat(remain=2)])
    assert len(notifier.sent) == 1


def test_failure_alert_after_threshold_then_recovery(env):
    run, notifier, state_path = env
    run(SiteError("HTTP 503"))
    run(SiteError("HTTP 503"))
    assert notifier.sent == []
    run(SiteError("HTTP 503"))                  # 3회 연속 실패: 오류 알림
    assert len(notifier.sent) == 1 and "감시 오류" in notifier.sent[0] and "연속 3회" in notifier.sent[0]
    run(SiteError("HTTP 503"))                  # 이미 알렸으므로 추가 알림 없음
    assert len(notifier.sent) == 1
    run([seat(remain=0)])                       # 성공: 복구 알림
    assert "감시 복구" in notifier.sent[-1]
    assert json.loads(state_path.read_text())["failures"] == {}


def test_success_resets_failure_count(env):
    run, notifier, _ = env
    run(SiteError("x"))
    run(SiteError("x"))
    run([seat(remain=0)])
    run(SiteError("x"))
    run(SiteError("x"))
    assert notifier.sent == []                  # 연속 3회가 아니므로 알림 없음


def test_unexpected_exception_does_not_crash(env):
    run, notifier, _ = env
    run(RuntimeError("boom"))                   # 예외가 밖으로 나오지 않아야 함


def test_corrupt_state_file_recovers(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json", encoding="utf-8")
    st = State.load(p)
    assert st.seats == {} and (tmp_path / "state.corrupt.json").exists()


def test_removed_target_is_pruned(env):
    run, notifier, state_path = env
    data = {"version": 1, "seats": {"fake:999|2027-01-01|1|R석": 3}, "failures": {"fake:999": {"count": 5, "alerted": True}}}
    state_path.write_text(json.dumps(data), encoding="utf-8")
    run([seat(remain=0)])
    saved = json.loads(state_path.read_text())
    assert all(not k.startswith("fake:999") for k in saved["seats"]) and saved["failures"] == {}


def test_booking_buttons_without_app_page():
    from monitor import booking_buttons
    assert booking_buttons(URL) == [("🌐 웹에서 열기", URL)]


# ---------------------------------------------------------------- 집중 감시

from datetime import datetime

from monitor import KST, focus_reason

FOCUS = Settings(focus_windows=("23:50-00:20", "12:00-12:10"), focus_before_cancel_close_min=60)


def at(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=KST)


@pytest.mark.parametrize("now,expected", [
    ("2026-10-26 23:49", None),
    ("2026-10-26 23:50", "시간대 23:50-00:20"),
    ("2026-10-27 00:10", "시간대 23:50-00:20"),   # 자정 넘김
    ("2026-10-27 00:20", None),
    ("2026-10-27 12:05", "시간대 12:00-12:10"),
])
def test_focus_windows(now, expected):
    assert focus_reason(at(now), FOCUS, []) == expected


@pytest.mark.parametrize("now,inside", [
    ("2027-01-13 15:59", False),
    ("2027-01-13 16:01", True),
    ("2027-01-13 17:00", True),
    ("2027-01-13 17:02", False),
])
def test_focus_before_cancel_close(now, inside):
    reason = focus_reason(at(now), FOCUS, ["2027-01-13 17:00:59", "bad-value"])
    assert (reason == "취소 마감 2027-01-13 17:00 직전") is inside


def test_focus_disabled_by_default():
    assert focus_reason(at("2026-10-26 23:55"), Settings(), ["2026-10-26 23:59:00"]) is None


def test_monitor_tracks_cancel_close(tmp_path):
    site = FakeSite()
    site.result = [SeatAvailability("t", "2027-01-14", 1, "19:30", "R석", 0, URL, cancel_close="2027-01-13 17:00:59")]
    cfg = Config(settings=Settings(focus_before_cancel_close_min=60), targets=(TARGET,),
                 telegram_token="T", telegram_chat_id="1")
    m = Monitor(cfg, State(tmp_path / "s.json"), FakeNotifier(), site_factory=lambda n, s: site, sleep=lambda: None)
    assert m.focus_reason(at("2027-01-13 16:30")) is None     # 아직 조회 전
    m.run_cycle()
    assert m.focus_reason(at("2027-01-13 16:30")) == "취소 마감 2027-01-13 17:00 직전"

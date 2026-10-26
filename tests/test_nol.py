import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import respx

from config import Settings, Target
from sites.base import SiteError, grade_matches
from sites.nol import (
    PRODUCT_URL, REMAINING_API, SCHEDULES_API, KST,
    NolSite, parse_goods_id, parse_goods_page, parse_remaining, parse_schedules,
)

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return (FIX / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- 파서

@pytest.mark.parametrize("value", [
    "26015024",
    "https://nol.yanolja.com/ticket/products/26015024",
    "https://nol.yanolja.com/ticket/products/26015024?utm=x",
    "https://tickets.interpark.com/goods/26015024",
    "https://ticket.interpark.com/Ticket/Goods/GoodsInfo.asp?GoodsCode=26015024",
])
def test_parse_goods_id(value):
    assert parse_goods_id(value) == "26015024"


def test_parse_goods_id_invalid():
    with pytest.raises(ValueError):
        parse_goods_id("https://nol.yanolja.com/ticket")


def test_parse_goods_page():
    info = parse_goods_page(load("nol_goods_page.html"), "26015024")
    assert info.key == "26015024:26001292"
    assert info.name == "요네즈 켄시 내한공연"
    assert (info.play_start, info.play_end) == ("2027-01-14", "2027-01-17")


def test_parse_goods_page_structure_changed():
    with pytest.raises(SiteError):
        parse_goods_page("<html></html>", "26015024")


def test_parse_schedules_assigns_daily_round():
    data = json.loads(load("nol_schedules.json"))
    # 같은 날 회차를 하나 더 넣어 "그날의 회차" 번호가 시간순으로 매겨지는지 확인
    data["content"].append({**data["content"][1], "playSeq": "004", "playTime": "14:00"})
    s = parse_schedules(data)
    jan16 = [x for x in s if x.date == "2027-01-16"]
    assert [(x.time, x.round, x.play_seq) for x in jan16] == [("14:00", 1, "004"), ("19:00", 2, "002")]


def test_parse_remaining():
    assert parse_remaining(json.loads(load("nol_remaining_some.json"))) == [
        ("플로어석", 2), ("지정석 P", 0), ("지정석 R", 1), ("지정석 S", 0),
    ]


def test_parse_remaining_bad_shape():
    with pytest.raises(SiteError):
        parse_remaining({"unexpected": []})


@pytest.mark.parametrize("wanted,name,expected", [
    ((), "지정석 R", True),
    (("R",), "지정석 R", True),
    (("R석",), "지정석 R", True),
    (("지정석 R",), "지정석 R", True),
    (("플로어",), "플로어석", True),
    (("vip",), "VIP석", True),
    (("R",), "VIP석", False),
    (("S",), "지정석 R", False),
])
def test_grade_matches(wanted, name, expected):
    assert grade_matches(wanted, name) is expected


# ---------------------------------------------------------------- fetch (HTTP 모킹)

def make_site():
    return NolSite(Settings(), client=httpx.Client(), sleep=lambda: None,
                   now=lambda: datetime(2026, 10, 22, 12, 0, tzinfo=KST))


@respx.mock
def test_fetch_filters_dates_rounds_grades():
    respx.get(PRODUCT_URL.format(code="26015024")).mock(return_value=httpx.Response(200, text=load("nol_goods_page.html")))
    sched = respx.get(SCHEDULES_API).mock(return_value=httpx.Response(200, text=load("nol_schedules.json")))
    remain = respx.get(REMAINING_API).mock(return_value=httpx.Response(200, text=load("nol_remaining_some.json")))

    target = Target(site="nol", goods="26015024", dates=("2027-01-16",), rounds=(1,), grades=("플로어", "R"))
    seats = make_site().fetch(target)

    # 조회 기간을 dates 범위로 좁혀서 요청
    assert sched.calls.last.request.url.params["playStartDate"] == "2027-01-16"
    assert sched.calls.last.request.url.params["playEndDate"] == "2027-01-16"
    # 1월 16일 회차(playSeq 002)만 잔여석 조회
    assert remain.call_count == 1
    assert remain.calls.last.request.url.params["playSeq"] == "002"
    assert [(s.grade, s.remain) for s in seats] == [("플로어석", 2), ("지정석 R", 1)]
    assert seats[0].title == "요네즈 켄시 내한공연"
    assert seats[0].booking_url == "https://nol.yanolja.com/ticket/products/26015024"
    assert seats[0].cancel_close == "2027-01-15 17:00:59"


@respx.mock
def test_fetch_caches_goods_page():
    page = respx.get(PRODUCT_URL.format(code="26015024")).mock(return_value=httpx.Response(200, text=load("nol_goods_page.html")))
    respx.get(SCHEDULES_API).mock(return_value=httpx.Response(200, text=load("nol_schedules.json")))
    respx.get(REMAINING_API).mock(return_value=httpx.Response(200, text=load("nol_remaining_soldout.json")))
    site = make_site()
    target = Target(site="nol", goods="26015024")
    site.fetch(target)
    site.fetch(target)
    assert page.call_count == 1


@respx.mock
def test_fetch_respects_max_rounds():
    respx.get(PRODUCT_URL.format(code="26015024")).mock(return_value=httpx.Response(200, text=load("nol_goods_page.html")))
    respx.get(SCHEDULES_API).mock(return_value=httpx.Response(200, text=load("nol_schedules.json")))
    remain = respx.get(REMAINING_API).mock(return_value=httpx.Response(200, text=load("nol_remaining_soldout.json")))
    site = NolSite(Settings(max_rounds_per_target=2), client=httpx.Client(), sleep=lambda: None,
                   now=lambda: datetime(2026, 10, 22, tzinfo=KST))
    site.fetch(Target(site="nol", goods="26015024"))
    assert remain.call_count == 2


@respx.mock
def test_fetch_skips_finished_show():
    respx.get(PRODUCT_URL.format(code="26015024")).mock(return_value=httpx.Response(200, text=load("nol_goods_page.html")))
    sched = respx.get(SCHEDULES_API)
    site = NolSite(Settings(), client=httpx.Client(), sleep=lambda: None,
                   now=lambda: datetime(2027, 2, 1, tzinfo=KST))
    assert site.fetch(Target(site="nol", goods="26015024")) == []
    assert not sched.called


@respx.mock
def test_http_error_raises_site_error(monkeypatch):
    monkeypatch.setattr("sites.base.time.sleep", lambda s: None)
    respx.get(PRODUCT_URL.format(code="26015024")).mock(return_value=httpx.Response(503))
    with pytest.raises(SiteError, match="503"):
        make_site().fetch(Target(site="nol", goods="26015024"))

"""취소표 알림 봇 진입점.

  python main.py            계속 실행 (3~5분 무작위 간격으로 점검)
  python main.py --once     한 번만 점검하고 종료 (GitHub Actions 용)
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import signal
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import ConfigError, load_config
from monitor import Monitor
from notifier import TelegramNotifier
from state import State

log = logging.getLogger("main")


def setup_logging(log_dir: Path | None) -> None:
    level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(log_dir / "bot.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"))
    for h in handlers:
        h.setFormatter(fmt)
    logging.basicConfig(level=level, handlers=handlers, force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # 요청마다 찍히는 로그는 숨김


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="NOL티켓 취소표 텔레그램 알림 봇")
    p.add_argument("--once", action="store_true", help="한 번만 점검하고 종료")
    p.add_argument("--config", default="config.yaml", help="설정 파일 (기본: config.yaml)")
    p.add_argument("--state", default="state.json", help="상태 파일 (기본: state.json)")
    p.add_argument("--log-dir", default="logs", help="로그 폴더, 빈 값이면 파일 로그 안 남김 (기본: logs)")
    p.add_argument("--interval-override", type=float, metavar="SEC",
                   help="테스트용: 점검 간격을 이 값(초, 최소 10)으로 고정")
    p.add_argument("--focus-budget", type=float, default=0, metavar="SEC",
                   help="--once 와 함께: 집중 감시 시간이면 이 시간(초) 안에서 focus_interval_sec 간격으로 "
                        "여러 번 점검 (Actions 용, 기본 0 = 1회만)")
    return p.parse_args(argv)


def run_once(monitor: Monitor, focus_interval: float, budget: float) -> None:
    """한 번 점검한다. 집중 감시 시간이면 budget 초 안에서 focus_interval 간격으로 반복한다."""
    started = time.monotonic()
    while True:
        cycle_started = time.monotonic()
        monitor.run_cycle()
        reason = monitor.focus_reason()
        next_at = cycle_started + focus_interval
        if not reason or next_at - started > budget:
            return
        log.info("집중 감시(%s): %.0f초 후 다시 점검", reason, next_at - time.monotonic())
        time.sleep(max(0.0, next_at - time.monotonic()))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(Path(args.log_dir) if args.log_dir else None)

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        log.error("설정 오류: %s", e)
        return 1
    monitor = Monitor(cfg, State.load(args.state), TelegramNotifier(cfg.telegram_token, cfg.telegram_chat_id))

    if args.once:
        run_once(monitor, cfg.settings.focus_interval_sec, args.focus_budget)
        return 0

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    s = cfg.settings
    log.info("감시 시작: 대상 %d개, 간격 %s", len(cfg.targets),
             f"{args.interval_override:.0f}초 (테스트)" if args.interval_override
             else f"{s.interval_min_sec:.0f}~{s.interval_max_sec:.0f}초")
    while not stop.is_set():
        started = time.monotonic()
        try:
            monitor.run_cycle()
        except Exception:  # run_cycle 은 예외를 삼키지만, 만일을 대비해 루프는 절대 죽지 않게
            log.exception("점검 중 예상치 못한 오류")
        reason = monitor.focus_reason()
        if args.interval_override:
            interval = max(10.0, args.interval_override)
        elif reason:
            interval = random.uniform(s.focus_interval_sec, s.focus_interval_sec + 10)
            log.info("집중 감시 중 (%s)", reason)
        else:
            interval = random.uniform(s.interval_min_sec, s.interval_max_sec)
        # 간격은 점검 시작 시각 기준 (점검에 걸린 시간만큼 빼고 대기)
        wait = max(0.0, interval - (time.monotonic() - started))
        log.info("다음 점검까지 %.0f초 대기", wait)
        stop.wait(wait)
    log.info("종료합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""state.json: 좌석별 마지막 잔여 수량과 대상별 연속 실패 횟수를 저장해 중복 알림을 막는다."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

VERSION = 1


def seat_key(target_id: str, date: str, round_: int, grade: str) -> str:
    return f"{target_id}|{date}|{round_}|{grade}"


class State:
    def __init__(self, path: str | Path, seats: dict[str, int] | None = None,
                 failures: dict[str, dict] | None = None):
        self.path = Path(path)
        self.seats: dict[str, int] = seats or {}
        # target_id -> {"count": 연속 실패 횟수, "alerted": 오류 알림을 이미 보냈는지}
        self.failures: dict[str, dict] = failures or {}

    @classmethod
    def load(cls, path: str | Path) -> "State":
        path = Path(path)
        if not path.exists():
            return cls(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(path, seats=dict(data.get("seats", {})), failures=dict(data.get("failures", {})))
        except (ValueError, AttributeError) as e:
            # 깨진 파일 때문에 봇이 멈추지 않도록 백업해 두고 새로 시작
            backup = path.with_suffix(".corrupt.json")
            path.replace(backup)
            log.warning("상태 파일이 손상되어 %s 로 옮기고 새로 시작합니다: %s", backup, e)
            return cls(path)

    def save(self) -> None:
        """임시 파일에 쓴 뒤 교체해서, 저장 도중 중단돼도 파일이 깨지지 않게 한다."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": VERSION, "seats": self.seats, "failures": self.failures}
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # ------------------------------------------------------------ 좌석

    def is_newly_available(self, key: str, remain: int) -> bool:
        """이전에 0이었거나 기록이 없던 좌석이 지금 1매 이상이면 True."""
        return remain > 0 and self.seats.get(key, 0) <= 0

    def set_seat(self, key: str, remain: int) -> None:
        self.seats[key] = remain

    def prune_seats(self, active_target_ids: set[str]) -> None:
        """config 에서 빠진 대상의 기록을 지운다."""
        self.seats = {k: v for k, v in self.seats.items() if k.split("|", 1)[0] in active_target_ids}
        self.failures = {k: v for k, v in self.failures.items() if k in active_target_ids}

    # ------------------------------------------------------------ 실패 횟수

    def record_failure(self, target_id: str) -> int:
        f = self.failures.setdefault(target_id, {"count": 0, "alerted": False})
        f["count"] += 1
        return f["count"]

    def failure_alerted(self, target_id: str) -> bool:
        return self.failures.get(target_id, {}).get("alerted", False)

    def mark_failure_alerted(self, target_id: str) -> None:
        self.failures.setdefault(target_id, {"count": 0, "alerted": False})["alerted"] = True

    def record_success(self, target_id: str) -> bool:
        """실패 기록을 지운다. 오류 알림을 보냈던 대상이면 True (복구 알림용)."""
        return self.failures.pop(target_id, {}).get("alerted", False)

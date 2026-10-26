import main


class FakeMonitor:
    def __init__(self, focus):
        self.focus = focus
        self.cycles = 0

    def run_cycle(self):
        self.cycles += 1

    def focus_reason(self):
        return "시간대 23:50-00:20" if self.focus else None


def test_run_once_single_cycle_outside_focus(monkeypatch):
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    m = FakeMonitor(focus=False)
    main.run_once(m, focus_interval=60, budget=120)
    assert m.cycles == 1


def test_run_once_repeats_within_budget_during_focus(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(main.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(main.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    m = FakeMonitor(focus=True)
    main.run_once(m, focus_interval=60, budget=120)
    assert m.cycles == 3          # 0초, 60초, 120초에 점검


def test_run_once_without_budget_is_single_cycle(monkeypatch):
    m = FakeMonitor(focus=True)
    main.run_once(m, focus_interval=60, budget=0)
    assert m.cycles == 1

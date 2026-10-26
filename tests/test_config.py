import pytest

from config import ConfigError, load_config


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")


def test_example_config_loads():
    cfg = load_config("config.example.yaml")
    assert len(cfg.targets) == 2
    t = cfg.targets[0]
    assert t.site == "nol" and t.dates == ("2027-01-16", "2027-01-17") and t.rounds == (1,)
    assert cfg.targets[1].site == "nol" and cfg.targets[1].grades == ()
    assert cfg.settings.request_delay_sec == (2.0, 6.0)


def test_unquoted_yaml_date_becomes_string(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("targets:\n  - goods: '1'\n    dates: [2026-11-15]\n", encoding="utf-8")
    assert load_config(p).targets[0].dates == ("2026-11-15",)


def test_too_short_interval_rejected(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("settings: {interval_min_sec: 10}\ntargets: [{goods: '1'}]\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)


def test_focus_settings_loaded():
    s = load_config("config.example.yaml").settings
    assert s.focus_windows == ("23:50-00:20",) and s.focus_before_cancel_close_min == 60


@pytest.mark.parametrize("body", [
    "settings: {focus_windows: ['25:00-01:00']}\n",
    "settings: {focus_windows: ['2350-0020']}\n",
    "settings: {focus_interval_sec: 30}\n",
])
def test_invalid_focus_settings_rejected(tmp_path, body):
    p = tmp_path / "c.yaml"
    p.write_text(body + "targets: [{goods: '1'}]\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)

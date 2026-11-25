from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

from config.settings import load_env

load_env()

from services.order_manager import OrderManager
from services.risk_guard import RiskGuard
from services.telegram_notifier import TelegramNotifier


def test_risk_guard_missing_ledger():
    """Missing or empty trade ledger must return 0 drawdown and not breach kill-switch."""
    non_existent = "non_existent_ledger_12345.csv"
    dd, peak, total = RiskGuard.calculate_peak_to_trough_drawdown(non_existent)
    assert dd == 0.0
    assert peak == 0.0
    assert total == 0.0

    is_breached, curr_dd, reason = RiskGuard.check_hard_kill_switch(max_drawdown_limit=1185.0, ledger_path=non_existent)
    assert is_breached is False
    assert curr_dd == 0.0
    assert "safe" in reason.lower()


def test_risk_guard_drawdown_calculation_and_breach(tmp_path):
    """Verifies peak-to-trough drawdown calculation and hard kill-switch breach."""
    ledger_file = tmp_path / "trade_ledger.csv"

    # 1. First trade: +$500
    RiskGuard.record_session_to_ledger(
        str(ledger_file),
        {
            "trade_date": "2026-11-20",
            "net_pnl_usd": 500.0,
            "outcome_type": "Type 1: Full Theta Decay",
        },
    )
    dd, peak, total = RiskGuard.calculate_peak_to_trough_drawdown(str(ledger_file))
    assert peak == 500.0
    assert total == 500.0
    assert dd == 0.0

    # 2. Second trade: -$600 -> cum_pnl = -100, peak = 500, dd = 600
    RiskGuard.record_session_to_ledger(
        str(ledger_file),
        {
            "trade_date": "2026-11-21",
            "net_pnl_usd": -600.0,
            "outcome_type": "Type 2: 1 SL Hit",
        },
    )
    dd, peak, total = RiskGuard.calculate_peak_to_trough_drawdown(str(ledger_file))
    assert peak == 500.0
    assert total == -100.0
    assert dd == 600.0

    # Safe because 600 < 1185
    breached, curr_dd, _ = RiskGuard.check_hard_kill_switch(1185.0, str(ledger_file))
    assert breached is False
    assert curr_dd == 600.0

    # 3. Third trade: -$600 -> cum_pnl = -700, peak = 500, dd = 1200 (> 1185!)
    RiskGuard.record_session_to_ledger(
        str(ledger_file),
        {
            "trade_date": "2026-11-22",
            "net_pnl_usd": -600.0,
            "outcome_type": "Type 3: Cost Trailed",
        },
    )
    dd, peak, total = RiskGuard.calculate_peak_to_trough_drawdown(str(ledger_file))
    assert dd == 1200.0

    breached, curr_dd, reason = RiskGuard.check_hard_kill_switch(1185.0, str(ledger_file))
    assert breached is True
    assert curr_dd == 1200.0
    assert "breached" in reason.lower()


def test_order_manager_configurable_multipliers():
    """Verifies that OrderManager accepts custom SL and cost-trail multipliers."""
    mock_client = MagicMock()
    custom_om = OrderManager(mock_client, default_leverage=50, sl_multiplier=2.50, cost_trail_multiplier=1.10)
    assert custom_om.sl_multiplier == 2.50
    assert custom_om.cost_trail_multiplier == 1.10


def test_telegram_crash_alert_formatter():
    """Verifies format_crash_alert formats exception details with short traceback."""
    msg = TelegramNotifier.format_crash_alert(
        job_name="main.py entry",
        timestamp_str="2026-11-24 10:00:19 IST",
        exception_type="TypeError",
        exception_msg="float() argument must be a string or a real number, not 'NoneType'",
        file_line="services/delta_calculator.py:370 in get_10_delta_strikes",
        short_traceback="Traceback:\n  File delta_calculator.py, line 370\nTypeError",
    )
    assert "🚨🚨 *[DELTA BOT CRASH ALERT]* 🚨🚨" in msg
    assert "main.py entry" in msg
    assert "TypeError" in msg
    assert "services/delta_calculator.py:370" in msg
    assert "aborted safely" in msg


@patch("time.sleep", return_value=None)
def test_entry_job_non_blocking_drawdown_warning(_mock_sleep, monkeypatch):
    """Verifies that drawdown breach triggers an advisory alert without blocking entry job execution."""
    import importlib
    from unittest.mock import patch

    entry_job = importlib.import_module("jobs.1_entry_job")

    mock_send = MagicMock()
    mock_strikes = MagicMock(return_value=(None, None))

    with (
        patch.object(
            entry_job.RiskGuard, "check_hard_kill_switch", return_value=(True, 1250.0, "Test DD breach $1250")
        ),
        patch.object(entry_job.TelegramNotifier, "send_message", mock_send),
        patch.object(entry_job.DeltaCalculator, "get_10_delta_strikes", mock_strikes),
        patch.object(entry_job, "ENTRY_WINDOW_SECONDS", 5),
        patch.object(entry_job, "ENTRY_RETRY_INTERVAL_SECONDS", 5),
    ):
        entry_job.run()

    # Verify advisory warning was sent
    assert mock_send.call_count >= 1
    first_call_args, first_call_kwargs = mock_send.call_args_list[0]
    alert_text = first_call_args[0]
    assert "DRAWDOWN ALERT" in alert_text
    assert "1250.00" in alert_text
    assert "Advisory Warning only" in alert_text
    assert first_call_kwargs.get("is_trade_alert") is False

    # Crucially verify get_10_delta_strikes WAS called (execution was NOT blocked/halted!)
    mock_strikes.assert_called_once()

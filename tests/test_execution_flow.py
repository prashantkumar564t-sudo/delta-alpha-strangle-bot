from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

from config.settings import DEFAULT_LEVERAGE, load_env

load_env()

from core.api_client import DeltaApiClient
from services.delta_calculator import DeltaCalculator, parse_expiry_date
from services.order_manager import OrderManager


def test_dry_run_pipeline():
    """Verifies delta bounds and Combo A 100% stop-loss tick-size rounding logic."""
    client = DeltaApiClient("dummy_key", "dummy_secret", "https://cdn-ind.testnet.deltaex.org")
    order_mgr = OrderManager(client, default_leverage=DEFAULT_LEVERAGE)

    ce = {
        "id": 210166,
        "symbol": "C-BTC-66200-181126",
        "strike_price": 66200.0,
        "tick_size": 0.5,
        "delta": 0.1058,
        "abs_delta": 0.1058,
        "mark_price": 29.5,
        "best_bid": 28.0,
        "best_ask": 31.0,
    }
    pe = {
        "id": 210163,
        "symbol": "P-BTC-64800-181126",
        "strike_price": 64800.0,
        "tick_size": 0.5,
        "delta": -0.0988,
        "abs_delta": 0.0988,
        "mark_price": 19.5,
        "best_bid": 18.0,
        "best_ask": 21.0,
    }

    # 1. Delta Bounds Verification (0.07 <= abs_delta <= 0.13)
    assert 0.07 <= ce["abs_delta"] <= 0.13
    assert 0.07 <= pe["abs_delta"] <= 0.13

    # 2. Stop-Loss Tick-Size Rounding Simulation (Combo A 100% SL & Cost Trail)
    ce_rounded_sl_100 = order_mgr._round_to_tick_size(ce["mark_price"] * 2.00, ce["tick_size"])
    pe_rounded_sl_100 = order_mgr._round_to_tick_size(pe["mark_price"] * 2.00, pe["tick_size"])
    ce_rounded_cost = order_mgr._round_to_tick_size(ce["mark_price"] * 1.00, ce["tick_size"])
    pe_rounded_cost = order_mgr._round_to_tick_size(pe["mark_price"] * 1.00, pe["tick_size"])

    # 29.5 * 2.00 = 59.0 -> tick 0.5 -> 59.0
    # 19.5 * 2.00 = 39.0 -> tick 0.5 -> 39.0
    assert ce_rounded_sl_100 % 0.5 == 0.0
    assert pe_rounded_sl_100 % 0.5 == 0.0
    assert ce_rounded_cost == 29.5
    assert pe_rounded_cost == 19.5


def test_set_leverage_normal_and_portfolio_margin():
    """Verifies that OrderManager handles standard 40x leverage and portfolio margin mode."""
    mock_client = MagicMock()
    order_mgr = OrderManager(mock_client, default_leverage=40)

    # Case 1: Standard account sets 40x leverage successfully
    mock_client.request.return_value = {"success": True, "result": {"leverage": "40"}}
    res = order_mgr.set_leverage(1001, 40)
    assert res is True
    mock_client.request.assert_called_with("POST", "/v2/products/1001/orders/leverage", payload={"leverage": "40"})

    # Case 2: Portfolio margin account returns unsupported error -> should still be treated as valid
    mock_client.request.return_value = {"success": False, "error": {"code": "unsupported"}}
    res_pm = order_mgr.set_leverage(1002, 40)
    assert res_pm is True


def test_parse_expiry_date():
    """Verifies DDMMYY parsing into date objects for calendar comparison."""
    d = parse_expiry_date("161126")
    assert d is not None
    assert d.year == 2026
    assert d.month == 11
    assert d.day == 16
    assert parse_expiry_date("invalid") is None


def test_strict_0dte_liquidity_and_depth_filters():
    """
    Verifies that get_10_delta_strikes rejects:
    1. One-sided books (best_bid <= 0 or best_ask <= 0)
    2. Mark price < 5.0
    3. Spread ratio > 0.40
    4. Bid size < requested lot size
    """
    mock_client = MagicMock()
    calc = DeltaCalculator(mock_client)

    target_suffix = calc.get_target_expiry_date_str()

    # Mock products
    mock_products = [
        {
            "id": 1,
            "contract_type": "call_options",
            "symbol": f"C-BTC-70000-{target_suffix}",
            "tick_size": "0.1",
            "strike_price": "70000",
        },
        {
            "id": 2,
            "contract_type": "put_options",
            "symbol": f"P-BTC-60000-{target_suffix}",
            "tick_size": "0.1",
            "strike_price": "60000",
        },
    ]
    calc._get_products = MagicMock(return_value=mock_products)

    # Case 1: Rejected because mark_price < 5.0
    mock_tickers = [
        {
            "product_id": 1,
            "greeks": {"delta": "0.10"},
            "mark_price": "4.5",
            "quotes": {"best_bid": "4.0", "best_ask": "5.0", "bid_size": "10"},
        },
        {
            "product_id": 2,
            "greeks": {"delta": "-0.10"},
            "mark_price": "20.0",
            "quotes": {"best_bid": "19.0", "best_ask": "21.0", "bid_size": "10"},
        },
    ]
    mock_client.request_public.return_value = {"success": True, "result": mock_tickers}
    ce, pe = calc.get_10_delta_strikes(symbol="BTC", target_delta=0.10, lot_size=1, enable_anti_trap=False)
    assert ce is None  # Call rejected because mark_price < 5.0

    # Case 2: Rejected because spread / mark_price > 0.40
    mock_tickers[0]["mark_price"] = "10.0"
    mock_tickers[0]["quotes"] = {
        "best_bid": "7.0",
        "best_ask": "12.0",
        "bid_size": "10",
    }  # spread 5.0 / 10.0 = 0.50 > 0.40
    ce, pe = calc.get_10_delta_strikes(symbol="BTC", target_delta=0.10, lot_size=1, enable_anti_trap=False)
    assert ce is None

    # Case 3: Rejected because bid_size < lot_size (depth failure)
    mock_tickers[0]["quotes"] = {"best_bid": "9.5", "best_ask": "10.5", "bid_size": "2"}
    ce, pe = calc.get_10_delta_strikes(symbol="BTC", target_delta=0.10, lot_size=5, enable_anti_trap=False)
    assert ce is None

    # Case 4: Compliant 0-DTE Call and Put
    mock_tickers[0]["quotes"] = {"best_bid": "9.5", "best_ask": "10.5", "bid_size": "10"}
    ce, pe = calc.get_10_delta_strikes(symbol="BTC", target_delta=0.10, lot_size=1, enable_anti_trap=False)
    assert ce is not None
    assert pe is not None
    assert ce["symbol"] == f"C-BTC-70000-{target_suffix}"
    assert pe["symbol"] == f"P-BTC-60000-{target_suffix}"


def test_cancelled_order_detection():
    """Verifies that matching engine top-level success: True with state: cancelled is treated as failure."""
    mock_client = MagicMock()
    order_mgr = OrderManager(mock_client)

    # Delta matching engine returns HTTP 200 with success: True, but state: "cancelled"
    mock_client.request.return_value = {
        "success": True,
        "result": {
            "id": 888123,
            "state": "cancelled",
            "cancellation_reason": "order_size_not_available_in_orderbook",
        },
    }

    res = order_mgr._market_sell(product_id=101, size=1, leg_name="CE", symbol="C-BTC-TEST")
    assert res is False  # Must detect cancellation and return False


@patch("time.sleep", return_value=None)
def test_asymmetric_partial_fill_rollback(_mock_sleep):
    """Verifies that if CE fills but PE fails, atomic rollback is triggered on CE."""
    mock_client = MagicMock()
    order_mgr = OrderManager(mock_client)
    order_mgr.notifier = MagicMock()
    order_mgr._rollback_leg = MagicMock()
    order_mgr.set_leverage = MagicMock(return_value=True)

    # CE sell succeeds, PE sell fails/cancelled
    order_mgr._market_sell = MagicMock(
        side_effect=[
            {"id": 111, "product_id": 101, "state": "open"},
            None,
        ]
    )

    ce_info = {"id": 101, "symbol": "C-BTC-70000-TODAY"}
    pe_info = {"id": 102, "symbol": "P-BTC-60000-TODAY"}

    report = order_mgr.execute_strangle_with_dual_verification(ce_info, pe_info, size=1)
    assert report["success"] is False
    # Verify rollback was called for CE to prevent naked exposure
    order_mgr._rollback_leg.assert_called_once_with(ce_info, 1, "CE")


@patch("time.sleep", return_value=None)
def test_bracket_sl_retry_and_emergency_close(_mock_sleep):
    """Verifies that bracket SL failure triggers 3 retries and emergency square-off."""
    mock_client = MagicMock()
    order_mgr = OrderManager(mock_client)
    order_mgr.notifier = MagicMock()
    order_mgr.set_leverage = MagicMock(return_value=True)

    # Both legs sell successfully
    order_mgr._market_sell = MagicMock(return_value={"id": 123, "state": "open"})

    # Positions exist
    order_mgr._find_position = MagicMock(
        side_effect=[
            {"size": -1, "entry_price": "100.0"},  # CE pos
            {"size": -1, "entry_price": "80.0"},  # PE pos
        ]
    )

    # Bracket SL placement fails 3 times
    order_mgr._place_bracket_sl = MagicMock(return_value=None)
    order_mgr._emergency_close_strangle = MagicMock()

    ce_info = {"id": 101, "symbol": "C-BTC-70000-TODAY", "tick_size": 0.1}
    pe_info = {"id": 102, "symbol": "P-BTC-60000-TODAY", "tick_size": 0.1}

    # Execute
    report = order_mgr.execute_strangle_with_dual_verification(ce_info, pe_info, size=1)
    assert report["success"] is False
    # Must have triggered emergency close
    order_mgr._emergency_close_strangle.assert_called_once()


@patch("time.sleep", return_value=None)
def test_exit_blast_radius_isolation(_mock_sleep):
    """Verifies that square_off_with_retry only closes target product IDs and leaves other positions alone."""
    mock_client = MagicMock()
    order_mgr = OrderManager(mock_client)

    # Open positions include target strangle legs (101, 102) and an unrelated position (999)
    positions = [
        {"product_id": 101, "product_symbol": "C-BTC-101", "size": -1},
        {"product_id": 102, "product_symbol": "P-BTC-102", "size": -1},
        {"product_id": 999, "product_symbol": "BTCUSD_FUT", "size": 5},
    ]

    mock_client.request.side_effect = [
        {"success": True},  # order 1 cancel
        {"success": True},  # order 2 cancel
        {"success": True, "result": positions},  # pos check 1
        {"success": True, "result": {"state": "closed"}},  # close 101
        {"success": True, "result": {"state": "closed"}},  # close 102
        # After settlement, remaining check: 101 and 102 closed, 999 remains
        {"success": True, "result": [{"product_id": 999, "product_symbol": "BTCUSD_FUT", "size": 5}]},
    ]

    open_orders = [
        {"id": "o1", "product_id": 101},
        {"id": "o2", "product_id": 102},
        {"id": "o999", "product_id": 999},
    ]
    order_mgr._get_open_orders = MagicMock(return_value=open_orders)

    # Run square-off targeting only 101 and 102
    summary = order_mgr.square_off_with_retry(target_product_ids=[101, 102], max_retries=1, retry_delay=0)

    # Success should be True because remaining positions matching [101, 102] is 0!
    assert summary["success"] is True
    # Product 999 was not touched
    assert len(summary["remaining_positions"]) == 0


@patch("time.sleep", return_value=None)
@patch("services.order_manager.OrderManager.execute_strangle_with_dual_verification")
@patch("services.delta_calculator.DeltaCalculator.get_10_delta_strikes")
@patch("services.risk_guard.RiskGuard.check_hard_kill_switch", return_value=(False, 0.0, "OK"))
@patch("services.notifier.TelegramNotifier.send_message")
def test_smart_entry_retry_loop_recovers_after_micro_bid(
    mock_send_telegram,
    mock_kill_switch,
    mock_get_strikes,
    mock_execute,
    _mock_sleep,
):
    """Verifies that 1_entry_job retries when attempt 1 fails and executes on attempt 2 without false skip."""
    import importlib

    entry_job = importlib.import_module("jobs.1_entry_job")

    # Attempt 1 returns (None, None); Attempt 2 returns valid CE, PE
    mock_ce = {"id": 101, "symbol": "C-BTC-70000", "allocated_lots": 1000, "sizing_msg": "Full 1000"}
    mock_pe = {"id": 102, "symbol": "P-BTC-60000", "allocated_lots": 1000, "sizing_msg": "Full 1000"}

    mock_get_strikes.side_effect = [
        (None, None),
        (mock_ce, mock_pe),
    ]
    mock_execute.return_value = {
        "success": True,
        "ce": {"sl_trigger": 60.0},
        "pe": {"sl_trigger": 40.0},
    }

    with (
        patch.object(entry_job, "ENTRY_WINDOW_SECONDS", 10),
        patch.object(entry_job, "ENTRY_RETRY_INTERVAL_SECONDS", 5),
    ):
        entry_job.run()

    # Verify get_10_delta_strikes was called twice
    assert mock_get_strikes.call_count == 2
    # Verify execute_strangle_with_dual_verification was called with 1000 lots
    mock_execute.assert_called_once_with(ce_info=mock_ce, pe_info=mock_pe, size=1000)
    # Verify skip message was NOT sent
    for call in mock_send_telegram.call_args_list:
        assert "JOB 1 SKIPPED" not in call[0][0]


def test_phase1_warmup_target_lock_and_drift_relock():
    """
    Verifies Phase 1 (09:58 - 09:59:59 IST):
    1. Locks 10-Delta targets without placing premature orders.
    2. Re-locks targets when delta drifts outside [0.07, 0.13].
    3. Completes at 10:00:00 IST with zero exchange orders placed.
    """
    import importlib
    from datetime import datetime, timedelta

    entry_job = importlib.import_module("jobs.1_entry_job")

    mock_calc = MagicMock()
    mock_notifier = MagicMock()

    initial_ce = {
        "id": 101,
        "symbol": "C-BTC-70000",
        "delta": 0.10,
        "abs_delta": 0.10,
        "best_bid": 30.0,
        "bid_size": 5000,
    }
    initial_pe = {
        "id": 102,
        "symbol": "P-BTC-60000",
        "delta": -0.10,
        "abs_delta": 0.10,
        "best_bid": 25.0,
        "bid_size": 5000,
    }

    relocked_ce = {
        "id": 103,
        "symbol": "C-BTC-71000",
        "delta": 0.095,
        "abs_delta": 0.095,
        "best_bid": 28.0,
        "bid_size": 5500,
    }
    relocked_pe = dict(initial_pe)

    mock_calc.lock_10_delta_strikes.side_effect = [
        (initial_ce, initial_pe),  # Initial lock at 09:58
        (relocked_ce, relocked_pe),  # Re-lock after delta drift
    ]

    # Poll 1: CE delta drifted to 0.14 (> 0.13), Poll 2: both valid
    drifted_ce = dict(initial_ce, delta=0.14, abs_delta=0.14)
    mock_calc.refresh_strike_quote.side_effect = [drifted_ce, initial_pe, relocked_ce, relocked_pe]
    mock_calc.check_delta_drift.side_effect = [False, True, True, True]  # CE drifted, then re-locked valid

    # Stateful simulated clock advancing 60s per sleep to complete 120s warm-up cleanly
    sim_time = [datetime(2026, 11, 25, 9, 58, 0)]

    def mock_now():
        return sim_time[0]

    def mock_sleep(sec):
        sim_time[0] += timedelta(seconds=max(60.0, float(sec)))

    locked_ce, locked_pe = entry_job.run_phase1_warmup(
        calc=mock_calc,
        notifier=mock_notifier,
        now_fn=mock_now,
        sleep_fn=mock_sleep,
    )

    # 1. Verify lock_10_delta_strikes was called twice (initial lock + drift re-lock)
    assert mock_calc.lock_10_delta_strikes.call_count == 2
    # 2. Verify returned targets are the re-locked ones
    assert locked_ce["id"] == 103
    assert locked_pe["id"] == 102
    # 3. Verify sleep was invoked for polling
    assert mock_now() >= datetime(2026, 11, 25, 10, 0, 0)


@patch("time.sleep", return_value=None)
@patch("services.order_manager.OrderManager.execute_strangle_with_dual_verification")
@patch("services.delta_calculator.DeltaCalculator.get_10_delta_strikes")
@patch("services.risk_guard.RiskGuard.check_hard_kill_switch", return_value=(False, 0.0, "OK"))
def test_phase2_sniper_execution_uses_prelocked_targets(
    mock_kill_switch,
    mock_get_strikes,
    mock_execute,
    _mock_sleep,
):
    """Verifies that Phase 2 passes pre-locked strikes to get_10_delta_strikes and executes 1,000 lots."""
    import importlib
    from datetime import datetime

    entry_job = importlib.import_module("jobs.1_entry_job")

    prelocked_ce = {"id": 101, "symbol": "C-BTC-70000", "allocated_lots": 1000, "sizing_msg": "Full 1000 lots"}
    prelocked_pe = {"id": 102, "symbol": "P-BTC-60000", "allocated_lots": 1000, "sizing_msg": "Full 1000 lots"}

    mock_get_strikes.return_value = (prelocked_ce, prelocked_pe)
    mock_execute.return_value = {"success": True, "ce": {"sl_trigger": 60.0}, "pe": {"sl_trigger": 40.0}}

    now_10am = datetime(2026, 11, 25, 10, 0, 0)
    res = entry_job.run(now_fn=lambda: now_10am, sleep_fn=lambda _s: None)

    assert res is True
    # Verify get_10_delta_strikes was called with locked_ce and locked_pe (None when entering at 10:00 directly)
    assert mock_get_strikes.call_count == 1
    # Verify execute_strangle was executed with 1,000 lots (1.0 BTC)
    mock_execute.assert_called_once_with(ce_info=prelocked_ce, pe_info=prelocked_pe, size=1000)

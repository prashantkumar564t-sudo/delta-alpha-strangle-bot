from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

from config.settings import DEFAULT_LEVERAGE, load_env

load_env()

from services.delta_calculator import DeltaCalculator
from services.order_manager import OrderManager


def test_anti_trap_layer1_max_spread_barrier():
    """Verifies that Layer 1 enforces (Spread / Mark) <= 0.080 (8.0%)."""
    mock_client = MagicMock()
    calc = DeltaCalculator(mock_client)

    # Passing case: Spread = 7.5, Mark = 100.0 -> 7.5% <= 8.0%, Discount = (100 - 98.5)/100 = 1.5% <= 2.0%
    # Provide mock snapshot 2 for Layer 4 so Layer 1 can pass through
    mock_client.request_public.return_value = {
        "success": True,
        "result": {"quotes": {"best_bid": "98.5", "best_ask": "106.0", "bid_size": "600"}},
    }
    ok, _reason, metrics = calc.check_anti_trap_liquidity(
        product_id=1,
        symbol="C-BTC-100-TEST",
        mark_price=100.0,
        best_bid=98.5,
        best_ask=106.0,
        bid_size=600.0,
        order_lots=1,
        sleep_fn=None,
    )
    assert ok is True
    assert metrics["spread_ratio"] <= 0.080

    # Failing case: Spread = 9.0, Mark = 100.0 -> 9.0% > 8.0%, Discount = 1.5% <= 2.0%
    ok, reason, _metrics = calc.check_anti_trap_liquidity(
        product_id=1,
        symbol="C-BTC-100-TEST",
        mark_price=100.0,
        best_bid=98.5,
        best_ask=107.5,
        bid_size=600.0,
        order_lots=1,
        sleep_fn=None,
    )
    assert ok is False
    assert "Layer 1 Failed" in reason


def test_8pct_spread_cap_allows_institutional_2tick_quotes():
    """Verifies that 8.0% spread cap passes 2-tick institutional MM quotes ($2 spread on $30 option = 6.67%)."""
    mock_client = MagicMock()
    calc = DeltaCalculator(mock_client)

    # Mark = 30.0, Bid = 29.5, Ask = 31.5 -> Spread = 2.0 (6.67% <= 8.0%), Discount = 0.5 (1.67% <= 2.0%)
    mock_client.request_public.return_value = {
        "success": True,
        "result": {"quotes": {"best_bid": "29.5", "best_ask": "31.5", "bid_size": "6000"}},
    }
    ok, _reason, metrics = calc.check_anti_trap_liquidity(
        product_id=1,
        symbol="C-BTC-70000-TODAY",
        mark_price=30.0,
        best_bid=29.5,
        best_ask=31.5,
        bid_size=6000.0,
        order_lots=1000,
        sleep_fn=None,
    )
    assert ok is True
    assert round(metrics["spread_ratio"], 4) == round(2.0 / 30.0, 4)
    assert metrics["spread_ratio"] <= 0.080


def test_1_lot_fixed_order_passes_liquidity():
    """Verifies that a 1-lot fixed order with modest depth passes Layer 2 and dynamic sizing cleanly."""
    mock_client = MagicMock()
    calc = DeltaCalculator(mock_client)

    # 1. Dynamic sizing for 1 lot: even with bid_size=10, 10 * 0.20 = 2 >= effective_min (1)
    lots, msg = calc.calculate_liquidity_aware_lots(
        call_bid_size=10.0,
        put_bid_size=15.0,
        target_lots=1,
        min_tradeable_lots=100,
    )
    assert lots == 1
    assert "Full allocation: 1 / 1 lots" in msg

    # 2. Layer 2 anti-trap check for 1 lot order with bid_size=10.0
    mock_client.request_public.return_value = {
        "success": True,
        "result": {"quotes": {"best_bid": "99.0", "best_ask": "101.0", "bid_size": "10.0"}},
    }
    ok, _reason, metrics = calc.check_anti_trap_liquidity(
        product_id=1,
        symbol="C-BTC-100-TEST",
        mark_price=100.0,
        best_bid=99.0,
        best_ask=101.0,
        bid_size=10.0,
        order_lots=1,
        min_tradeable_lots=100,
        sleep_fn=None,
    )
    assert ok is True
    assert metrics["safe_lots"] == 1


def test_anti_trap_layer2_top_bid_depth_cushion():
    """Verifies that Layer 2 enforces Top Bid Lots >= 500 under 20% L1 footprint rule."""
    mock_client = MagicMock()
    calc = DeltaCalculator(mock_client)

    # 1. Passing: 550 lots -> safe_lots = int(550 * 0.20) = 110 >= 100 min floor
    mock_client.request_public.return_value = {
        "success": True,
        "result": {"quotes": {"best_bid": "99.0", "best_ask": "101.0", "bid_size": "550"}},
    }
    ok, _reason, _metrics = calc.check_anti_trap_liquidity(
        product_id=1,
        symbol="C-BTC-100-TEST",
        mark_price=100.0,
        best_bid=99.0,
        best_ask=101.0,
        bid_size=550.0,
        order_lots=1000,
        min_tradeable_lots=100,
        sleep_fn=None,
    )
    assert ok is True

    # 2. Failing: 450 lots (< 500 min floor -> safe_lots = 90 < 100)
    ok, reason, _metrics = calc.check_anti_trap_liquidity(
        product_id=1,
        symbol="C-BTC-100-TEST",
        mark_price=100.0,
        best_bid=99.0,
        best_ask=101.0,
        bid_size=450.0,
        order_lots=1000,
        min_tradeable_lots=100,
        sleep_fn=None,
    )
    assert ok is False
    assert "Layer 2 Failed" in reason


def test_dynamic_liquidity_aware_sizing_full_allocation():
    """Verifies full 1,000 lots allocation when top_bid_lots >= 5,000."""
    calc = DeltaCalculator(MagicMock())

    # Both Call and Put have >= 5,000 lots
    lots, msg = calc.calculate_liquidity_aware_lots(
        call_bid_size=5000.0,
        put_bid_size=6500.0,
        target_lots=1000,
        min_tradeable_lots=100,
    )
    assert lots == 1000
    assert "Full allocation: 1000 / 1000 lots" in msg


def test_dynamic_liquidity_aware_sizing_auto_downsizing():
    """Verifies auto-downsizing to 600 lots when top_bid_lots == 3,000."""
    calc = DeltaCalculator(MagicMock())

    # Limiting leg has 3,000 lots (3,000 * 0.20 = 600 lots)
    lots, msg = calc.calculate_liquidity_aware_lots(
        call_bid_size=3000.0,
        put_bid_size=5000.0,
        target_lots=1000,
        min_tradeable_lots=100,
    )
    assert lots == 600
    assert "Adjusted Lots: 600 / 1000" in msg
    assert "3,000" in msg


def test_dynamic_liquidity_aware_sizing_block_below_min():
    """Verifies blocking when top_bid_lots < 500 (final_lots < 100)."""
    calc = DeltaCalculator(MagicMock())

    # Bid size is 450 lots (450 * 0.20 = 90 < 100 min tradeable lots)
    lots, msg = calc.calculate_liquidity_aware_lots(
        call_bid_size=450.0,
        put_bid_size=4000.0,
        target_lots=1000,
        min_tradeable_lots=100,
    )
    assert lots == 90
    assert lots < 100
    assert "Blocked" in msg
    assert "below MIN_TRADEABLE_LOTS (100)" in msg


def test_anti_trap_layer3_mark_to_bid_discount():
    """Verifies that Layer 3 enforces (Mark - Best Bid) / Mark <= 0.020 (2.0%)."""
    mock_client = MagicMock()
    calc = DeltaCalculator(mock_client)

    mock_client.request_public.return_value = {
        "success": True,
        "result": {"quotes": {"best_bid": "98.5", "best_ask": "101.5", "bid_size": "600"}},
    }

    # Passing case: Mark = 100.0, Bid = 98.5 -> Discount = 1.5% <= 2.0%
    ok, _reason, _metrics = calc.check_anti_trap_liquidity(
        product_id=1,
        symbol="C-BTC-100-TEST",
        mark_price=100.0,
        best_bid=98.5,
        best_ask=101.5,
        bid_size=600.0,
        order_lots=1,
        sleep_fn=None,
    )
    assert ok is True

    # Failing case: Mark = 100.0, Bid = 97.5 -> Discount = 2.5% > 2.0%
    ok, reason, _metrics = calc.check_anti_trap_liquidity(
        product_id=1,
        symbol="C-BTC-100-TEST",
        mark_price=100.0,
        best_bid=97.5,
        best_ask=100.5,
        bid_size=600.0,
        order_lots=1,
        sleep_fn=None,
    )
    assert ok is False
    assert "Layer 3 Failed" in reason


def test_anti_trap_layer4_2snapshot_stability():
    """Verifies that Layer 4 samples twice 2.5s apart and blocks if bid shifts > 1.5% or depth drops > 50%."""
    mock_client = MagicMock()
    calc = DeltaCalculator(mock_client)

    # 1. Passing case: Bid shift = 0.5% (<= 1.5%), size drops by 10% (>= 50% retained)
    mock_client.request_public.return_value = {
        "success": True,
        "result": {"quotes": {"best_bid": "99.5", "best_ask": "101.5", "bid_size": "540"}},
    }
    sleep_mock = MagicMock()
    ok, _reason, _metrics = calc.check_anti_trap_liquidity(
        product_id=1,
        symbol="C-BTC-100-TEST",
        mark_price=100.0,
        best_bid=99.0,
        best_ask=101.5,
        bid_size=600.0,
        order_lots=1,
        sleep_fn=sleep_mock,
    )
    assert ok is True
    sleep_mock.assert_called_once_with(2.5)

    # 2. Failing case: Best bid jumps by 2.5% (> 1.5% limit)
    mock_client.request_public.return_value = {
        "success": True,
        "result": {"quotes": {"best_bid": "101.5", "best_ask": "103.5", "bid_size": "600"}},
    }
    ok, reason, _metrics = calc.check_anti_trap_liquidity(
        product_id=1,
        symbol="C-BTC-100-TEST",
        mark_price=100.0,
        best_bid=99.0,
        best_ask=101.5,
        bid_size=600.0,
        order_lots=1,
        sleep_fn=None,
    )
    assert ok is False
    assert "Layer 4 Failed" in reason
    assert "Best Bid shifted" in reason

    # 3. Failing case: Top bid depth drops from 600 to 200 (66% drop > 50% limit)
    mock_client.request_public.return_value = {
        "success": True,
        "result": {"quotes": {"best_bid": "99.0", "best_ask": "101.5", "bid_size": "200"}},
    }
    ok, reason, _metrics = calc.check_anti_trap_liquidity(
        product_id=1,
        symbol="C-BTC-100-TEST",
        mark_price=100.0,
        best_bid=99.0,
        best_ask=101.5,
        bid_size=600.0,
        order_lots=1,
        sleep_fn=None,
    )
    assert ok is False
    assert "Layer 4 Failed" in reason
    assert "Top Bid depth dropped by > 50%" in reason


def test_anti_trap_blocks_get_10_delta_strikes_with_telegram():
    """Verifies that if chosen strike fails anti-trap, Telegram alert is sent and (None, None) returned."""
    mock_client = MagicMock()
    calc = DeltaCalculator(mock_client)
    calc.notifier = MagicMock()

    target_suffix = calc.get_target_expiry_date_str()
    calc._get_products = MagicMock(
        return_value=[
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
    )

    # Quotes with thin orderbook (< 500 lots)
    mock_tickers = [
        {
            "product_id": 1,
            "greeks": {"delta": "0.10"},
            "mark_price": "50.0",
            "quotes": {"best_bid": "49.5", "best_ask": "50.5", "bid_size": "100"},  # 100 < 500 lots
        },
        {
            "product_id": 2,
            "greeks": {"delta": "-0.10"},
            "mark_price": "40.0",
            "quotes": {"best_bid": "39.5", "best_ask": "40.5", "bid_size": "600"},
        },
    ]
    mock_client.request_public.return_value = {"success": True, "result": mock_tickers}

    ce, pe = calc.get_10_delta_strikes(symbol="BTC", target_delta=0.10, lot_size=1000, enable_anti_trap=True)
    assert ce is None
    assert pe is None
    # Must send Telegram block alert
    calc.notifier.send_message.assert_called_once()
    assert "ANTI-TRAP FILTER BLOCKED" in calc.notifier.send_message.call_args[0][0]


@patch("time.sleep", return_value=None)
def test_order_manager_initial_100pct_sl_setup(_mock_sleep):
    """Verifies that OrderManager attaches 100% stop-loss (entry * 2.00) and arms Combo A trail."""
    mock_client = MagicMock()
    order_mgr = OrderManager(mock_client, default_leverage=DEFAULT_LEVERAGE)
    order_mgr.notifier = MagicMock()
    order_mgr.set_leverage = MagicMock(return_value=True)
    order_mgr._market_sell = MagicMock(return_value={"id": 11, "state": "open"})
    order_mgr._get_open_positions = MagicMock(
        return_value=[
            {"product_id": 101, "size": -1, "entry_price": "100.0"},
            {"product_id": 102, "size": -1, "entry_price": "80.0"},
        ]
    )
    order_mgr._place_bracket_sl_with_retry = MagicMock(side_effect=[901, 902])
    order_mgr._get_open_orders = MagicMock(
        return_value=[
            {"product_id": 101, "bracket_order": True, "stop_price": "200.0"},
            {"product_id": 102, "bracket_order": True, "stop_price": "160.0"},
        ]
    )

    ce_info = {"id": 101, "symbol": "C-BTC-100", "tick_size": 0.1}
    pe_info = {"id": 102, "symbol": "P-BTC-80", "tick_size": 0.1}

    report = order_mgr.execute_strangle_with_dual_verification(ce_info, pe_info, size=1)
    assert report["success"] is True
    # 100% SL: 100.0 * 2.00 = 200.0, 80.0 * 2.00 = 160.0
    assert report["ce"]["sl_trigger"] == 200.0
    assert report["pe"]["sl_trigger"] == 160.0
    assert report["ce"]["sl_mode"] == "100_PERCENT"
    assert report["pe"]["sl_mode"] == "100_PERCENT"
    assert report["strategy"] == "COMBO_A"
    assert report["trail_status"] == "ARMED"
    assert report["ce"]["sl_order_id"] == 901
    assert report["pe"]["sl_order_id"] == 902


def test_trail_surviving_leg_to_cost():
    """Verifies that trail_surviving_leg_to_cost cancels old SL and attaches new SL at exact entry price."""
    mock_client = MagicMock()
    order_mgr = OrderManager(mock_client)
    order_mgr.notifier = MagicMock()
    order_mgr._place_bracket_sl_with_retry = MagicMock(return_value=999)

    surviving_info = {"product_id": 202, "symbol": "P-BTC-60000", "tick_size": 0.5}
    surviving_entry = 55.5  # Cost price

    res = order_mgr.trail_surviving_leg_to_cost(
        stopped_leg_name="CE",
        surviving_leg_info=surviving_info,
        surviving_entry_price=surviving_entry,
        old_sl_order_id=888,
        tick_size=0.5,
    )

    assert res["success"] is True
    assert res["cost_sl_trigger"] == 55.5
    assert res["new_sl_order_id"] == 999
    # Must cancel old SL order 888
    mock_client.request.assert_called_with("DELETE", "/v2/orders", payload={"id": 888, "product_id": 202})
    # Must place bracket SL at exact cost 55.5
    order_mgr._place_bracket_sl_with_retry.assert_called_once_with(
        product_id=202,
        trigger_price=55.5,
        leg_name="P-BTC-60000 (COST_TRAIL)",
        tick_size=0.5,
        max_retries=3,
    )
    # Must send Telegram notification
    order_mgr.notifier.send_message.assert_called_once()
    assert "COMBO A COST-TO-COST TRAIL ACTIVATED" in order_mgr.notifier.send_message.call_args[0][0]


def test_monitor_and_update_cost_trail_when_ce_stopped(tmp_path):
    """Verifies state machine when CE is stopped out: PE is trailed to cost and state.json updated."""
    mock_client = MagicMock()
    order_mgr = OrderManager(mock_client)
    order_mgr.notifier = MagicMock()
    order_mgr._place_bracket_sl_with_retry = MagicMock(return_value=1234)

    # Create dummy state.json
    state_file = tmp_path / "state.json"
    initial_state = {
        "status": "OPEN_PROTECTED",
        "strategy": "COMBO_A",
        "trail_status": "ARMED",
        "ce": {"product_id": 101, "symbol": "C-BTC-70000", "entry_price": 50.0, "sl_order_id": 801, "tick_size": 0.1},
        "pe": {"product_id": 102, "symbol": "P-BTC-60000", "entry_price": 40.0, "sl_order_id": 802, "tick_size": 0.1},
    }
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(initial_state, f)

    # Open positions show CE is gone (stopped), PE is still open
    order_mgr._get_open_positions = MagicMock(
        return_value=[
            {"product_id": 102, "size": -1, "mark_price": "25.0"},
        ]
    )

    res = order_mgr.monitor_and_update_cost_trail(state_file_path=str(state_file))
    assert res["status"] == "TRAILED"
    assert res["stopped_leg"] == "CE"
    assert res["surviving_leg"] == "PE"

    # Verify state file was updated
    with open(state_file, "r", encoding="utf-8") as f:
        updated_state = json.load(f)

    assert updated_state["trail_status"] == "TRAILED"
    assert updated_state["stopped_leg"] == "CE"
    assert updated_state["pe"]["sl_trigger"] == 40.0  # Moved to entry cost!
    assert updated_state["pe"]["sl_mode"] == "COST_TO_COST"
    assert updated_state["pe"]["sl_order_id"] == 1234


def test_monitor_and_update_cost_trail_when_pe_stopped(tmp_path):
    """Verifies state machine when PE is stopped out: CE is trailed to cost and state.json updated."""
    mock_client = MagicMock()
    order_mgr = OrderManager(mock_client)
    order_mgr.notifier = MagicMock()
    order_mgr._place_bracket_sl_with_retry = MagicMock(return_value=5678)

    state_file = tmp_path / "state.json"
    initial_state = {
        "status": "OPEN_PROTECTED",
        "strategy": "COMBO_A",
        "trail_status": "ARMED",
        "ce": {"product_id": 101, "symbol": "C-BTC-70000", "entry_price": 50.0, "sl_order_id": 801, "tick_size": 0.1},
        "pe": {"product_id": 102, "symbol": "P-BTC-60000", "entry_price": 40.0, "sl_order_id": 802, "tick_size": 0.1},
    }
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(initial_state, f)

    # Open positions show PE is gone (stopped), CE is still open
    order_mgr._get_open_positions = MagicMock(
        return_value=[
            {"product_id": 101, "size": -1, "mark_price": "20.0"},
        ]
    )

    res = order_mgr.monitor_and_update_cost_trail(state_file_path=str(state_file))
    assert res["status"] == "TRAILED"
    assert res["stopped_leg"] == "PE"
    assert res["surviving_leg"] == "CE"

    with open(state_file, "r", encoding="utf-8") as f:
        updated_state = json.load(f)

    assert updated_state["trail_status"] == "TRAILED"
    assert updated_state["stopped_leg"] == "PE"
    assert updated_state["ce"]["sl_trigger"] == 50.0  # Moved to entry cost!
    assert updated_state["ce"]["sl_mode"] == "COST_TO_COST"
    assert updated_state["ce"]["sl_order_id"] == 5678


def test_get_10_delta_strikes_without_explicit_lot_size_regression():
    """Regression test: calling get_10_delta_strikes without lot_size must not raise TypeError."""
    mock_client = MagicMock()
    calc = DeltaCalculator(mock_client)

    # Mock products
    mock_products = [
        {
            "id": 1,
            "symbol": "C-BTC-70000-241126",
            "strike_price": "70000",
            "contract_type": "call_options",
            "tick_size": "0.1",
        },
        {
            "id": 2,
            "symbol": "P-BTC-60000-241126",
            "strike_price": "60000",
            "contract_type": "put_options",
            "tick_size": "0.1",
        },
    ]
    calc._get_products = MagicMock(return_value=mock_products)

    # Mock tickers with two-sided liquid book
    mock_client.request_public.return_value = {
        "success": True,
        "result": [
            {
                "product_id": 1,
                "symbol": "C-BTC-70000-241126",
                "greeks": {"delta": "0.10"},
                "mark_price": "100.0",
                "quotes": {"best_bid": "99.0", "best_ask": "101.0", "bid_size": "1500"},
            },
            {
                "product_id": 2,
                "symbol": "P-BTC-60000-241126",
                "greeks": {"delta": "-0.10"},
                "mark_price": "100.0",
                "quotes": {"best_bid": "99.0", "best_ask": "101.0", "bid_size": "1500"},
            },
        ],
    }

    # Call without lot_size parameter (lot_size defaults to None)
    ce, pe = calc.get_10_delta_strikes(
        symbol="BTC",
        target_delta=0.10,
        expiry_date_str="241126",
        target_lots=1000,
        min_tradeable_lots=100,
        enable_anti_trap=False,
    )
    assert ce is not None
    assert ce["symbol"] == "C-BTC-70000-241126"
    assert pe is not None
    assert pe["symbol"] == "P-BTC-60000-241126"

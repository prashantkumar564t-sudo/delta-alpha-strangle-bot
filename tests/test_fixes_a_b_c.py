import os
from unittest.mock import MagicMock, patch

from core.api_client import DeltaApiClient
from services.delta_calculator import DeltaCalculator
from services.order_manager import OrderManager


def test_testnet_relaxation_vs_production_strictness():
    # 1. Testnet client: should allow 200% spread and bypass mark-bid discount (> 2.0%)
    testnet_client = MagicMock(spec=DeltaApiClient)
    testnet_client.base_url = "https://cdn-ind.testnet.deltaex.org"
    testnet_client.request_public.return_value = {
        "success": True,
        "result": {
            "quotes": {"best_bid": 0.50, "best_ask": 55.0, "bid_size": 10000.0},
            "mark_price": 30.0,
        },
    }
    calc_testnet = DeltaCalculator(testnet_client)

    # Quotes typical of Testnet: Bid 0.50, Ask 55.0, Mark 30.0 (spread ratio ~181%, discount ~98%)
    ok, reason, metrics = calc_testnet.check_anti_trap_liquidity(
        product_id=101,
        symbol="C-BTC-60000-TEST",
        mark_price=30.0,
        best_bid=0.50,
        best_ask=55.0,
        bid_size=10000.0,
        order_lots=100,
        min_tradeable_lots=100,
        max_spread_ratio=0.080,
    )
    assert ok is True, f"Expected Testnet quotes to pass relaxed checks, failed with: {reason}"
    assert metrics["spread_ratio"] > 1.0

    # 2. Production client: should strictly reject spread > 8.0% and discount > 2.0%
    prod_client = MagicMock(spec=DeltaApiClient)
    prod_client.base_url = "https://api.india.delta.exchange"
    calc_prod = DeltaCalculator(prod_client)

    # Same quotes on production must be rejected by Layer 1 (spread)
    ok_p1, reason_p1, _ = calc_prod.check_anti_trap_liquidity(
        product_id=101,
        symbol="C-BTC-60000-PROD",
        mark_price=30.0,
        best_bid=0.50,
        best_ask=55.0,
        bid_size=10000.0,
        order_lots=100,
        min_tradeable_lots=100,
        max_spread_ratio=0.080,
    )
    assert ok_p1 is False
    assert "Layer 1 Failed" in reason_p1

    # Production quotes with valid spread (5%) but wide discount (5% > 2.0%) must be rejected by Layer 3
    ok_p2, reason_p2, _ = calc_prod.check_anti_trap_liquidity(
        product_id=102,
        symbol="C-BTC-60000-PROD2",
        mark_price=100.0,
        best_bid=95.0,  # 5% discount > 2%
        best_ask=100.0,  # 5% spread <= 8%
        bid_size=10000.0,
        order_lots=100,
        min_tradeable_lots=100,
        max_spread_ratio=0.080,
    )
    assert ok_p2 is False
    assert "Layer 3 Failed" in reason_p2


def test_lock_10_delta_strikes_testnet_vs_prod_filters():
    mock_products = [
        {"id": 201, "symbol": "C-BTC-60000-251126", "contract_type": "call_options", "strike_price": 60000.0},
        {"id": 202, "symbol": "P-BTC-58000-251126", "contract_type": "put_options", "strike_price": 58000.0},
    ]
    mock_tickers = [
        {
            "product_id": 201,
            "mark_price": 30.0,
            "greeks": {"delta": "0.10"},
            "quotes": {"best_bid": 0.50, "best_ask": 50.0, "bid_size": 5000.0},  # bid=0.50, spread=165%
        },
        {
            "product_id": 202,
            "mark_price": 30.0,
            "greeks": {"delta": "-0.10"},
            "quotes": {"best_bid": 0.50, "best_ask": 50.0, "bid_size": 5000.0},  # bid=0.50, spread=165%
        },
    ]

    # Testnet: Should pass because min_bid=0.10 and allowed_max_spread=5.0
    client_testnet = MagicMock(spec=DeltaApiClient)
    client_testnet.base_url = "https://cdn-ind.testnet.deltaex.org"
    client_testnet.request_public.return_value = {"success": True, "result": mock_tickers}
    calc_testnet = DeltaCalculator(client_testnet)
    calc_testnet._get_products = MagicMock(return_value=mock_products)

    ce_t, pe_t = calc_testnet.lock_10_delta_strikes(symbol="BTC", target_delta=0.10, expiry_date_str="251126")
    assert ce_t is not None and pe_t is not None
    assert ce_t["symbol"] == "C-BTC-60000-251126"
    assert pe_t["symbol"] == "P-BTC-58000-251126"

    # Production: Must reject because best_bid (0.50) < 5.0 and spread > 40%
    client_prod = MagicMock(spec=DeltaApiClient)
    client_prod.base_url = "https://api.india.delta.exchange"
    client_prod.request_public.return_value = {"success": True, "result": mock_tickers}
    calc_prod = DeltaCalculator(client_prod)
    calc_prod._get_products = MagicMock(return_value=mock_products)

    ce_p, pe_p = calc_prod.lock_10_delta_strikes(symbol="BTC", target_delta=0.10, expiry_date_str="251126")
    assert ce_p is None and pe_p is None


def test_cost_trail_accurate_stopped_leg_data():
    mock_client = MagicMock(spec=DeltaApiClient)
    mock_client.request.return_value = {"success": True, "result": {"stop_loss_order": {"id": 99999}}}
    order_mgr = OrderManager(mock_client, sl_multiplier=2.0, cost_trail_multiplier=1.0)
    order_mgr.notifier = MagicMock()
    order_mgr._get_open_orders = MagicMock(return_value=[])

    surviving_leg = {
        "product_id": 101,
        "symbol": "C-BTC-60000-SURVIVOR",
        "entry_price": 25.0,
        "tick_size": 0.1,
    }
    stopped_leg = {
        "product_id": 102,
        "symbol": "P-BTC-58000-STOPPED",
        "entry_price": 45.0,
        "sl_trigger": 90.0,
    }

    with patch("services.telegram_notifier.TelegramNotifier.format_cost_trail_alert") as mock_alert_fmt:
        mock_alert_fmt.return_value = "ALERT_MSG"
        res = order_mgr.trail_surviving_leg_to_cost(
            stopped_leg_name="PE",
            surviving_leg_info=surviving_leg,
            surviving_entry_price=25.0,
            stopped_leg_info=stopped_leg,
        )

        assert res["success"] is True
        mock_alert_fmt.assert_called_once()
        kwargs = mock_alert_fmt.call_args.kwargs
        # Verify stopped leg uses its OWN entry and exit, NOT the surviving leg's 25.0
        assert kwargs["stopped_symbol"] == "P-BTC-58000-STOPPED"
        assert kwargs["stopped_entry"] == 45.0
        assert kwargs["stopped_exit"] == 90.0
        assert kwargs["surviving_entry"] == 25.0


def test_dynamic_env_resolution_at_runtime():
    import importlib

    with patch.dict(os.environ, {"DELTA_BASE_URL": "https://custom.test.endpoint", "DELTA_API_KEY": "KEY_123"}):
        entry_mod = importlib.import_module("jobs.1_entry_job")

        with patch.object(entry_mod, "DeltaApiClient") as mock_client_cls, \
             patch.object(entry_mod, "TelegramNotifier"), \
             patch.object(entry_mod, "DeltaCalculator"), \
             patch.object(entry_mod, "OrderManager"), \
             patch.object(entry_mod, "check_drawdown_warning"), \
             patch.object(entry_mod, "run_phase2_sniper_execution") as mock_phase2:
            mock_phase2.return_value = True
            entry_mod.run()

            # Ensure client was instantiated with dynamic runtime env values
            mock_client_cls.assert_called_once()
            args = mock_client_cls.call_args[0]
            assert args[0] == "KEY_123"
            assert args[2] == "https://custom.test.endpoint"

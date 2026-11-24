from __future__ import annotations

import importlib
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

from core.api_client import DeltaApiClient
from services.order_manager import OrderManager

monitor_job = importlib.import_module("jobs.3_monitor_job")


def test_public_vs_private_routing():
    """Confirms public market data bypasses proxy and private endpoints use proxy."""
    client = DeltaApiClient("dummy_key", "dummy_secret", "https://cdn-ind.testnet.deltaex.org")
    client.request_public = MagicMock(return_value={"success": True, "result": []})
    client.request_private = MagicMock(return_value={"success": True, "result": []})

    # Public endpoints routed to request_public
    client.request("GET", "/v2/products")
    client.request_public.assert_called_with("GET", "/v2/products")

    client.request("GET", "/v2/tickers")
    client.request_public.assert_called_with("GET", "/v2/tickers")

    client.request("GET", "/v2/l2orderbook?symbol=BTC")
    client.request_public.assert_called_with("GET", "/v2/l2orderbook?symbol=BTC")

    client.request("GET", "/v2/indices/BTC")
    client.request_public.assert_called_with("GET", "/v2/indices/BTC")

    # Private endpoints routed to request_private
    client.request("GET", "/v2/positions?underlying_asset_symbol=BTC")
    client.request_private.assert_called_with("GET", "/v2/positions?underlying_asset_symbol=BTC", None)

    client.request("POST", "/v2/orders", payload={"product_id": 123})
    client.request_private.assert_called_with("POST", "/v2/orders", {"product_id": 123})


def test_monitor_job_fast_exit_when_no_state_file(capsys, monkeypatch, tmp_path):
    """When state.json does not exist, monitor fast-exits with 0 API calls."""
    monkeypatch.setattr(monitor_job, "ROOT_DIR", str(tmp_path))

    with patch.object(monitor_job, "DeltaApiClient") as mock_client:
        monitor_job.run()
        mock_client.assert_not_called()

    captured = capsys.readouterr()
    assert "MONITOR FAST-EXIT" in captured.out
    assert "0 proxy calls consumed" in captured.out


def test_monitor_job_fast_exit_when_stale_or_closed(capsys, monkeypatch, tmp_path):
    """When state.json is from yesterday or CLOSED/TRAILED, monitor fast-exits with 0 API calls."""
    state_dir = tmp_path / "data"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "state.json"
    monkeypatch.setattr(monitor_job, "ROOT_DIR", str(tmp_path))

    # 1. Stale trade_date
    stale_state = {
        "trade_date": "2020-01-01",
        "status": "OPEN_PROTECTED",
        "trail_status": "ARMED",
    }
    state_file.write_text(json.dumps(stale_state), encoding="utf-8")

    with patch.object(monitor_job, "DeltaApiClient") as mock_client:
        monitor_job.run()
        mock_client.assert_not_called()

    # 2. Status CLOSED
    today_str = datetime.now().strftime("%Y-%m-%d")
    closed_state = {
        "trade_date": today_str,
        "status": "CLOSED",
        "trail_status": "BOTH_CLOSED",
    }
    state_file.write_text(json.dumps(closed_state), encoding="utf-8")

    with patch.object(monitor_job, "DeltaApiClient") as mock_client:
        monitor_job.run()
        mock_client.assert_not_called()

    # 3. trail_status TRAILED
    trailed_state = {
        "trade_date": today_str,
        "status": "OPEN_PROTECTED",
        "trail_status": "TRAILED",
    }
    state_file.write_text(json.dumps(trailed_state), encoding="utf-8")

    with patch.object(monitor_job, "DeltaApiClient") as mock_client:
        monitor_job.run()
        mock_client.assert_not_called()


def test_order_manager_stale_date_guard(tmp_path):
    """OrderManager.monitor_and_update_cost_trail returns STALE_DATE without API calls."""
    client = MagicMock()
    order_mgr = OrderManager(client)
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "trade_date": "2024-01-01",
                "status": "OPEN_PROTECTED",
                "trail_status": "ARMED",
                "ce": {"product_id": 101},
                "pe": {"product_id": 102},
            }
        ),
        encoding="utf-8",
    )

    res = order_mgr.monitor_and_update_cost_trail(state_file_path=str(state_file))
    assert res.get("status") == "STALE_DATE"
    client.request.assert_not_called()


def test_order_manager_dry_run_simulation():
    """Verifies that OrderManager with dry_run=True places zero orders and dispatches alert."""
    client = MagicMock()
    order_mgr = OrderManager(client, default_leverage=40, dry_run=True)
    order_mgr.notifier = MagicMock()

    ce = {
        "id": 101,
        "symbol": "C-BTC-65000-241126",
        "best_bid": 100.0,
        "mark_price": 105.0,
        "tick_size": 0.5,
    }
    pe = {
        "id": 102,
        "symbol": "P-BTC-58000-241126",
        "best_bid": 90.0,
        "mark_price": 95.0,
        "tick_size": 0.5,
    }

    report = order_mgr.execute_strangle_with_dual_verification(ce, pe, size=500)
    assert report["success"] is True
    assert report["ce"]["entry_price"] == 100.0
    assert report["pe"]["entry_price"] == 90.0
    assert report["ce"]["sl_trigger"] == 200.0
    assert report["pe"]["sl_trigger"] == 180.0
    # Zero API calls made to exchange
    client.request.assert_not_called()
    # Telegram entry notification dispatched
    assert order_mgr.notifier.send_message.called

from __future__ import annotations

from unittest.mock import patch

from services.telegram_notifier import TelegramNotifier


def test_telegram_dual_broadcast_trade_alert():
    """Verifies that trade alerts broadcast to both chat_id and channel_id."""
    notifier = TelegramNotifier(
        bot_token="TEST_BOT_TOKEN",
        chat_id="12345678",
        channel_id="-100987654321",
    )

    with patch.object(notifier, "send_to_chat", return_value=True) as mock_send:
        success = notifier.send_message("Test Trade Alert", is_trade_alert=True)
        assert success is True
        assert mock_send.call_count == 2
        # First call to private chat_id
        assert mock_send.call_args_list[0][0] == ("12345678", "Test Trade Alert")
        # Second call to public channel_id
        assert mock_send.call_args_list[1][0] == ("-100987654321", "Test Trade Alert")


def test_telegram_system_error_isolated_to_chat_id():
    """Verifies that system errors and tracebacks are strictly routed to chat_id, NOT channel_id."""
    notifier = TelegramNotifier(
        bot_token="TEST_BOT_TOKEN",
        chat_id="12345678",
        channel_id="-100987654321",
    )

    with patch.object(notifier, "send_to_chat", return_value=True) as mock_send:
        success = notifier.send_message("CRITICAL ERROR: Exception trace", is_trade_alert=False)
        assert success is True
        assert mock_send.call_count == 1
        # Sent strictly to private chat_id
        assert mock_send.call_args_list[0][0] == ("12345678", "CRITICAL ERROR: Exception trace")

    with patch.object(notifier, "send_to_chat", return_value=True) as mock_send:
        success2 = notifier.send_system_error("EMERGENCY ERROR")
        assert success2 is True
        assert mock_send.call_count == 1
        assert mock_send.call_args_list[0][0] == ("12345678", "EMERGENCY ERROR")


def test_telegram_broadcast_without_channel_id():
    """Verifies that if channel_id is not configured, message routes only to chat_id."""
    notifier = TelegramNotifier(
        bot_token="TEST_BOT_TOKEN",
        chat_id="12345678",
        channel_id="",
    )

    with patch.object(notifier, "send_to_chat", return_value=True) as mock_send:
        success = notifier.send_message("Trade Alert Without Channel", is_trade_alert=True)
        assert success is True
        assert mock_send.call_count == 1
        assert mock_send.call_args_list[0][0] == ("12345678", "Trade Alert Without Channel")


def test_template_1_entry_executed_formatting():
    """Verifies Template 1 format with all required fields (Target, Allocated, Depth, SL, Status)."""
    alert = TelegramNotifier.format_entry_alert(
        date_str="2026-11-23",
        time_str="10:00:00 IST",
        spot_price=98450.00,
        target_lots=1000,
        allocated_lots=600,
        sizing_msg="Downsized to 600 lots (20% L1 Footprint Rule)",
        ce_symbol="C-BTC-102000-231126",
        ce_entry_price=65.50,
        ce_sl=131.00,
        ce_bid_depth=3000,
        ce_spread_pct=1.25,
        pe_symbol="P-BTC-94000-231126",
        pe_entry_price=58.00,
        pe_sl=116.00,
        pe_bid_depth=3200,
        pe_spread_pct=1.40,
        total_credit=74.10,
    )

    assert "🎯 *ALPHA STRANGLE COMBO A — ENTRY EXECUTED*" in alert
    assert "98,450.00" in alert
    assert "1,000 lots" in alert
    assert "600 lots" in alert
    assert "20% L1 Downsizing" in alert
    assert "C-BTC-102000-231126" in alert
    assert "$65.50 USD" in alert
    assert "$131.00 USD" in alert
    assert "3,000 lots" in alert
    assert "1.25%" in alert
    assert "P-BTC-94000-231126" in alert
    assert "$58.00 USD" in alert
    assert "$116.00 USD" in alert
    assert "3,200 lots" in alert
    assert "1.40%" in alert
    assert "+$74.10 USD" in alert
    assert "Cost-to-Cost Trail Armed" in alert


def test_template_2_anti_trap_shield_blocked_formatting():
    """Verifies Template 2 format for each of the 4 Anti-Trap layers."""
    alert_spread = TelegramNotifier.format_anti_trap_blocked_alert(
        date_str="2026-11-23",
        time_str="10:00:02 IST",
        layer_name="Layer 1 — Maximum Bid-Ask Spread Gate (> 3.5%)",
        contract_symbol="C-BTC-102000-231126",
        violation_reason="Spread (4.20%) exceeds maximum allowable threshold (3.5%)",
        mark_price=60.0,
        best_bid=58.0,
        best_ask=60.52,
        bid_size=1500,
    )
    assert "🛡️ *[ANTI-TRAP FILTER BLOCKED — SHIELD ACTIVATED]*" in alert_spread
    assert "Layer 1 — Maximum Bid-Ask Spread Gate" in alert_spread
    assert "C-BTC-102000-231126" in alert_spread
    assert "4.20%" in alert_spread
    assert "Capital Preserved ✅" in alert_spread

    alert_depth = TelegramNotifier.format_anti_trap_blocked_alert(
        date_str="2026-11-23",
        time_str="10:00:02 IST",
        layer_name="Layer 2 — Top Bid Depth Cushion (< 500 contracts)",
        contract_symbol="C-BTC-102000-231126 / P-BTC-94000-231126",
        violation_reason="Safe lots (80) below MIN_TRADEABLE_LOTS (100)",
        mark_price=55.0,
        best_bid=54.0,
        best_ask=55.5,
        bid_size=400,
    )
    assert "Layer 2 — Top Bid Depth Cushion" in alert_depth
    assert "400 lots" in alert_depth


def test_template_3_cost_trail_activated_formatting():
    """Verifies Template 3 format when Cost-to-Cost Trail triggers."""
    alert = TelegramNotifier.format_cost_trail_alert(
        date_str="2026-11-23",
        time_str="14:15:30 IST",
        stopped_leg="CE",
        stopped_symbol="C-BTC-102000-231126",
        stopped_entry=65.50,
        stopped_exit=131.00,
        stopped_pnl_pct=-100.0,
        surviving_leg="PE",
        surviving_symbol="P-BTC-94000-231126",
        surviving_entry=58.00,
        surviving_orig_sl=116.00,
        new_sl_trigger=58.00,
        order_id=987654,
    )

    assert "⚡ *[COMBO A COST-TO-COST TRAIL ACTIVATED]*" in alert
    assert "CE" in alert
    assert "C-BTC-102000-231126" in alert
    assert "$65.50" in alert
    assert "$131.00" in alert
    assert "-100.0%" in alert
    assert "PE" in alert
    assert "P-BTC-94000-231126" in alert
    assert "$116.00 USD" in alert
    assert "$58.00 USD" in alert
    assert "987654" in alert
    assert "Directional Risk Neutralized" in alert


def test_template_4_session_scorecard_formatting():
    """Verifies Template 4 format for 17:15 daily session scorecard."""
    alert = TelegramNotifier.format_session_scorecard(
        date_str="2026-11-23",
        time_str="17:15:00 IST",
        outcome_type="Type 1: Full Theta Decay (Both OTM Expired Worthless)",
        ce_symbol="C-BTC-102000-231126",
        ce_entry=65.50,
        ce_exit=0.50,
        ce_pnl=65.00,
        pe_symbol="P-BTC-94000-231126",
        pe_entry=58.00,
        pe_exit=0.50,
        pe_pnl=57.50,
        allocated_lots=1000,
        gross_pnl_usd=122.50,
        fees_usd=5.14,
        net_pnl_usd=117.36,
        inr_rate=85.0,
    )

    assert "🏁 *DELTA ALPHA STRANGLE — 17:15 IST SESSION SCORECARD*" in alert
    assert "Type 1: Full Theta Decay" in alert
    assert "1,000 lots" in alert
    assert "+$122.50 USD" in alert
    assert "+₹10,412.50" in alert
    assert "-$5.14 USD" in alert
    assert "-₹436.90" in alert
    assert "+$117.36 USD" in alert
    assert "+₹9,975.60" in alert
    assert "FLAT" in alert

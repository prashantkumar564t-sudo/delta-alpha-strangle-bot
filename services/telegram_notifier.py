from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request


class TelegramNotifier:
    """
    Institutional Telegram Alerting Engine.
    Uses pure standard library (urllib.request) with zero external dependencies.

    Dual-Broadcast Routing:
    - TELEGRAM_CHAT_ID: Receives all notifications, trade alerts, and system/error tracebacks.
    - TELEGRAM_CHANNEL_ID (Optional): Receives ONLY clean trade alerts (Entries, Shield Blocks,
      Cost Trail, and 17:15 Scorecards). System errors/tracebacks are strictly isolated to DM.
    """

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
        channel_id: str | None = None,
    ):
        self.bot_token = (bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
        self.chat_id = (chat_id or os.getenv("TELEGRAM_CHAT_ID", "")).strip()
        self.channel_id = (channel_id or os.getenv("TELEGRAM_CHANNEL_ID", "")).strip()

    def send_to_chat(self, target_chat_id: str, text: str) -> bool:
        """Sends a markdown-formatted message to a specific chat or channel ID."""
        if not self.bot_token or not target_chat_id:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": target_chat_id, "text": text, "parse_mode": "Markdown"}

        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                res = json.loads(response.read().decode("utf-8"))
                ok = bool(res.get("ok", False))
                if ok:
                    print(f"[NOTIFIER SUCCESS] Telegram message delivered to {target_chat_id} (HTTP 200, ok=True) ✅")
                return ok
        except Exception as e:
            print(f"[NOTIFIER ERROR] Telegram delivery failed for {target_chat_id}: {e}")
            return False

    def send_message(self, text: str, is_trade_alert: bool = True) -> bool:
        """
        Main messaging entrypoint.
        - If is_trade_alert=True: sends to chat_id and dual-broadcasts to channel_id if configured.
        - If is_trade_alert=False: strictly sends to chat_id (system error/traceback isolation).
        """
        if not self.bot_token or not self.chat_id:
            print("[NOTIFIER WARN] Telegram credentials not configured. Printing to console:")
            print(text)
            return False

        # 1. Primary delivery to private chat / admin DM
        primary_success = self.send_to_chat(self.chat_id, text)

        # 2. Dual-broadcast trade alerts to public/community channel
        if is_trade_alert and self.channel_id:
            self.send_to_chat(self.channel_id, text)

        return primary_success

    def send_system_error(self, text: str) -> bool:
        """Explicitly routes system/error tracebacks strictly to TELEGRAM_CHAT_ID."""
        return self.send_message(text, is_trade_alert=False)

    def send_trade_alert(self, text: str) -> bool:
        """Explicitly broadcasts trade alert to both DM and Channel."""
        return self.send_message(text, is_trade_alert=True)

    # =========================================================================
    # 4 INSTITUTIONAL ALERT FORMATTERS
    # =========================================================================

    @staticmethod
    def format_entry_alert(
        date_str: str,
        time_str: str,
        spot_price: float,
        target_lots: int,
        allocated_lots: int,
        sizing_msg: str,
        ce_symbol: str,
        ce_entry_price: float,
        ce_sl: float,
        ce_bid_depth: float,
        ce_spread_pct: float,
        pe_symbol: str,
        pe_entry_price: float,
        pe_sl: float,
        pe_bid_depth: float,
        pe_spread_pct: float,
        total_credit: float,
    ) -> str:
        """Template 1: Strangle Entry Executed."""
        downsizing_line = (
            f"• ⚡ *20% L1 Downsizing:* `{sizing_msg}`\n"
            if allocated_lots < target_lots or "Downsizing" in sizing_msg
            else "• Sizing Status: `Full Target Allocation ✅`\n"
        )
        total_credit_str = f"+${total_credit:.2f} USD ({allocated_lots * 0.001:.3f} BTC)"

        return (
            "🎯 *ALPHA STRANGLE COMBO A — ENTRY EXECUTED*\n\n"
            f"🕒 *Session:* `{date_str} | {time_str}`\n"
            f"🪙 *BTC Spot:* `${spot_price:,.2f}`\n\n"
            f"📊 *EXECUTION SIZING:*\n"
            f"• Target: `{target_lots:,} lots` ({target_lots * 0.001:.3f} BTC)\n"
            f"• Allocated: `{allocated_lots:,} lots` ({allocated_lots * 0.001:.3f} BTC)\n"
            f"{downsizing_line}\n"
            f"🟢 *CALL LEG (CE):*\n"
            f"• Strike: `{ce_symbol}`\n"
            f"• Sold @: `${ce_entry_price:.2f} USD`\n"
            f"• 100% Bracket SL: `${ce_sl:.2f} USD` (2.0x Entry) ✅\n"
            f"• L1 Top Bid Depth: `{ce_bid_depth:,.0f} lots` | Spread: `{ce_spread_pct:.2f}%`\n\n"
            f"🔴 *PUT LEG (PE):*\n"
            f"• Strike: `{pe_symbol}`\n"
            f"• Sold @: `${pe_entry_price:.2f} USD`\n"
            f"• 100% Bracket SL: `${pe_sl:.2f} USD` (2.0x Entry) ✅\n"
            f"• L1 Top Bid Depth: `{pe_bid_depth:,.0f} lots` | Spread: `{pe_spread_pct:.2f}%`\n\n"
            f"💰 *Total Credit Collected:* `{total_credit_str}`\n"
            "🛡️ *Status:* Positions Protected | Cost-to-Cost Trail Armed (2-min monitor)"
        )

    @staticmethod
    def format_anti_trap_blocked_alert(
        date_str: str,
        time_str: str,
        layer_name: str,
        contract_symbol: str,
        violation_reason: str,
        mark_price: float | None = None,
        best_bid: float | None = None,
        best_ask: float | None = None,
        bid_size: float | None = None,
    ) -> str:
        """Template 2: Entry Blocked / Anti-Trap Shield."""
        mp_str = f"${mark_price:.2f} USD" if mark_price is not None else "N/A"
        bb_str = f"${best_bid:.2f} USD" if best_bid is not None else "N/A"
        ba_str = f"${best_ask:.2f} USD" if best_ask is not None else "N/A"
        depth_str = f"{bid_size:,.0f} lots" if bid_size is not None else "N/A"

        return (
            "🛡️ *[ANTI-TRAP FILTER BLOCKED — SHIELD ACTIVATED]*\n\n"
            f"🕒 *Time:* `{date_str} | {time_str}`\n"
            "🎯 *Asset:* `BTCUSD 0DTE Options`\n"
            f"⚠️ *Triggered Shield:* `{layer_name}`\n"
            f"📋 *Contract:* `{contract_symbol}`\n\n"
            "🔍 *Orderbook Microstructure Metrics:*\n"
            f"• Violation: {violation_reason}\n"
            f"• Mark Price: `{mp_str}`\n"
            f"• Best Bid: `{bb_str}` | Best Ask: `{ba_str}`\n"
            f"• Top Bid Depth: `{depth_str}`\n\n"
            "🛡️ *Verdict:* Entry safely rejected | 0 Trades Placed | Capital Preserved ✅"
        )

    @staticmethod
    def format_cost_trail_alert(
        date_str: str,
        time_str: str,
        stopped_leg: str,
        stopped_symbol: str,
        stopped_entry: float,
        stopped_exit: float,
        stopped_pnl_pct: float,
        surviving_leg: str,
        surviving_symbol: str,
        surviving_entry: float,
        surviving_orig_sl: float,
        new_sl_trigger: float,
        order_id: str | int | None = None,
    ) -> str:
        """Template 3: Cost-to-Cost Trail Activated."""
        return (
            "⚡ *[COMBO A COST-TO-COST TRAIL ACTIVATED]*\n\n"
            f"🕒 *Time:* `{date_str} | {time_str}`\n\n"
            "⚡ *Breached Leg (SL Triggered):*\n"
            f"• Leg: `{stopped_leg}` (`{stopped_symbol}`)\n"
            f"• Entry: `${stopped_entry:.2f}` ➔ Exit: `${stopped_exit:.2f}` ({stopped_pnl_pct:+.1f}%)\n\n"
            "🎯 *Surviving Leg (Protected):*\n"
            f"• Leg: `{surviving_leg}` (`{surviving_symbol}`)\n"
            f"• Original SL: `${surviving_orig_sl:.2f} USD` (2.0x Entry)\n"
            f"🔒 *New SL Trigger:* Moved to exact Entry Cost `${new_sl_trigger:.2f} USD` (1.00x entry)\n"
            f"📋 *Order ID:* `{order_id or 'UPDATED'}`\n\n"
            "🛡️ *Risk Verdict:* Directional Risk Neutralized | Surviving leg guaranteed breakeven or pure profit ✅"
        )

    @staticmethod
    def format_session_scorecard(
        date_str: str,
        time_str: str,
        outcome_type: str,
        ce_symbol: str,
        ce_entry: float,
        ce_exit: float,
        ce_pnl: float,
        pe_symbol: str,
        pe_entry: float,
        pe_exit: float,
        pe_pnl: float,
        allocated_lots: int,
        gross_pnl_usd: float,
        fees_usd: float,
        net_pnl_usd: float,
        inr_rate: float = 85.0,
    ) -> str:
        """Template 4: 17:15 IST Daily Session Scorecard."""
        gross_sign = "+" if gross_pnl_usd >= 0 else ""
        net_sign = "+" if net_pnl_usd >= 0 else ""

        return (
            "🏁 *DELTA ALPHA STRANGLE — 17:15 IST SESSION SCORECARD*\n\n"
            f"🕒 *Session:* `{date_str} | {time_str}`\n"
            f"🏆 *Outcome Classification:*\n`{outcome_type}`\n\n"
            f"📊 *Leg Performance Breakdown ({allocated_lots:,} lots):*\n"
            f"• 🟢 CE (`{ce_symbol}`): `${ce_entry:.2f}` ➔ `${ce_exit:.2f}` | PnL: `${ce_pnl:+.2f} USD`\n"
            f"• 🔴 PE (`{pe_symbol}`): `${pe_entry:.2f}` ➔ `${pe_exit:.2f}` | PnL: `${pe_pnl:+.2f} USD`\n\n"
            "💰 *Financial Realization:*\n"
            f"• Gross PnL: `{gross_sign}${gross_pnl_usd:.2f} USD` (`{gross_sign}₹{gross_pnl_usd * inr_rate:,.2f}`)\n"
            f"• Estimated Delta India Fees (4.13%): `-${fees_usd:.2f} USD` (`-₹{fees_usd * inr_rate:,.2f}`)\n"
            f"• Net Realized PnL: `{net_sign}${net_pnl_usd:.2f} USD` (`{net_sign}₹{net_pnl_usd * inr_rate:,.2f}`)\n\n"
            "🛡️ *Account Status:* FLAT (All positions squared off | 0 overnight risk verified ✅)"
        )

    @staticmethod
    def format_crash_alert(
        job_name: str,
        timestamp_str: str,
        exception_type: str,
        exception_msg: str,
        file_line: str,
        short_traceback: str,
    ) -> str:
        """Crash Alert: Dispatched when unhandled exception occurs in main.py entrypoints."""
        return (
            "🚨🚨 *[DELTA BOT CRASH ALERT]* 🚨🚨\n\n"
            f"🕒 *Timestamp:* `{timestamp_str}`\n"
            f"⚙️ *Job:* `{job_name}`\n"
            f"💥 *Error Type:* `{exception_type}`\n"
            f"📍 *Location:* `{file_line}`\n"
            f"📝 *Message:* `{exception_msg}`\n\n"
            "```text\n"
            f"{short_traceback}\n"
            "```\n"
            "⚡ Bot execution aborted safely (exit code 1)."
        )

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

from config.settings import load_env

load_env()

from core.api_client import DeltaApiClient
from services.notifier import TelegramNotifier
from services.order_manager import OrderManager
from services.risk_guard import RiskGuard

BASE_URL = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
API_KEY = os.getenv("DELTA_API_KEY", "")
API_SECRET = os.getenv("DELTA_API_SECRET", "")


def run():
    print("\n========================================================")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] RUNNING JOB 2: AUTO SQUARE-OFF (05:15 PM)")
    print("========================================================")

    notifier = TelegramNotifier()
    client = DeltaApiClient(API_KEY, API_SECRET, BASE_URL)
    order_mgr = OrderManager(client)

    state_file = os.path.join(ROOT_DIR, "data", "state.json")
    target_pids: list[int] | None = None
    state_data: dict = {}

    # Extract active target product IDs from state.json for blast-radius isolation
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
            if state_data.get("product_ids"):
                target_pids = [int(pid) for pid in state_data["product_ids"]]
            else:
                pids = []
                ce_id = state_data.get("ce", {}).get("product_id")
                pe_id = state_data.get("pe", {}).get("product_id")
                if ce_id:
                    pids.append(int(ce_id))
                if pe_id:
                    pids.append(int(pe_id))
                if pids:
                    target_pids = pids
        except Exception as e:
            print(f"[STATE WARN] Could not read product_ids from state.json: {e}")

    if target_pids:
        print(f"[*] Target Product IDs for Square-Off (Isolated Blast-Radius): {target_pids}")
    else:
        print("[*] No target product IDs found in state.json; scoping to all active BTC strategy positions.")

    # 1. Cleanup pending bracket orders and close active positions with retry
    result = order_mgr.square_off_with_retry(
        target_product_ids=target_pids,
        max_retries=3,
        retry_delay=4,
    )
    is_flat = result.get("success", False)
    closed = result.get("closed_positions", [])
    remaining = result.get("remaining_positions", [])

    # 2. Update state.json
    if os.path.exists(state_file):
        try:
            state_data["status"] = "CLOSED" if is_flat else "FAILED_EXIT"
            state_data["exit_timestamp"] = datetime.now().isoformat()
            state_data["closed_count"] = len(closed)
            state_data["remaining_count"] = len(remaining)
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2)
        except Exception as e:
            print(f"[STATE WARN] Could not update state.json: {e}")

    # 3. Telegram Alert
    if is_flat:
        trade_date = state_data.get("trade_date", datetime.now().strftime("%Y-%m-%d"))
        time_str = datetime.now().strftime("%H:%M:%S IST")
        allocated_lots = int(state_data.get("allocated_lots") or state_data.get("target_lots") or 1000)
        trail_status = state_data.get("trail_status", "ARMED")

        ce_data = state_data.get("ce", {})
        pe_data = state_data.get("pe", {})
        ce_sym = ce_data.get("symbol", "BTC-CE")
        pe_sym = pe_data.get("symbol", "BTC-PE")
        ce_entry = float(ce_data.get("entry_price") or 0.0)
        pe_entry = float(pe_data.get("entry_price") or 0.0)

        # Determine outcome classification
        stopped_leg = state_data.get("stopped_leg")
        if trail_status == "TRAILED":
            outcome_type = f"Type 2: 1 SL Hit ({stopped_leg}) + Runner Survived (Theta Buffer)"
            if stopped_leg == "CE":
                ce_exit = float(ce_data.get("sl_trigger") or (ce_entry * 2.0))
                pe_exit = 0.50
            else:
                pe_exit = float(pe_data.get("sl_trigger") or (pe_entry * 2.0))
                ce_exit = 0.50
        elif trail_status == "BOTH_CLOSED":
            outcome_type = "Type 3: 1 SL Hit + 2nd Trailed to Cost (Breakeven Locked)"
            ce_exit = ce_entry
            pe_exit = pe_entry
        else:
            outcome_type = "Type 1: Full Theta Decay (Both OTM Expired Worthless)"
            ce_exit = 0.50
            pe_exit = 0.50

        ce_pnl = (ce_entry - ce_exit) * allocated_lots * 0.001
        pe_pnl = (pe_entry - pe_exit) * allocated_lots * 0.001
        gross_pnl_usd = ce_pnl + pe_pnl
        turnover_usd = (ce_entry + ce_exit + pe_entry + pe_exit) * allocated_lots * 0.001
        fees_usd = turnover_usd * 0.0413
        net_pnl_usd = gross_pnl_usd - fees_usd

        # Record financial realization to persistent ledger
        ledger_path = os.path.join(ROOT_DIR, "data", "trade_ledger.csv")
        RiskGuard.record_session_to_ledger(
            ledger_path=ledger_path,
            session_record={
                "trade_date": trade_date,
                "entry_time": state_data.get("entry_timestamp", ""),
                "exit_time": datetime.now().isoformat(),
                "outcome_type": outcome_type,
                "ce_symbol": ce_sym,
                "pe_symbol": pe_sym,
                "allocated_lots": allocated_lots,
                "ce_entry": ce_entry,
                "ce_exit": ce_exit,
                "pe_entry": pe_entry,
                "pe_exit": pe_exit,
                "gross_pnl_usd": round(gross_pnl_usd, 4),
                "fees_usd": round(fees_usd, 4),
                "net_pnl_usd": round(net_pnl_usd, 4),
            },
        )

        msg = TelegramNotifier.format_session_scorecard(
            date_str=trade_date,
            time_str=time_str,
            outcome_type=outcome_type,
            ce_symbol=ce_sym,
            ce_entry=ce_entry,
            ce_exit=ce_exit,
            ce_pnl=ce_pnl,
            pe_symbol=pe_sym,
            pe_entry=pe_entry,
            pe_exit=pe_exit,
            pe_pnl=pe_pnl,
            allocated_lots=allocated_lots,
            gross_pnl_usd=gross_pnl_usd,
            fees_usd=fees_usd,
            net_pnl_usd=net_pnl_usd,
            inr_rate=85.0,
        )
        print("\n" + msg + "\n")
        notifier.send_trade_alert(msg)
        print("[FINISHED] Job 2 execution complete.\n")
    else:
        rem_lines = [f"• `{r.get('product_symbol', r.get('product_id'))}`: Size {r.get('size')}" for r in remaining]
        emergency_msg = (
            "🚨🚨 *[CRITICAL EMERGENCY] AUTO SQUARE-OFF FAILED!* 🚨🚨\n\n"
            f"🕒 Time: `{datetime.now().strftime('%H:%M:%S IST')}`\n"
            "⚠️ Positions still remain open after 3 square-off retries!\n"
            "⏰ 17:30 IST Settlement is in 15 minutes!\n\n"
            "*Remaining Open Positions:*\n" + "\n".join(rem_lines) + "\n\n"
            "👉 *PLEASE LOG IN TO DELTA EXCHANGE AND CLOSE MANUALLY IMMEDIATELY!*"
        )
        print("\n" + emergency_msg + "\n")
        notifier.send_system_error(emergency_msg)
        sys.exit(1)


if __name__ == "__main__":
    run()

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

from config.settings import (
    COST_TRAIL_MULTIPLIER,
    DEFAULT_LEVERAGE,
    HARD_KILL_SWITCH_USD,
    MIN_TRADEABLE_LOTS,
    SL_MULTIPLIER,
    TARGET_LOTS,
    load_env,
)

load_env()

from core.api_client import DeltaApiClient
from services.delta_calculator import DeltaCalculator
from services.notifier import TelegramNotifier
from services.order_manager import OrderManager
from services.risk_guard import RiskGuard

BASE_URL = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
API_KEY = os.getenv("DELTA_API_KEY", "")
API_SECRET = os.getenv("DELTA_API_SECRET", "")


def run():
    print("\n========================================================")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] RUNNING JOB 1: ENTRY & BRACKET SL")
    print("========================================================")

    notifier = TelegramNotifier()
    client = DeltaApiClient(API_KEY, API_SECRET, BASE_URL)
    calc = DeltaCalculator(client)
    order_mgr = OrderManager(
        client,
        default_leverage=DEFAULT_LEVERAGE,
        sl_multiplier=SL_MULTIPLIER,
        cost_trail_multiplier=COST_TRAIL_MULTIPLIER,
    )

    # ------------------------------------------------------------------
    # PRE-FLIGHT RISK GATE: HARD STRATEGY KILL-SWITCH ($1,185 MDD Barrier)
    # ------------------------------------------------------------------
    ledger_path = os.path.join(ROOT_DIR, "data", "trade_ledger.csv")
    is_breached, current_dd, reason = RiskGuard.check_hard_kill_switch(
        max_drawdown_limit=HARD_KILL_SWITCH_USD,
        ledger_path=ledger_path,
    )
    if is_breached:
        kill_alert = (
            "🚨🚨 *[HARD STRATEGY KILL-SWITCH TRIGGERED]* 🚨🚨\n\n"
            f"🕒 *Timestamp:* `{datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}`\n"
            f"🛑 *Live Drawdown:* `-${current_dd:.2f} USD` (Limit: `-${HARD_KILL_SWITCH_USD:.2f} USD`)\n"
            "🛡️ *Action:* 10:00 AM Entry HALTED automatically to preserve capital.\n"
            f"📋 *Details:* {reason}\n\n"
            "👉 *Please review strategy performance ledger before resuming live execution.*"
        )
        print(f"\n[KILL-SWITCH HALT] {reason}")
        print(kill_alert)
        notifier.send_system_error(kill_alert)
        return

    target_lots = TARGET_LOTS
    min_tradeable_lots = MIN_TRADEABLE_LOTS
    print(
        f"\n[1/3] Fetching 0-DTE 10-Delta Strikes (Target: {target_lots} lots, Min Floor: {min_tradeable_lots} lots)..."
    )
    ce, pe = calc.get_10_delta_strikes(
        symbol="BTC",
        target_delta=0.10,
        target_lots=target_lots,
        min_tradeable_lots=min_tradeable_lots,
    )

    if not ce or not pe:
        msg = "⚠️ [JOB 1 SKIPPED] Today's 0-DTE 10-Delta strikes not available or failed spread/depth filters. Skipping entry safely."
        print(msg)
        notifier.send_message(msg)
        return

    final_lots = int(ce.get("allocated_lots", target_lots))
    sizing_msg = ce.get("sizing_msg", f"Allocated: {final_lots} lots")
    print(f"Selected CE: {ce['symbol']} (ID: {ce['id']})")
    print(f"Selected PE: {pe['symbol']} (ID: {pe['id']})")
    print(f"[DYNAMIC SIZING] {sizing_msg}")

    print(
        f"\n[2/3] Setting {DEFAULT_LEVERAGE}x Leverage + Executing Market Sell (Size: {final_lots} lots) + 100% Combo A Bracket SL..."
    )
    report = order_mgr.execute_strangle_with_dual_verification(ce_info=ce, pe_info=pe, size=final_lots)

    if not report.get("success"):
        print("\n❌ Entry or Bracket SL execution failed.")
        sys.exit(1)

    print("\n[3/3] Saving active state to data/state.json...")
    state_file = os.path.join(ROOT_DIR, "data", "state.json")
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    state_data = {
        "trade_date": datetime.now().strftime("%Y-%m-%d"),
        "entry_timestamp": datetime.now().isoformat(),
        "strategy": "COMBO_A",
        "target_lots": target_lots,
        "allocated_lots": final_lots,
        "sizing_msg": sizing_msg,
        "sl_multiplier": SL_MULTIPLIER,
        "cost_trail_multiplier": COST_TRAIL_MULTIPLIER,
        "trail_status": "ARMED",
        "product_ids": [ce["id"], pe["id"]],
        "ce": report["ce"],
        "pe": report["pe"],
        "status": "OPEN_PROTECTED",
    }

    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=2)

    print(f"[SUCCESS] State saved to {state_file}")
    print("[FINISHED] Job 1 execution complete.\n")


if __name__ == "__main__":
    run()

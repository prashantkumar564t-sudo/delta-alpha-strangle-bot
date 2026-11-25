from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from typing import Any

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

from config.settings import (
    COST_TRAIL_MULTIPLIER,
    DEFAULT_LEVERAGE,
    DRY_RUN,
    ENTRY_RETRY_INTERVAL_SECONDS,
    ENTRY_WINDOW_SECONDS,
    EXECUTION_HOUR,
    EXECUTION_MINUTE,
    HARD_KILL_SWITCH_USD,
    MAX_SPREAD_RATIO,
    MIN_TRADEABLE_LOTS,
    SL_MULTIPLIER,
    TARGET_LOTS,
    WARMUP_POLL_INTERVAL_SECONDS,
    WARMUP_START_HOUR,
    WARMUP_START_MINUTE,
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


def check_drawdown_warning(notifier: TelegramNotifier) -> tuple[bool, float, str]:
    """Pre-flight risk check: emits non-blocking advisory alert if MDD threshold is breached."""
    ledger_path = os.path.join(ROOT_DIR, "data", "trade_ledger.csv")
    is_breached, current_dd, reason = RiskGuard.check_hard_kill_switch(
        max_drawdown_limit=HARD_KILL_SWITCH_USD,
        ledger_path=ledger_path,
    )
    if is_breached:
        warning_alert = (
            "⚠️ *DRAWDOWN ALERT: Account drawdown exceeded threshold — strategy needs attention*\n\n"
            f"🕒 *Timestamp:* `{datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}`\n"
            f"🛑 *Live Drawdown:* `-${current_dd:.2f} USD` (Threshold: `-${HARD_KILL_SWITCH_USD:.2f} USD`)\n"
            "ℹ️ *Status:* Advisory Warning only — Entry proceeding as scheduled.\n"
            f"📋 *Details:* {reason}"
        )
        print(f"\n[DRAWDOWN WARNING] {reason}")
        print(warning_alert)
        notifier.send_message(warning_alert, is_trade_alert=False)
    return is_breached, current_dd, reason


def run_phase1_warmup(
    calc: DeltaCalculator,
    notifier: TelegramNotifier,
    now_fn: Any = datetime.now,
    sleep_fn: Any = time.sleep,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """
    Phase 1: 09:58:00 to 09:59:59 IST — Warm-Up & Target Lock
    - Scans 0DTE option chain, locks 0.10 Delta CE & PE strikes in memory.
    - Polls locked strikes every 5s until 10:00:00 IST (zero orders placed).
    - Dynamically re-locks if delta drifts outside [0.07, 0.13].
    """
    print("\n========================================================")
    print(f"[{now_fn().strftime('%Y-%m-%d %H:%M:%S')}] PHASE 1: 09:58 IST WARM-UP & TARGET LOCK")
    print("========================================================")

    now = now_fn()
    exec_target = now.replace(hour=EXECUTION_HOUR, minute=EXECUTION_MINUTE, second=0, microsecond=0)

    locked_ce, locked_pe = calc.lock_10_delta_strikes(symbol="BTC", target_delta=0.10)
    if not locked_ce or not locked_pe:
        print("[PHASE 1 WARNING] Could not lock 10-Delta targets during warm-up. Will retry in Phase 2.")
        return None, None

    print(
        f"🔒 [PHASE 1 LOCKED] CE: {locked_ce['symbol']} (Delta: {locked_ce['delta']:.4f}) | "
        f"PE: {locked_pe['symbol']} (Delta: {locked_pe['delta']:.4f})"
    )

    while now_fn() < exec_target:
        remaining_sec = (exec_target - now_fn()).total_seconds()
        if remaining_sec <= 0:
            break

        sleep_time = min(float(WARMUP_POLL_INTERVAL_SECONDS), remaining_sec)
        sleep_fn(sleep_time)

        # Poll locked strikes & check drift
        updated_ce = calc.refresh_strike_quote(locked_ce)
        updated_pe = calc.refresh_strike_quote(locked_pe)

        if updated_ce:
            locked_ce = updated_ce
        if updated_pe:
            locked_pe = updated_pe

        ce_drifted = not calc.check_delta_drift(locked_ce)
        pe_drifted = not calc.check_delta_drift(locked_pe)

        if ce_drifted or pe_drifted:
            print(
                f"⚠️ [PHASE 1 DRIFT] Delta drifted outside [0.07, 0.13] "
                f"(CE: {locked_ce.get('delta')}, PE: {locked_pe.get('delta')}). Re-locking..."
            )
            new_ce, new_pe = calc.lock_10_delta_strikes(symbol="BTC", target_delta=0.10)
            if new_ce and new_pe:
                locked_ce, locked_pe = new_ce, new_pe
                print(
                    f"🔒 [PHASE 1 RE-LOCKED] New CE: {locked_ce['symbol']} (Delta: {locked_ce['delta']:.4f}) | "
                    f"New PE: {locked_pe['symbol']} (Delta: {locked_pe['delta']:.4f})"
                )
        else:
            print(
                f"[PHASE 1 TRACKING | {now_fn().strftime('%H:%M:%S')}] "
                f"CE: {locked_ce['symbol']} (Delta: {locked_ce['delta']:.4f}, Bid: {locked_ce['best_bid']}, Size: {locked_ce['bid_size']:.0f}) | "
                f"PE: {locked_pe['symbol']} (Delta: {locked_pe['delta']:.4f}, Bid: {locked_pe['best_bid']}, Size: {locked_pe['bid_size']:.0f})"
            )

    print(f"[{now_fn().strftime('%Y-%m-%d %H:%M:%S')}] Phase 1 complete. Handing over locked strikes to Phase 2.\n")
    return locked_ce, locked_pe


def run_phase2_sniper_execution(
    calc: DeltaCalculator,
    order_mgr: OrderManager,
    notifier: TelegramNotifier,
    locked_ce: dict[str, Any] | None = None,
    locked_pe: dict[str, Any] | None = None,
    now_fn: Any = datetime.now,
    sleep_fn: Any = time.sleep,
) -> bool:
    """
    Phase 2: 10:00:00 to 10:02:00 IST — Sniper Liquidity Check & Execution
    - Uses pre-locked strikes (skips chain scan) or locks strikes if not provided.
    - Polls locked L1 orderbooks every 5s (up to 120s / 24 attempts) for Spread <= 8.0%, L1 Depth >= 5,000 lots, etc.
    - Executes Market Sell 1,000 Lots (1.0 BTC) + 100% SL immediately on first qualifying poll.
    """
    print("========================================================")
    print(f"[{now_fn().strftime('%Y-%m-%d %H:%M:%S')}] PHASE 2: 10:00 IST SNIPER LIQUIDITY CHECK & EXECUTION")
    print("========================================================")

    target_lots = TARGET_LOTS
    min_tradeable_lots = MIN_TRADEABLE_LOTS
    max_window_sec = ENTRY_WINDOW_SECONDS
    poll_interval = ENTRY_RETRY_INTERVAL_SECONDS
    max_attempts = max(1, max_window_sec // poll_interval)

    print(
        f"\n[1/3] Starting Smart {max_window_sec}s Sniper Window "
        f"(Target: {target_lots} lots [1.0 BTC], Min Floor: {min_tradeable_lots} lots, Max Spread: {MAX_SPREAD_RATIO:.1%}, "
        f"Polling every {poll_interval}s, max {max_attempts} attempts)..."
    )

    ce, pe = None, None
    start_time = time.time()
    for attempt in range(1, max_attempts + 1):
        elapsed_sec = int(time.time() - start_time)
        print(f"\n[POLL ATTEMPT {attempt}/{max_attempts} | Elapsed: {elapsed_sec}s / {max_window_sec}s]")

        is_last_attempt = attempt == max_attempts

        ce, pe = calc.get_10_delta_strikes(
            symbol="BTC",
            target_delta=0.10,
            target_lots=target_lots,
            min_tradeable_lots=min_tradeable_lots,
            enable_anti_trap=True,
            max_spread_ratio=MAX_SPREAD_RATIO,
            suppress_block_alert=(not is_last_attempt),
            locked_ce=locked_ce,
            locked_pe=locked_pe,
        )

        if ce and pe:
            print(
                f"✅ [SNIPER EXECUTION LOCKED] Qualifying 10-Delta strikes cleared all liquidity barriers on attempt {attempt} (Elapsed: {elapsed_sec}s)!"
            )
            break

        if not is_last_attempt:
            sleep_fn(poll_interval)

    if not ce or not pe:
        msg = (
            f"⚠️ [JOB 1 SKIPPED] Today's 0-DTE 10-Delta strikes not available or failed spread/depth filters "
            f"after {max_attempts} attempts across {max_window_sec}s window. Skipping entry safely."
        )
        print(f"\n{msg}")
        notifier.send_message(msg)
        return False

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

    if DRY_RUN:
        print(
            "\n[DRY RUN ACTIVE] Zero exchange orders executed. Skipping data/state.json persistence so tomorrow's session starts completely fresh."
        )
    else:
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
    return True


def run(now_fn: Any = datetime.now, sleep_fn: Any = time.sleep) -> bool:
    print("\n========================================================")
    print(f"[{now_fn().strftime('%Y-%m-%d %H:%M:%S')}] RUNNING JOB 1: 2-PHASE ENTRY & BRACKET SL")
    print("========================================================")

    notifier = TelegramNotifier()
    client = DeltaApiClient(API_KEY, API_SECRET, BASE_URL)
    calc = DeltaCalculator(client)
    order_mgr = OrderManager(
        client,
        default_leverage=DEFAULT_LEVERAGE,
        sl_multiplier=SL_MULTIPLIER,
        cost_trail_multiplier=COST_TRAIL_MULTIPLIER,
        dry_run=DRY_RUN,
    )

    # 1. Pre-flight non-blocking drawdown risk check
    check_drawdown_warning(notifier)

    # 2. Timing Gate: Determine Phase 1 vs Phase 2
    now = now_fn()
    exec_target = now.replace(hour=EXECUTION_HOUR, minute=EXECUTION_MINUTE, second=0, microsecond=0)
    warmup_target = now.replace(hour=WARMUP_START_HOUR, minute=WARMUP_START_MINUTE, second=0, microsecond=0)

    locked_ce, locked_pe = None, None
    if warmup_target <= now < exec_target:
        # Phase 1: 09:58:00 to 09:59:59 IST
        locked_ce, locked_pe = run_phase1_warmup(calc, notifier, now_fn=now_fn, sleep_fn=sleep_fn)

    # Phase 2: 10:00:00 to 10:02:00 IST (Sniper Liquidity Check & Execution)
    return run_phase2_sniper_execution(
        calc, order_mgr, notifier, locked_ce=locked_ce, locked_pe=locked_pe, now_fn=now_fn, sleep_fn=sleep_fn
    )


if __name__ == "__main__":
    run()

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
    FULL_TARGET_WAIT_SECONDS,
    HARD_KILL_SWITCH_USD,
    MAX_SPREAD_RATIO,
    MIN_FALLBACK_LOTS,
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


def _send_phase1_telemetry(
    notifier: TelegramNotifier,
    ce: dict[str, Any],
    pe: dict[str, Any],
    now_fn: Any,
    target_lots: int = TARGET_LOTS,
    is_relock: bool = False,
) -> None:
    """Helper to dispatch Phase 1 target-lock telemetry to Telegram (DM only)."""
    ce_mark = float(ce.get("mark_price") or 1.0)
    ce_ask = float(ce.get("best_ask") or 0.0)
    ce_bid = float(ce.get("best_bid") or 0.0)
    ce_spread_pct = ((ce_ask - ce_bid) / ce_mark * 100.0) if ce_mark > 0 and ce_ask > 0 else 0.0

    pe_mark = float(pe.get("mark_price") or 1.0)
    pe_ask = float(pe.get("best_ask") or 0.0)
    pe_bid = float(pe.get("best_bid") or 0.0)
    pe_spread_pct = ((pe_ask - pe_bid) / pe_mark * 100.0) if pe_mark > 0 and pe_ask > 0 else 0.0

    alert_msg = TelegramNotifier.format_phase1_warmup_alert(
        date_str=now_fn().strftime("%Y-%m-%d"),
        time_str=now_fn().strftime("%H:%M:%S"),
        ce_symbol=ce.get("symbol", "N/A"),
        ce_strike=float(ce.get("strike_price") or 0.0),
        ce_delta=float(ce.get("delta") or 0.0),
        ce_mark=ce_mark,
        ce_bid_depth=float(ce.get("bid_size") or 0.0),
        ce_spread_pct=ce_spread_pct,
        pe_symbol=pe.get("symbol", "N/A"),
        pe_strike=float(pe.get("strike_price") or 0.0),
        pe_delta=float(pe.get("delta") or 0.0),
        pe_mark=pe_mark,
        pe_bid_depth=float(pe.get("bid_size") or 0.0),
        pe_spread_pct=pe_spread_pct,
        target_lots=target_lots,
        is_relock=is_relock,
    )
    print("\n" + alert_msg + "\n")
    notifier.send_message(alert_msg, is_trade_alert=False)


def run_phase1_warmup(
    calc: DeltaCalculator,
    notifier: TelegramNotifier,
    now_fn: Any = datetime.now,
    sleep_fn: Any = time.sleep,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """
    Phase 1: 09:58:00 to 09:59:59 IST — Warm-Up & Target Lock
    - Scans 0DTE option chain, locks 0.10 Delta CE & PE strikes in memory.
    - Sends Telegram pre-warm telemetry alert.
    - Polls locked strikes every 5s until 10:00:00 IST (zero orders placed).
    - Dynamically re-locks and alerts if delta drifts outside [0.07, 0.13].
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
    _send_phase1_telemetry(notifier, locked_ce, locked_pe, now_fn, is_relock=False)

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
                _send_phase1_telemetry(notifier, locked_ce, locked_pe, now_fn, is_relock=True)
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
    full_wait_sec = FULL_TARGET_WAIT_SECONDS
    min_fallback = MIN_FALLBACK_LOTS
    max_attempts = max(1, max_window_sec // poll_interval)

    print(
        f"\n[1/3] Starting 2-Stage Sniper Window ({max_window_sec}s total): "
        f"Stage 1 (0-{full_wait_sec}s: Full {target_lots} lots / 1.0 BTC) -> "
        f"Stage 2 ({full_wait_sec}-{max_window_sec}s: Dynamic Equal-Leg Fallback >= {min_fallback} lots) | "
        f"Max Spread: {MAX_SPREAD_RATIO:.1%}, Polling every {poll_interval}s, max {max_attempts} attempts..."
    )

    ce, pe = None, None
    start_time = time.time()
    for attempt in range(1, max_attempts + 1):
        elapsed_sec = int(time.time() - start_time)
        is_stage1 = elapsed_sec < full_wait_sec
        stage_desc = (
            f"STAGE 1 (FULL {target_lots} LOTS)" if is_stage1 else f"STAGE 2 (DYNAMIC FALLBACK >= {min_fallback} LOTS)"
        )
        print(f"\n[POLL ATTEMPT {attempt}/{max_attempts} | Elapsed: {elapsed_sec}s / {max_window_sec}s | {stage_desc}]")

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
            require_full_target=is_stage1,
            min_fallback_lots=min_fallback,
        )

        if ce and pe:
            final_lots = int(ce.get("allocated_lots", target_lots))
            exec_mode = (
                f"FULL ALLOCATION ({final_lots} lots / 1.0 BTC)"
                if final_lots >= target_lots
                else f"STAGE 2 DYNAMIC EQUAL-LEG FALLBACK ({final_lots} lots)"
            )
            print(
                f"✅ [SNIPER EXECUTION LOCKED] Qualifying 10-Delta strikes cleared all liquidity barriers on attempt {attempt} "
                f"(Elapsed: {elapsed_sec}s | Mode: {exec_mode})!"
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
    report = order_mgr.execute_strangle_with_dual_verification(
        ce_info=ce, pe_info=pe, size=final_lots, fill_delay_sec=elapsed_sec
    )

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
            "fill_delay_seconds": elapsed_sec,
            "stage": "STAGE_1_FULL" if final_lots >= target_lots else "STAGE_2_DYNAMIC_FALLBACK",
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
    load_env()
    base_url = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
    api_key = os.getenv("DELTA_API_KEY", "")
    api_secret = os.getenv("DELTA_API_SECRET", "")

    print("\n========================================================")
    print(f"[{now_fn().strftime('%Y-%m-%d %H:%M:%S')}] RUNNING JOB 1: 2-PHASE ENTRY & BRACKET SL")
    print("========================================================")

    notifier = TelegramNotifier()
    client = DeltaApiClient(api_key, api_secret, base_url)
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

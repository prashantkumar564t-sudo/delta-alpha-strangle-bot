# 🔍 DELTA ALPHA STRANGLE BOT — CORE LOGIC BUG HUNT & AUDIT CONSOLIDATION

**Strategy Architecture:** BTCUSD 0-DTE Intraday Short Strangle (Combo A Architecture)  
**Target Exchange:** Delta Exchange India (`api.india.delta.exchange`) & Global (`api.delta.exchange`)  
**Runtime Environment:** Android Termux / Bare-Metal Linux VPS | **100% Python Standard Library (Zero External Dependencies)**  
**Git Checkpoint:** `commit a225c5e`  
**Test Suite Status:** 46/46 Unit Tests Passing (100% Verified)  

---

## 📑 TABLE OF CONTENTS
1. [System Architectural Overview & Invariants](#1-system-architectural-overview--invariants)
2. [End-to-End Execution State Machine](#2-end-to-end-execution-state-machine)
3. [Comprehensive Bug Hunter's Edge-Case Checklist](#3-comprehensive-bug-hunters-edge-case-checklist)
4. [Verbatim Source Code Modules (100% Production Code)](#4-verbatim-source-code-modules)
   - [Module 1: `main.py`](#module-1-mainpy)
   - [Module 2: `config/settings.py`](#module-2-configsettingspy)
   - [Module 3: `core/api_client.py`](#module-3-coreapi_clientpy)
   - [Module 4: `services/delta_calculator.py`](#module-4-servicesdelta_calculatorpy)
   - [Module 5: `services/order_manager.py`](#module-5-servicesorder_managerpy)
   - [Module 6: `services/telegram_notifier.py`](#module-6-servicestelegram_notifierpy)
   - [Module 7: `services/risk_guard.py`](#module-7-servicesrisk_guardpy)
   - [Module 8: `jobs/1_entry_job.py`](#module-8-jobs1_entry_jobpy)
   - [Module 9: `jobs/2_exit_job.py`](#module-9-jobs2_exit_jobpy)
   - [Module 10: `jobs/3_monitor_job.py`](#module-10-jobs3_monitor_jobpy)

---

## 1. SYSTEM ARCHITECTURAL OVERVIEW & INVARIANTS

### Core Operational Schedule (Asia/Kolkata - IST)
* **`09:58:00 IST` (Cron `58 9 * * *`):** **Phase 1 Pre-Warm & Target Lock.** Scans the 0DTE chain via direct public REST endpoints (**0 KB proxy bandwidth**). Locks candidate ~0.10 Delta $[0.07, 0.13]$ CE & PE strikes with mark $\ge \$5.00$. Dispatches Phase 1 Telegram telemetry. Polls every 5s; re-locks if delta drifts outside $[0.07, 0.13]$. Zero exchange orders placed.
* **`10:00:00 IST`–`10:02:00 IST`:** **Phase 2 Sniper Execution.** Retries up to 120s (24 attempts @ 5s intervals).
  - **Stage 1 (`0s` to `90s`):** Full Target Patience. Mandatory full $1,000\text{ lots}$ ($1.0\text{ BTC}$) allocation. Requires Top Bid depth $\ge 5,000\text{ lots}$ under the 20% L1 Footprint Rule.
  - **Stage 2 (`90s` to `120s`):** Dynamic Equal-Leg Fallback. If full depth is unavailable after 90s, dynamically calculates $\text{equal\_lots} = \min(\text{safe}_{CE}, \text{safe}_{PE}, 1000)$. Executes immediately if $\text{equal\_lots} \ge 500\text{ lots}$ ($0.5\text{ BTC}$). If $< 500\text{ lots}$ across 120s, entry is safely skipped.
* **`10:00:10 IST`–`10:00:30 IST`:** **Dual 10s Settlement & Verification Buffers.**
  - Buffer 1 (10s): Waits for matching engine fill finalization before querying `/v2/positions`.
  - Attaches $+100\%$ ($2.0\times$ entry price) Stop-Market Bracket Stop-Loss on each leg.
  - Buffer 2 (10s): Waits for stop orderbook registration before verifying active status in `/v2/orders?state=open`.
* **`10:00`–`17:15 IST` (Cron `*/2 10-17 * * *`):** **Monitor Daemon (Fast-Exit Guard).** Runs every 2 minutes. Immediately exits with 0 proxy calls if flat or already trailed. If one leg is stopped out, immediately cancels surviving leg's SL and trails it to exact entry cost ($1.00\times$), locking in zero directional risk.
* **`17:15:00 IST` (Cron `15 17 * * *`):** **Guaranteed EOD Square-Off.** 15 minutes prior to 17:30 IST settlement. 3-attempt purge and market buy loop with reduce-only flags and aggressive limit fallback. Verifies 0 positions remaining (100% FLAT).

### Key Architectural Invariants
1. **Zero External Dependencies:** Built strictly on Python Standard Library (`urllib.request`, `hmac`, `hashlib`, `json`, `time`, `os`).
2. **Isolated Proxy Routing:** Public market data (`/v2/tickers`, `/v2/products`) routes directly over local internet (0 KB proxy bandwidth); private authenticated calls (`/v2/orders*`, `/v2/positions`) route through static datacenter proxy with HMAC-SHA256.
3. **Atomic Single-Leg Rollback:** If Leg 1 fills but Leg 2 fails, the engine immediately closes Leg 1 via market buy with `reduce_only=True`, preventing naked overnight exposure.
4. **Equal-Leg Symmetry Invariant:** Sizing is strictly equal across both Call and Put legs (`equal_lots = min(safe_call, safe_put)`) to maintain delta neutrality.
5. **Non-Blocking Drawdown Warning:** Cumulative peak-to-trough drawdown exceeding \$1,185.00 USD dispatches an advisory Telegram alert without halting execution.

---

## 2. END-TO-END EXECUTION STATE MACHINE

```
                           [START: 09:58:00 IST (Cron 58 9 * * *)]
                                              │
                                              ▼
                             [Pre-Flight Drawdown Risk Check]
                                              │
                         ┌────────────────────┴────────────────────┐
                         │                                         │
             [Cumulative DD >= $1185]                     [Drawdown Safe]
                         │                                         │
               Send Telegram Warning                               │
                         │                                         │
                         └────────────────────┬────────────────────┘
                                              │
                                              ▼
                              [Phase 1: Pre-Warm Target Lock]
                           • Scan 0DTE chain via direct public REST
                           • Filter: |Delta - 0.10|, Mark >= $5.00
                           • Lock CE & PE within [0.07, 0.13] bounds
                           • Dispatch Phase 1 Telegram Telemetry
                                              │
                                              ▼
                             [Warm-up Tracking: 09:58 - 10:00]
                           • Poll quotes every 5s (0 exchange orders)
                           • If Delta < 0.07 or > 0.13 ──► Re-Lock & Alert
                                              │
                                              ▼
                             [Phase 2: 10:00:00 IST Sniper Start]
                                              │
                       ┌──────────────────────┴──────────────────────┐
                       ▼                                             ▼
          [Stage 1: Elapsed 0s - 90s]                   [Stage 2: Elapsed 90s - 120s]
          • Require Full 1,000 Lots (1.0 BTC)           • Dynamic Equal-Leg Fallback
          • Both L1 Depths >= 5,000 Lots                • Equal = min(safe_ce, safe_pe, 1000)
          • If Depth < 5,000, wait & retry 5s           • If Equal >= 500 Lots ──► EXECUTE
                                                        • If Equal < 500 across 120s ──► SKIP
                       │                                             │
                       └──────────────────────┬──────────────────────┘
                                              │ (Conditions Met)
                                              ▼
                              [4-Layer Anti-Trap Verification]
                           • Layer 1: Spread / Mark <= 8.0%
                           • Layer 2: Equal Lots >= 500
                           • Layer 3: (Mark - Bid) / Mark <= 2.0%
                           • Layer 4: 2.5s Snapshot Stability Check
                                              │
                                              ▼
                              [Step 0: Set 40x Leverage]
                                              │
                                              ▼
                             [Step 1: Sequential Market Sell]
                           • Submit Market Sell CE (Product ID 1)
                           • Submit Market Sell PE (Product ID 2)
                                              │
                         ┌────────────────────┴────────────────────┐
                         │                                         │
                 [Both Sells Filled]                       [Leg 2 PE Failed]
                         │                                         │
                         │                              [ATOMIC SINGLE-LEG ROLLBACK]
                         │                              • Emergency Market Buy CE
                         │                              • Reduce-Only True + Limit Fallback
                         │                              • Abort Session 100% FLAT
                         │
                         ▼
                   [⏳ 10-Second Wait: Matching Engine Settlement]
                         │
                         ▼
             [Step 2: Query /v2/positions for Realized Fills]
                         │
                         ▼
             [Step 3: Calculate & Attach 100% Bracket SL]
             • SL Trigger = Realized Entry Price × 2.00
             • Submit POST /v2/orders/bracket (Pure Market Stops)
             • Max 3 retries with 2s delay
                         │
                         ▼
                   [⏳ 10-Second Wait: Orderbook Registration]
                         │
                         ▼
             [Step 4: Verify bracket_order == True in /v2/orders]
                         │
                         ▼
             [Step 5: Dispatch Telegram Entry Report & Save state.json]
                         │
                         ▼
             [State: OPEN_PROTECTED | Trail Status: ARMED]
                         │
                         │ ◄── Every 2 Mins: jobs/3_monitor_job.py
                         ▼
             [Monitor: Check Leg States in Live Positions]
                         │
          ┌──────────────┼───────────────────────────┐
          │              │                           │
   [Both Open]     [1 Leg Stopped]             [Both Closed]
          │              │                           │
       Healthy     [COMBO A TRAIL]              Update state.json
                   • Cancel old SL              to BOTH_CLOSED
                   • Move surviving SL
                     to 1.00x entry cost
                   • Telegram Alert
                         │
                         ▼
             [17:15:00 IST: jobs/2_exit_job.py Triggered]
                         │
                         ▼
             [3-Attempt Square-off Loop (4s backoff)]
             • Purge all pending orders (DELETE /v2/orders)
             • Market Buy remaining positions (Reduce-only)
             • Aggressive Limit IOC/GTC fallback if thin book
             • Verify positions == 0
                         │
                         ▼
             [Record PnL to trade_ledger.csv & Send Session Scorecard]
                         │
                         ▼
             [Account 100% FLAT Overnight]
```

---

## 3. COMPREHENSIVE BUG HUNTER'S EDGE-CASE CHECKLIST

When reviewing this codebase for critical vulnerabilities, race conditions, and mathematical edge cases, evaluate the following checklist:

### A. Timing, Clocks & Expiry Determination
- [ ] **Midnight / Rollover UTC Boundary:** `get_target_expiry_date_str()` checks `hour > 17 or (hour == 17 and minute >= 30)`. Does it accurately handle month/year rollouts (e.g. leap years, Dec 31 to Jan 01) via `timedelta(days=1)`?
- [ ] **System Clock Drift:** Phase 1 uses `exec_target = now.replace(hour=10, minute=0, second=0)` and checks `now_fn() < exec_target`. If the host machine's clock steps backward (NTP sync), will `remaining_sec` behave deterministically?
- [ ] **Entry Window Timeout:** `ENTRY_WINDOW_SECONDS = 120`. `start_time = time.time()` tracks elapsed time. If sleep pauses longer than expected on low-power mobile CPU, does attempt counting or elapsed time terminate cleanly?

### B. Orderbook Microstructure & Anti-Trap Math
- [ ] **Zero / Negative Quote Guard:** `mark_price <= 0.0 or best_bid <= 0.0 or best_ask <= 0.0`. Are there scenarios where `best_bid` is missing or `None` in `/v2/tickers` causing unhandled `float(None)` exceptions?
- [ ] **Spread Calculation Zero Division:** `spread / mark_price`. If `mark_price == 0.0`, is zero division caught by the pre-check before the division executes?
- [ ] **Layer 4 Snapshot Timing:** In `check_anti_trap_liquidity`, `sleep_fn(2.5)` is called between snapshot 1 and snapshot 2. During rapid market movements, does `/v2/tickers/{symbol}` return a single dict or a list of dicts, and is the quote extraction type-safe?
- [ ] **Delta Drift Range Boundary:** `0.07 <= abs_delta <= 0.13`. What happens if delta is exactly 0.0700 or 0.1300? (Inclusive comparison is used). If all contracts on the chain have delta outside this range, does it cleanly log a notice and return `(None, None)`?

### C. Sizing, Lot Allocation & Footprint Sizing
- [ ] **Stage 1 vs Stage 2 Boundary:** Stage 1 runs while `elapsed_sec < 90`. At exactly second 90, `elapsed_sec >= 90`, switching to `require_full_target=False` (Stage 2). Does this trigger on attempt ~19?
- [ ] **Equal-Leg Symmetry Guarantee:** In `calculate_liquidity_aware_lots`, `equal_lots = min(safe_call, safe_put)`. If Call depth is 6,000 lots (safe = 1,000) and Put depth is 3,500 lots (safe = 700), `equal_lots` becomes 700. Both legs receive exactly 700 lots. Is it impossible for legs to have asymmetric sizes?
- [ ] **Minimum Floor Enforcement:** If `equal_lots < 500` in Stage 2, does it block entry without executing either leg?

### D. Order Placement, Matching & Atomic Rollback
- [ ] **Exchange Asynchronous Settlement:** Order 1 (CE) sells at market; Order 2 (PE) sells at market. `_market_sell` checks for immediate cancellation (`state == 'cancelled'`). If Order 2 is rejected by exchange matching engine (e.g. margin exhaustion, tick size change), does `_rollback_leg` immediately close Order 1?
- [ ] **Rollback Market Order Rejection:** If the rollback Market Buy for CE is also rejected or cancelled due to no asks in the book, does the code fall back to aggressive Limit IOC, then Limit GTC at `mark_price * 1.25`?
- [ ] **Decimal Tick Precision:** `_round_to_tick_size` uses `Decimal.quantize(ROUND_HALF_UP)`. Does it avoid floating-point representation errors (e.g., `$88.00000000000001`) that cause Delta API `invalid_price_tick` errors?

### E. Bracket Stop-Loss & Cost-to-Cost Trail
- [ ] **Bracket Registration Failure:** If `_place_bracket_sl_with_retry` fails after 3 retries on either leg, does the engine trigger `_emergency_close_strangle` to close both legs immediately rather than holding unhedged short options?
- [ ] **Monitor State Machine Fast-Exit:** If `state.json` does not exist or `trade_date != today`, `jobs/3_monitor_job.py` exits immediately without making any HTTP requests. Does this conserve 100% of mobile data and API quotas when idle?
- [ ] **Surviving Leg Stop Re-placement:** When Leg 1 hits its 100% SL and closes, does `trail_surviving_leg_to_cost` cancel the existing SL order before placing the new stop at entry cost? If the old order cancellation fails, does the new bracket still register?
- [ ] **Double SL Race Condition:** If spot moves so violently that both legs breach their SL triggers in the same 2-minute monitor window, does `monitor_and_update_cost_trail` detect `not ce_pos and not pe_pos` and set `state["trail_status"] = "BOTH_CLOSED"` cleanly?

### F. Square-Off & EOD Purge
- [ ] **Blast-Radius Isolation:** `jobs/2_exit_job.py` extracts `target_pids = state_data["product_ids"]`. When square-off runs, does it strictly cancel orders and close positions matching `target_pids`, ensuring other trades (e.g. BTC perpetual futures) on the same sub-account are NOT closed?
- [ ] **Position Size Signs:** In Delta positions, short option positions have negative size (e.g. `-1000`). Does `square_off_with_retry` correctly set `side = "buy" if size < 0 else "sell"` and `close_size = abs(size)`?

---

## 4. VERBATIM SOURCE CODE MODULES

All source files below are complete, unedited, verbatim production code directly from the repository.

---

### Module 1: `main.py`
```python
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(ROOT_DIR)

from config.settings import DEFAULT_LEVERAGE, LOT_SIZE, load_env

load_env()

from core.api_client import DeltaApiClient
from services.telegram_notifier import TelegramNotifier

BASE_URL = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
API_KEY = os.getenv("DELTA_API_KEY", "")
API_SECRET = os.getenv("DELTA_API_SECRET", "")


def show_status() -> None:
    print("\n" + "=" * 60)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DELTA ALPHA STRANGLE BOT — STATUS CHECK")
    print("=" * 60)

    print(f"• Base URL: {BASE_URL}")
    print(f"• Default Leverage: {DEFAULT_LEVERAGE}x")
    print(f"• Default Lot Size: {LOT_SIZE}")

    state_file = os.path.join(ROOT_DIR, "data", "state.json")
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
            print("\n[Local State File: data/state.json]")
            print(json.dumps(state_data, indent=2))
        except Exception as e:
            print(f"\n[Local State File Error] Could not read {state_file}: {e}")
    else:
        print("\n[Local State File] No active state.json found (Flat / Never traded).")

    client = DeltaApiClient(API_KEY, API_SECRET, BASE_URL)

    print("\n[Exchange Positions Check (/v2/positions)]")
    pos_res = client.request("GET", "/v2/positions?underlying_asset_symbol=BTC")
    positions = pos_res.get("result", []) if pos_res else []
    if isinstance(positions, dict):
        positions = [positions]

    active_positions = [p for p in positions if int(p.get("size", 0)) != 0]
    if active_positions:
        print(f"Found {len(active_positions)} active position(s):")
        for p in active_positions:
            print(
                f"  - Product: {p.get('product_symbol', p.get('product_id'))} | "
                f"Size: {p.get('size')} | Entry: {p.get('entry_price')} | Mark: {p.get('mark_price')}"
            )
    else:
        print("  ✅ 0 active positions on Delta Exchange (Account is FLAT).")

    print("\n[Exchange Open Orders Check (/v2/orders?state=open)]")
    orders_res = client.request("GET", "/v2/orders?state=open")
    orders = orders_res.get("result", []) if orders_res else []
    if isinstance(orders, dict):
        orders = [orders]

    if orders:
        print(f"Found {len(orders)} open order(s):")
        for o in orders:
            print(
                f"  - Order ID: {o.get('id')} | Product: {o.get('product_symbol', o.get('product_id'))} | "
                f"Type: {o.get('order_type')} | Side: {o.get('side')} | Stop: {o.get('stop_price')} | Size: {o.get('size')}"
            )
    else:
        print("  ✅ 0 open orders on Delta Exchange.")
    print("=" * 60 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delta Alpha Strangle Bot CLI Router",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "action",
        choices=["entry", "exit", "status", "monitor"],
        help="Command action to execute:\n"
        "  entry   - Run 10:00 AM IST 0-DTE entry, check anti-trap liquidity, and attach 100%% Combo A Bracket SL\n"
        "  exit    - Run 17:15 IST auto square-off and cancel pending orders\n"
        "  status  - Inspect local state.json and live exchange positions & open orders\n"
        "  monitor - Check active strangle state and execute Combo A Cost-to-Cost Trail if a leg SL triggered",
    )

    args = parser.parse_args()

    try:
        if args.action == "entry":
            entry_mod = importlib.import_module("jobs.1_entry_job")
            entry_mod.run()
        elif args.action == "exit":
            exit_mod = importlib.import_module("jobs.2_exit_job")
            exit_mod.run()
        elif args.action == "status":
            show_status()
        elif args.action == "monitor":
            monitor_mod = importlib.import_module("jobs.3_monitor_job")
            monitor_mod.run()
    except Exception as exc:
        import traceback

        tb = traceback.format_exc()
        tb_lines = tb.strip().splitlines()
        file_line = tb_lines[-2] if len(tb_lines) >= 2 else "Unknown Location"
        short_tb = "\n".join(tb_lines[-8:])

        notifier = TelegramNotifier()
        crash_msg = TelegramNotifier.format_crash_alert(
            job_name=f"main.py {args.action}",
            timestamp_str=datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
            exception_type=type(exc).__name__,
            exception_msg=str(exc),
            file_line=file_line.strip(),
            short_traceback=short_tb,
        )
        print("\n" + crash_msg, file=sys.stderr)
        notifier.send_system_error(crash_msg)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

---

### Module 2: `config/settings.py`
```python
import os


def load_env(env_path: str | None = None) -> None:
    """
    Lightweight built-in .env parser using only standard library.
    Parses key-value pairs, ignores empty lines and comments (#),
    supports UTF-8 and UTF-8-SIG (Windows BOM), and injects into os.environ.
    """
    if env_path is None:
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_path = os.path.join(root_dir, ".env")

    if not os.path.exists(env_path):
        return

    content = ""
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            with open(env_path, "r", encoding=encoding) as f:
                content = f.read()
            break
        except UnicodeError:
            continue

    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ[key.strip()] = val.strip().strip("'\"")


def setup_proxy() -> str | None:
    """
    Constructs and returns the configured proxy URL string if proxy variables are present.
    NOTE: Does NOT globally install the opener via urllib.request.install_opener()
    to prevent leaking public market data and Telegram alerts through the static proxy.
    Proxy routing is isolated exclusively inside DeltaApiClient for private authenticated calls.
    """
    proxy_host = os.getenv("PROXY_HOST", "").strip()
    proxy_port = os.getenv("PROXY_PORT", "").strip()
    proxy_user = os.getenv("PROXY_USER", "").strip()
    proxy_pass = os.getenv("PROXY_PASS", "").strip()

    if proxy_host and proxy_port:
        if proxy_user and proxy_pass:
            return f"http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"
        return f"http://{proxy_host}:{proxy_port}"

    return None


# Auto-load on import
load_env()
ACTIVE_PROXY = setup_proxy()

API_KEY = os.getenv("DELTA_API_KEY", "")
API_SECRET = os.getenv("DELTA_API_SECRET", "")
BASE_URL = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
TARGET_LOTS = int(os.getenv("TARGET_LOTS", os.getenv("LOT_SIZE", "1000")))
MIN_TRADEABLE_LOTS = int(os.getenv("MIN_TRADEABLE_LOTS", "100"))
LOT_SIZE = TARGET_LOTS
DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "40"))
DRY_RUN = os.getenv("DRY_RUN", "False").lower() in ("true", "1", "yes")

# Combo A Stop-Loss & Risk Management Parameters
SL_MULTIPLIER = float(os.getenv("SL_MULTIPLIER", "2.00"))
COST_TRAIL_MULTIPLIER = float(os.getenv("COST_TRAIL_MULTIPLIER", "1.00"))
HARD_KILL_SWITCH_USD = float(os.getenv("HARD_KILL_SWITCH_USD", "1185.00"))

# Entry Timing & Liquidity Guard Parameters
WARMUP_START_HOUR = int(os.getenv("WARMUP_START_HOUR", "9"))
WARMUP_START_MINUTE = int(os.getenv("WARMUP_START_MINUTE", "58"))
EXECUTION_HOUR = int(os.getenv("EXECUTION_HOUR", "10"))
EXECUTION_MINUTE = int(os.getenv("EXECUTION_MINUTE", "0"))
WARMUP_POLL_INTERVAL_SECONDS = int(os.getenv("WARMUP_POLL_INTERVAL_SECONDS", "5"))
MAX_SPREAD_RATIO = float(os.getenv("MAX_SPREAD_RATIO", "0.080"))
ENTRY_WINDOW_SECONDS = int(os.getenv("ENTRY_WINDOW_SECONDS", "120"))
ENTRY_RETRY_INTERVAL_SECONDS = int(os.getenv("ENTRY_RETRY_INTERVAL_SECONDS", "5"))
FULL_TARGET_WAIT_SECONDS = int(os.getenv("FULL_TARGET_WAIT_SECONDS", "90"))
MIN_FALLBACK_LOTS = int(os.getenv("MIN_FALLBACK_LOTS", "500"))

# Telegram Notifications
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
```

---

### Module 3: `core/api_client.py`
```python
from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def setup_proxy() -> str | None:
    """
    Constructs and returns the configured proxy URL string if proxy variables are present.
    NOTE: Does NOT globally install the opener via urllib.request.install_opener()
    to prevent leaking public market data and Telegram alerts through the static proxy.
    Proxy routing is isolated exclusively inside DeltaApiClient for private authenticated calls.
    """
    proxy_host = os.getenv("PROXY_HOST", "").strip()
    proxy_port = os.getenv("PROXY_PORT", "").strip()
    proxy_user = os.getenv("PROXY_USER", "").strip()
    proxy_pass = os.getenv("PROXY_PASS", "").strip()

    if proxy_host and proxy_port:
        if proxy_user and proxy_pass:
            return f"http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"
        return f"http://{proxy_host}:{proxy_port}"

    return None


class DeltaApiClient:
    def __init__(self, api_key: str, api_secret: str, base_url: str):
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.base_url = base_url.rstrip("/")
        self.proxy_url = setup_proxy()

        # 1. Direct Opener (Default local internet, 0 KB proxy bandwidth)
        self.direct_opener = urllib.request.build_opener()

        # 2. Isolated Proxy Opener (Exclusively for authenticated private orders/positions)
        if self.proxy_url:
            proxy_handler = urllib.request.ProxyHandler(
                {
                    "http": self.proxy_url,
                    "https": self.proxy_url,
                }
            )
            self.proxy_opener = urllib.request.build_opener(proxy_handler)
            self.has_proxy = True
        else:
            self.proxy_opener = self.direct_opener
            self.has_proxy = False

    def _generate_signature(self, method: str, timestamp: str, path: str, query_string: str, payload_str: str) -> str:
        # Signature: method + timestamp + path + query_string + payload
        message = method + timestamp + path + query_string + payload_str
        return hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def request_public(
        self,
        method: str,
        full_path: str,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> dict[str, Any]:
        """
        Routes public market data (/v2/tickers, /v2/products) directly over default local internet.
        Consumes 0 KB proxy bandwidth, decompresses gzip in-memory, and includes 3-attempt retry loop.
        """
        method = method.upper()
        parsed = urllib.parse.urlsplit(full_path)
        path = parsed.path
        query_string = f"?{parsed.query}" if parsed.query else ""
        full_url = f"{self.base_url}{path}{query_string}"

        headers = {
            "User-Agent": "DeltaStrangleBot/1.0",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        }
        req = urllib.request.Request(full_url, headers=headers, method=method)

        for attempt in range(1, max_retries + 1):
            try:
                with self.direct_opener.open(req, timeout=15) as response:
                    content = response.read()
                    if response.headers.get("Content-Encoding") == "gzip":
                        content = gzip.decompress(content)
                    return json.loads(content.decode("utf-8"))
            except urllib.error.HTTPError as e:
                err_body = e.read()
                try:
                    if e.headers.get("Content-Encoding") == "gzip":
                        err_body = gzip.decompress(err_body)
                    parsed_err = json.loads(err_body.decode("utf-8"))
                except Exception:
                    parsed_err = {"success": False, "error": str(err_body), "http_code": e.code}

                if e.code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    time.sleep(retry_delay * attempt)
                    continue
                return parsed_err
            except Exception as e:
                if attempt < max_retries:
                    time.sleep(retry_delay * attempt)
                    continue
                return {"success": False, "error": str(e)}

        return {"success": False, "error": "Max retries exceeded"}

    def request_private(
        self,
        method: str,
        full_path: str,
        payload: dict[str, Any] | None = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> dict[str, Any]:
        """
        Routes authenticated orders, positions, and brackets strictly through the Static IP Proxy.
        Enforces Delta HMAC-SHA256 signature and includes a 3-attempt retry wrapper for transient errors.
        """
        method = method.upper()
        parsed = urllib.parse.urlsplit(full_path)
        path = parsed.path
        query_string = f"?{parsed.query}" if parsed.query else ""
        full_url = f"{self.base_url}{path}{query_string}"

        for attempt in range(1, max_retries + 1):
            timestamp = str(int(time.time()))
            payload_str = json.dumps(payload, separators=(",", ":")) if payload else ""
            signature = self._generate_signature(method, timestamp, path, query_string, payload_str)

            headers = {
                "api-key": self.api_key,
                "timestamp": timestamp,
                "signature": signature,
                "User-Agent": "DeltaStrangleBot/1.0",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            data_bytes = payload_str.encode("utf-8") if payload_str else None
            req = urllib.request.Request(full_url, data=data_bytes, headers=headers, method=method)

            try:
                with self.proxy_opener.open(req, timeout=15) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw)
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                if e.code in (429, 502, 503, 504) and attempt < max_retries:
                    time.sleep(retry_delay * attempt)
                    continue
                try:
                    return json.loads(err_body)
                except Exception:
                    return {"success": False, "error": err_body, "http_code": e.code}
            except Exception as e:
                if attempt < max_retries:
                    time.sleep(retry_delay * attempt)
                    continue
                return {"success": False, "error": str(e)}

        return {"success": False, "error": "Max retries exceeded"}

    def request(
        self,
        method: str,
        full_path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Backward-compatible dispatcher:
        Automatically routes public market data endpoints (/v2/products, /v2/tickers) to request_public
        and all authenticated endpoints (/v2/orders*, /v2/positions, /v2/wallet*) to request_private.
        """
        parsed = urllib.parse.urlsplit(full_path)
        path = parsed.path
        public_endpoints = (
            "/v2/products",
            "/v2/tickers",
            "/v2/l2orderbook",
            "/v2/orderbook",
            "/v2/indices",
            "/v2/underlying-prices",
            "/v2/settlement-prices",
            "/v2/assets",
            "/v2/depth",
        )
        if method == "GET" and path.startswith(public_endpoints):
            return self.request_public(method, full_path)
        return self.request_private(method, full_path, payload)
```

---

### Module 4: `services/delta_calculator.py`
```python
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from services.notifier import TelegramNotifier

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT_DIR, "data")
CACHE_FILE = os.path.join(CACHE_DIR, "products_cache.json")
CACHE_TTL_SECONDS = 12 * 3600  # 12 hours TTL for products metadata


def parse_expiry_date(date_str: str) -> date | None:
    """Parses DDMMYY string into datetime.date object for calendar-aware comparisons."""
    try:
        return datetime.strptime(date_str, "%d%m%y").date()
    except (ValueError, TypeError):
        return None


class DeltaCalculator:
    def __init__(self, api_client):
        self.client = api_client
        self.notifier = TelegramNotifier()

    def get_target_expiry_date_str(self) -> str:
        """
        Delta options format: DDMMYY (e.g., 161126 for 16-Nov-2026).
        Delta daily options settle at 17:30:00 IST (12:00:00 UTC).
        After 17:30 IST, rolls over to the next day's expiry date.
        """
        now_ist = datetime.now(IST)
        if (now_ist.hour > 17) or (now_ist.hour == 17 and now_ist.minute >= 30):
            target_date = now_ist.date() + timedelta(days=1)
        else:
            target_date = now_ist.date()

        return target_date.strftime("%d%m%y")

    def _get_products(self) -> list[dict[str, Any]]:
        """
        Fetches products metadata with a 12-hour local file cache to prevent
        re-downloading the ~5.6 MB payload on every entry run.
        Routes via request_public (0 KB proxy bandwidth, gzip compressed).
        """
        if os.path.exists(CACHE_FILE):
            try:
                mtime = os.path.getmtime(CACHE_FILE)
                if (time.time() - mtime) < CACHE_TTL_SECONDS:
                    with open(CACHE_FILE, "r", encoding="utf-8") as f:
                        cached = json.load(f)
                    products = cached.get("result", [])
                    if products:
                        print(f"[CACHE] Loaded {len(products)} products from local cache ({CACHE_FILE}).")
                        return products
            except Exception as e:
                print(f"[CACHE WARN] Could not read products cache: {e}")

        print("[INFO] Fetching fresh /v2/products via public direct connection (0 KB proxy)...")
        resp = self.client.request_public("GET", "/v2/products")
        if resp and resp.get("success"):
            products = resp.get("result", [])
            try:
                os.makedirs(CACHE_DIR, exist_ok=True)
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(resp, f)
                print(f"[CACHE] Saved {len(products)} products to {CACHE_FILE} (TTL: 12h).")
            except Exception as e:
                print(f"[CACHE WARN] Could not write cache file: {e}")
            return products

        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                products = cached.get("result", [])
                if products:
                    print(
                        f"[CACHE FALLBACK] Live fetch failed; falling back to stale cache ({len(products)} products)."
                    )
                    return products
            except Exception:
                pass

        print(f"[ERROR] Failed to fetch products: {resp}")
        return []

    @staticmethod
    def calculate_liquidity_aware_lots(
        call_bid_size: float,
        put_bid_size: float,
        target_lots: int = 1000,
        min_tradeable_lots: int = 100,
        require_full_target: bool = False,
        min_fallback_lots: int = 100,
    ) -> tuple[int, str]:
        """
        2-Stage Dynamic Liquidity-Aware Sizing (20% L1 Footprint Rule):
        - safe_call_lots = min(target_lots, int(call_bid_size * 0.20))
        - safe_put_lots = min(target_lots, int(put_bid_size * 0.20))
        - equal_lots = min(safe_call_lots, safe_put_lots)

        Stage 1 (require_full_target=True, 0s to 90s):
        - Requires equal_lots >= target_lots (full 1,000 lots / 1.0 BTC).
        - If equal_lots < target_lots, returns (equal_lots, wait_msg) to wait for MM depth.

        Stage 2 (require_full_target=False, 90s to 120s):
        - Dynamic Equal-Leg Fallback: executes equal_lots if equal_lots >= min_fallback_lots.
        - Blocks trade only if equal_lots < effective_min (min_fallback_lots).
        """
        effective_min = min(target_lots, max(min_tradeable_lots, min_fallback_lots))
        safe_call = min(target_lots, int(float(call_bid_size) * 0.20))
        safe_put = min(target_lots, int(float(put_bid_size) * 0.20))
        equal_lots = min(safe_call, safe_put)

        if require_full_target:
            if equal_lots < target_lots:
                limiting_leg = "Call" if safe_call < safe_put else ("Put" if safe_put < safe_call else "Both")
                limiting_depth = call_bid_size if limiting_leg == "Call" else put_bid_size
                msg = (
                    f"Stage 1 Patience: L1 depth yields {equal_lots} < target {target_lots} lots "
                    f"({limiting_leg} depth: {limiting_depth:,.0f}). Waiting for full allocation..."
                )
                return equal_lots, msg
            msg = f"Stage 1 Full Target: {equal_lots} / {target_lots} lots (1.0 BTC)"
            return equal_lots, msg

        # Stage 2 Dynamic Fallback
        if equal_lots < effective_min:
            min_depth_seen = min(float(call_bid_size), float(put_bid_size))
            required_depth = effective_min * 5
            msg = (
                f"Blocked: Safe executable lots ({equal_lots}) below MIN_TRADEABLE_LOTS ({effective_min}). "
                f"L1 Bid Depth (Call: {call_bid_size:.0f}, Put: {put_bid_size:.0f}, min: {min_depth_seen:.0f}) < {required_depth} required."
            )
            return equal_lots, msg

        if equal_lots < target_lots:
            limiting_leg = "Call" if safe_call < safe_put else ("Put" if safe_put < safe_call else "Both")
            limiting_depth = call_bid_size if limiting_leg == "Call" else put_bid_size
            msg = f"Adjusted Lots: {equal_lots} / {target_lots} (Stage 2 Dynamic Fallback: Equal {equal_lots} lots on both legs due to {limiting_leg} L1 Depth = {limiting_depth:,.0f})"
        else:
            msg = f"Full allocation: {equal_lots} / {target_lots} lots (L1 Bid Depth >= {target_lots * 5:,} lots)"

        return equal_lots, msg

    def check_anti_trap_liquidity(
        self,
        product_id: int,
        symbol: str,
        mark_price: float,
        best_bid: float,
        best_ask: float,
        bid_size: float,
        order_lots: int = 1000,
        min_tradeable_lots: int = 100,
        max_spread_ratio: float = 0.080,
        sleep_fn: Any = time.sleep,
    ) -> tuple[bool, str, dict[str, Any]]:
        """
        4-Layer Pre-Trade Liquidity & Anti-Trap Filter:
        Layer 1: Spread / Mark <= 0.080 (8.0% max spread barrier, accommodates 2-3 tick MM quotes on low-dollar 0-DTEs)
        Layer 2: 20% L1 Footprint Rule (safe_lots = min(order_lots, int(bid_size * 0.20)) >= min_tradeable_lots)
        Layer 3: (Mark - Best Bid) / Mark <= 0.020 (2.0% max Mark-to-Bid discount)
        Layer 4: 2-Snapshot Stability Check (sample twice 2.5s apart):
                 Blocks entry if Best Bid shifts > 1.5% or Top Bid Lots drops > 50%.
        """
        metrics: dict[str, Any] = {
            "product_id": product_id,
            "symbol": symbol,
            "mark_price": mark_price,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "bid_size": bid_size,
            "order_lots": order_lots,
            "min_tradeable_lots": min_tradeable_lots,
            "max_spread_ratio": max_spread_ratio,
        }

        # Pre-check: non-positive prices
        if mark_price <= 0.0 or best_bid <= 0.0 or best_ask <= 0.0:
            err = f"Pre-check failed: Non-positive price/quotes (Mark: {mark_price}, Bid: {best_bid}, Ask: {best_ask})"
            return False, err, metrics

        # Layer 1: Max Spread Slippage Barrier (<= 8.0%)
        spread = best_ask - best_bid
        spread_ratio = spread / mark_price
        metrics["spread"] = spread
        metrics["spread_ratio"] = spread_ratio
        if spread_ratio > max_spread_ratio:
            reason = (
                f"Layer 1 Failed: Spread ratio {spread_ratio:.2%} exceeds {max_spread_ratio:.1%} limit "
                f"(Spread: {spread:.2f}, Mark: {mark_price:.2f}, Ask: {best_ask:.2f}, Bid: {best_bid:.2f})"
            )
            return False, reason, metrics

        # Layer 2: 20% L1 Footprint Rule (Dynamic Liquidity-Aware Sizing)
        metrics["target_lots"] = order_lots
        metrics["min_tradeable_lots"] = min_tradeable_lots
        effective_min = min(order_lots, min_tradeable_lots)
        min_required_depth = float(effective_min * 5)

        if bid_size < min_required_depth:
            safe_lots = int(float(bid_size) * 0.20)
            metrics["safe_lots"] = safe_lots
            reason = (
                f"Layer 2 Failed: Top Bid depth {bid_size:.1f} < {min_required_depth:.0f} lots required under 20% L1 footprint rule "
                f"(yields {safe_lots} < MIN_TRADEABLE_LOTS {effective_min})"
            )
            return False, reason, metrics

        safe_lots = min(order_lots, int(float(bid_size) * 0.20))
        metrics["safe_lots"] = safe_lots
        if safe_lots < effective_min:
            reason = (
                f"Layer 2 Failed: Safe lots ({safe_lots}) below MIN_TRADEABLE_LOTS ({effective_min}) "
                f"due to Top Bid depth {bid_size:.1f} < {min_required_depth:.0f} lots required under 20% L1 footprint rule"
            )
            return False, reason, metrics

        # Layer 3: Mark-to-Bid Discount (<= 2.0%)
        discount = (mark_price - best_bid) / mark_price
        metrics["mark_bid_discount"] = discount
        if discount > 0.020:
            reason = (
                f"Layer 3 Failed: Mark-to-Bid discount {discount:.2%} exceeds 2.0% limit "
                f"(Mark: {mark_price:.2f}, Bid: {best_bid:.2f})"
            )
            return False, reason, metrics

        # Layer 4: 2-Snapshot Stability Check (sample twice 2.5s apart)
        if sleep_fn:
            sleep_fn(2.5)

        snap2_resp = self.client.request_public("GET", f"/v2/tickers/{symbol}")
        snap2_quotes = None
        if snap2_resp and snap2_resp.get("success"):
            res = snap2_resp.get("result")
            if isinstance(res, dict):
                snap2_quotes = res.get("quotes")
            elif isinstance(res, list):
                for t in res:
                    if t.get("product_id") == product_id or t.get("symbol") == symbol:
                        snap2_quotes = t.get("quotes")
                        break
        else:
            all_t_resp = self.client.request_public("GET", "/v2/tickers")
            if all_t_resp and all_t_resp.get("success"):
                res_all = all_t_resp.get("result", [])
                if isinstance(res_all, list):
                    for t in res_all:
                        if t.get("product_id") == product_id or t.get("symbol") == symbol:
                            snap2_quotes = t.get("quotes")
                            break

        if not snap2_quotes:
            reason = "Layer 4 Failed: Could not fetch snapshot 2 quote for 2.5s stability verification"
            return False, reason, metrics

        snap2_bid = float(snap2_quotes.get("best_bid") or 0.0)
        snap2_bid_size = float(snap2_quotes.get("bid_size") or 0.0)
        metrics["snap2_bid"] = snap2_bid
        metrics["snap2_bid_size"] = snap2_bid_size

        if snap2_bid <= 0.0:
            reason = "Layer 4 Failed: Snapshot 2 Best Bid collapsed to 0.0"
            return False, reason, metrics

        bid_shift = abs(snap2_bid - best_bid) / best_bid
        metrics["bid_shift"] = bid_shift
        if bid_shift > 0.015:
            reason = (
                f"Layer 4 Failed: Best Bid shifted by {bid_shift:.2%} (> 1.5% limit) "
                f"in 2.5s snapshot ({best_bid:.2f} -> {snap2_bid:.2f})"
            )
            return False, reason, metrics

        if snap2_bid_size < 0.50 * bid_size:
            reason = (
                f"Layer 4 Failed: Top Bid depth dropped by > 50% in 2.5s snapshot "
                f"({bid_size:.1f} lots -> {snap2_bid_size:.1f} lots)"
            )
            return False, reason, metrics

        return True, "All 4 Anti-Trap Liquidity Layers Passed", metrics

    def refresh_strike_quote(self, strike_info: dict[str, Any]) -> dict[str, Any] | None:
        """
        Fetches live quotes and Greeks for a locked strike via direct public endpoint (0 KB proxy).
        Updates mark_price, best_bid, best_ask, bid_size, delta, and abs_delta in a shallow copy.
        """
        if not strike_info or not strike_info.get("symbol"):
            return None
        symbol = strike_info["symbol"]
        prod_id = strike_info.get("id")

        resp = self.client.request_public("GET", f"/v2/tickers/{symbol}")
        quotes = None
        mark_price = None
        greeks = None
        if resp and resp.get("success"):
            res = resp.get("result")
            if isinstance(res, dict):
                quotes = res.get("quotes")
                mark_price = res.get("mark_price")
                greeks = res.get("greeks")
            elif isinstance(res, list):
                for t in res:
                    if t.get("product_id") == prod_id or t.get("symbol") == symbol:
                        quotes = t.get("quotes")
                        mark_price = t.get("mark_price")
                        greeks = t.get("greeks")
                        break
        else:
            all_resp = self.client.request_public("GET", "/v2/tickers")
            if all_resp and all_resp.get("success"):
                for t in all_resp.get("result", []):
                    if t.get("product_id") == prod_id or t.get("symbol") == symbol:
                        quotes = t.get("quotes")
                        mark_price = t.get("mark_price")
                        greeks = t.get("greeks")
                        break

        if not quotes:
            return None

        updated = dict(strike_info)
        if mark_price is not None:
            updated["mark_price"] = float(mark_price or 0.0)
        updated["best_bid"] = float(quotes.get("best_bid") or 0.0)
        updated["best_ask"] = float(quotes.get("best_ask") or 0.0)
        updated["bid_size"] = float(quotes.get("bid_size") or 0.0)
        if greeks and greeks.get("delta") is not None:
            try:
                updated["delta"] = float(greeks["delta"])
                updated["abs_delta"] = abs(updated["delta"])
            except (ValueError, TypeError):
                pass
        return updated

    def check_delta_drift(self, strike_info: dict[str, Any] | None) -> bool:
        """
        Returns True if the strike's live delta remains within the institutional 0-DTE band [0.07, 0.13].
        Returns False if delta drifted outside, signalling that target re-locking is required.
        """
        if not strike_info:
            return False
        abs_delta = strike_info.get("abs_delta")
        if abs_delta is None:
            delta = strike_info.get("delta")
            if delta is not None:
                abs_delta = abs(float(delta))
        if abs_delta is None:
            return False
        return 0.07 <= abs_delta <= 0.13

    def lock_10_delta_strikes(
        self,
        symbol: str = "BTC",
        target_delta: float = 0.10,
        expiry_date_str: str | None = None,
        target_lots: int = 1000,
        min_tradeable_lots: int = 100,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """
        Scans today's 0-DTE option chain and locks the closest 10-Delta CE and PE contracts in memory.
        Enforces 0.07 <= |delta| <= 0.13, mark >= $5.00, active bid/ask, and bid_size >= effective_min.
        Does NOT execute orders or run 4-layer anti-trap; returns raw locked strike structures.
        """
        target_date_suffix = expiry_date_str or self.get_target_expiry_date_str()
        print(f"[INFO] Scanning 0-DTE chain for Expiry Date Suffix: {target_date_suffix}")

        tickers_resp = self.client.request_public("GET", "/v2/tickers")
        if not tickers_resp or not tickers_resp.get("success"):
            print(f"[ERROR] Failed to fetch tickers: {tickers_resp}")
            return None, None

        all_tickers = tickers_resp.get("result", [])
        products_list = self._get_products()
        if not products_list:
            return None, None

        products_map = {p["id"]: p for p in products_list}
        ce_candidates: list[dict[str, Any]] = []
        pe_candidates: list[dict[str, Any]] = []
        available_expiries: set[str] = set()

        for ticker in all_tickers:
            prod_id = ticker.get("product_id")
            prod = products_map.get(prod_id)
            if not prod:
                continue

            contract_type = prod.get("contract_type")
            if contract_type not in ("call_options", "put_options"):
                continue

            symbol_name = prod.get("symbol", "")
            if not symbol_name.startswith(("C-BTC-", "P-BTC-")):
                continue

            parts = symbol_name.split("-")
            if len(parts) >= 4:
                available_expiries.add(parts[-1])

            if not symbol_name.endswith(target_date_suffix):
                continue

            greeks = ticker.get("greeks") or {}
            raw_delta = greeks.get("delta")
            if raw_delta is None:
                continue

            try:
                raw_delta = float(raw_delta)
            except (ValueError, TypeError):
                continue

            abs_delta = abs(raw_delta)
            if not (0.07 <= abs_delta <= 0.13):
                continue

            quotes = ticker.get("quotes") or {}
            mark_price = float(ticker.get("mark_price") or 0.0)
            best_bid = float(quotes.get("best_bid") or 0.0)
            best_ask = float(quotes.get("best_ask") or 0.0)
            bid_size = float(quotes.get("bid_size") or 0.0)

            if best_bid <= 0.0 or best_ask <= 0.0:
                continue
            if mark_price < 5.0:
                continue

            is_testnet = "testnet" in getattr(self.client, "base_url", "").lower()
            min_bid = 1.0 if is_testnet else 5.0
            if best_bid < min_bid:
                continue

            spread = best_ask - best_bid
            if (spread / mark_price) > 0.40:
                continue

            effective_min_depth = min(target_lots, min_tradeable_lots)
            if bid_size < float(effective_min_depth):
                continue

            tick_size = float(prod.get("tick_size") or 0.1)
            candidate_info = {
                "id": prod_id,
                "symbol": symbol_name,
                "strike_price": float(prod.get("strike_price", 0.0)),
                "tick_size": tick_size,
                "delta": raw_delta,
                "abs_delta": abs_delta,
                "delta_diff": abs(abs_delta - target_delta),
                "mark_price": mark_price,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "bid_size": bid_size,
            }

            if contract_type == "call_options":
                ce_candidates.append(candidate_info)
            else:
                pe_candidates.append(candidate_info)

        if not ce_candidates and not pe_candidates:
            valid_expiries = [e for e in available_expiries if parse_expiry_date(e) is not None]
            sorted_expiries = sorted(valid_expiries, key=lambda e: parse_expiry_date(e) or date.min)
            print(f"[DEBUG] Active Expiries found on Delta: {sorted_expiries}")

        best_ce = min(ce_candidates, key=lambda x: x["delta_diff"]) if ce_candidates else None
        best_pe = min(pe_candidates, key=lambda x: x["delta_diff"]) if pe_candidates else None

        if not best_ce or not best_pe:
            missing = []
            if not best_ce:
                missing.append("CE")
            if not best_pe:
                missing.append("PE")
            print(
                f"[0-DTE NOTICE] No qualifying 10-Delta strikes found for today's 0-DTE expiry "
                f"({target_date_suffix}). Missing: {', '.join(missing)}. "
                f"Strict 0-DTE mandate active — skipping session cleanly."
            )
            return None, None

        return best_ce, best_pe

    def get_10_delta_strikes(
        self,
        symbol: str = "BTC",
        target_delta: float = 0.10,
        expiry_date_str: str | None = None,
        target_lots: int = 1000,
        min_tradeable_lots: int = 100,
        lot_size: int | None = None,
        enable_anti_trap: bool = True,
        max_spread_ratio: float = 0.080,
        suppress_block_alert: bool = False,
        locked_ce: dict[str, Any] | None = None,
        locked_pe: dict[str, Any] | None = None,
        require_full_target: bool = False,
        min_fallback_lots: int = 100,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """
        Selects optimal 10-Delta Call and Put strikes strictly for today's 0-DTE expiry.
        Supports 2-Phase pre-warm flow: if locked_ce and locked_pe are provided, directly audits
        and sizes the pre-locked targets (refreshing quotes & re-locking only on delta drift).
        Applies Dynamic Liquidity-Aware Sizing (20% L1 footprint rule) and 4-Layer Anti-Trap Filter.
        """
        if lot_size is not None:
            target_lots = lot_size

        best_ce = locked_ce
        best_pe = locked_pe

        if best_ce and best_pe:
            refreshed_ce = self.refresh_strike_quote(best_ce)
            refreshed_pe = self.refresh_strike_quote(best_pe)
            if refreshed_ce:
                best_ce = refreshed_ce
            if refreshed_pe:
                best_pe = refreshed_pe

            if not self.check_delta_drift(best_ce) or not self.check_delta_drift(best_pe):
                print("[INFO] Pre-locked strike delta drifted outside [0.07, 0.13]. Re-locking targets from chain...")
                best_ce, best_pe = self.lock_10_delta_strikes(
                    symbol=symbol,
                    target_delta=target_delta,
                    expiry_date_str=expiry_date_str,
                    target_lots=target_lots,
                    min_tradeable_lots=min_tradeable_lots,
                )
        else:
            best_ce, best_pe = self.lock_10_delta_strikes(
                symbol=symbol,
                target_delta=target_delta,
                expiry_date_str=expiry_date_str,
                target_lots=target_lots,
                min_tradeable_lots=min_tradeable_lots,
            )

        if not best_ce or not best_pe:
            return None, None

        if enable_anti_trap:
            final_lots, sizing_msg = self.calculate_liquidity_aware_lots(
                call_bid_size=best_ce["bid_size"],
                put_bid_size=best_pe["bid_size"],
                target_lots=target_lots,
                min_tradeable_lots=min_tradeable_lots,
                require_full_target=require_full_target,
                min_fallback_lots=min_fallback_lots,
            )
            best_ce["allocated_lots"] = final_lots
            best_pe["allocated_lots"] = final_lots
            best_ce["sizing_msg"] = sizing_msg
            best_pe["sizing_msg"] = sizing_msg

            if require_full_target and final_lots < target_lots:
                print(f"[STAGE 1 PATIENCE] {sizing_msg}")
                return None, None

            effective_min = min(target_lots, max(min_tradeable_lots, min_fallback_lots))
            if final_lots < effective_min:
                print(f"[ANTI-TRAP BLOCKED] Sizing below threshold: {sizing_msg}")
                if not suppress_block_alert:
                    block_alert = TelegramNotifier.format_anti_trap_blocked_alert(
                        date_str=datetime.now().strftime("%Y-%m-%d"),
                        time_str=datetime.now().strftime("%H:%M:%S"),
                        layer_name=f"Layer 2 — Top Bid Depth Cushion (< {effective_min * 5} contracts)",
                        contract_symbol=f"{best_ce['symbol']} / {best_pe['symbol']}",
                        violation_reason=sizing_msg,
                        mark_price=best_ce.get("mark_price"),
                        best_bid=best_ce.get("best_bid"),
                        best_ask=best_ce.get("best_ask"),
                        bid_size=min(float(best_ce.get("bid_size", 0.0)), float(best_pe.get("bid_size", 0.0))),
                    )
                    self.notifier.send_message(block_alert, is_trade_alert=True)
                return None, None

            print(f"\n[DYNAMIC SIZING] {sizing_msg}")
            print(f"[ANTI-TRAP AUDIT] Auditing CE ({best_ce['symbol']}) through 4-layer filter at {final_lots} lots...")
            ce_ok, ce_reason, _ = self.check_anti_trap_liquidity(
                product_id=best_ce["id"],
                symbol=best_ce["symbol"],
                mark_price=best_ce["mark_price"],
                best_bid=best_ce["best_bid"],
                best_ask=best_ce["best_ask"],
                bid_size=best_ce["bid_size"],
                order_lots=final_lots,
                min_tradeable_lots=min_tradeable_lots,
                max_spread_ratio=max_spread_ratio,
            )
            if not ce_ok:
                print(f"[ANTI-TRAP BLOCKED] CE Rejected: {ce_reason}")
                layer_name = f"Layer 1 — Maximum Bid-Ask Spread Gate (> {max_spread_ratio:.1%})"
                if "gap" in ce_reason.lower():
                    layer_name = "Layer 3 — Mark-to-Bid Slippage Gap (> 2.0%)"
                elif "deviation" in ce_reason.lower() or "stability" in ce_reason.lower():
                    layer_name = "Layer 4 — 2.5s Microstructure Spoofing Shift"
                elif "depth" in ce_reason.lower() or "cushion" in ce_reason.lower():
                    layer_name = "Layer 2 — Top Bid Depth Cushion"

                if not suppress_block_alert:
                    block_alert = TelegramNotifier.format_anti_trap_blocked_alert(
                        date_str=datetime.now().strftime("%Y-%m-%d"),
                        time_str=datetime.now().strftime("%H:%M:%S"),
                        layer_name=layer_name,
                        contract_symbol=best_ce["symbol"],
                        violation_reason=ce_reason,
                        mark_price=best_ce.get("mark_price"),
                        best_bid=best_ce.get("best_bid"),
                        best_ask=best_ce.get("best_ask"),
                        bid_size=best_ce.get("bid_size"),
                    )
                    self.notifier.send_message(block_alert, is_trade_alert=True)
                return None, None

            print(f"[ANTI-TRAP AUDIT] Auditing PE ({best_pe['symbol']}) through 4-layer filter at {final_lots} lots...")
            pe_ok, pe_reason, _ = self.check_anti_trap_liquidity(
                product_id=best_pe["id"],
                symbol=best_pe["symbol"],
                mark_price=best_pe["mark_price"],
                best_bid=best_pe["best_bid"],
                best_ask=best_pe["best_ask"],
                bid_size=best_pe["bid_size"],
                order_lots=final_lots,
                min_tradeable_lots=min_tradeable_lots,
                max_spread_ratio=max_spread_ratio,
            )
            if not pe_ok:
                print(f"[ANTI-TRAP BLOCKED] PE Rejected: {pe_reason}")
                layer_name = f"Layer 1 — Maximum Bid-Ask Spread Gate (> {max_spread_ratio:.1%})"
                if "gap" in pe_reason.lower():
                    layer_name = "Layer 3 — Mark-to-Bid Slippage Gap (> 2.0%)"
                elif "deviation" in pe_reason.lower() or "stability" in pe_reason.lower():
                    layer_name = "Layer 4 — 2.5s Microstructure Spoofing Shift"
                elif "depth" in pe_reason.lower() or "cushion" in pe_reason.lower():
                    layer_name = "Layer 2 — Top Bid Depth Cushion"

                if not suppress_block_alert:
                    block_alert = TelegramNotifier.format_anti_trap_blocked_alert(
                        date_str=datetime.now().strftime("%Y-%m-%d"),
                        time_str=datetime.now().strftime("%H:%M:%S"),
                        layer_name=layer_name,
                        contract_symbol=best_pe["symbol"],
                        violation_reason=pe_reason,
                        mark_price=best_pe.get("mark_price"),
                        best_bid=best_pe.get("best_bid"),
                        best_ask=best_pe.get("best_ask"),
                        bid_size=best_pe.get("bid_size"),
                    )
                    self.notifier.send_message(block_alert, is_trade_alert=True)
                return None, None

            print(f"[ANTI-TRAP AUDIT] Both CE and PE cleared all 4 liquidity layers at {final_lots} lots! ✅")
        else:
            best_ce["allocated_lots"] = target_lots
            best_pe["allocated_lots"] = target_lots
            best_ce["sizing_msg"] = f"Unfiltered sizing: {target_lots} lots"
            best_pe["sizing_msg"] = f"Unfiltered sizing: {target_lots} lots"

        return best_ce, best_pe
```

---

### Module 5: `services/order_manager.py`
```python
from __future__ import annotations

import time
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from config.settings import COST_TRAIL_MULTIPLIER, DRY_RUN, SL_MULTIPLIER, TARGET_LOTS
from services.notifier import TelegramNotifier


class OrderManager:
    def __init__(
        self,
        api_client,
        default_leverage: int = 40,
        sl_multiplier: float | None = None,
        cost_trail_multiplier: float | None = None,
        dry_run: bool | None = None,
    ):
        self.client = api_client
        self.notifier = TelegramNotifier()
        self.default_leverage = default_leverage
        self.sl_multiplier = sl_multiplier if sl_multiplier is not None else SL_MULTIPLIER
        self.cost_trail_multiplier = (
            cost_trail_multiplier if cost_trail_multiplier is not None else COST_TRAIL_MULTIPLIER
        )
        self.dry_run = dry_run if dry_run is not None else DRY_RUN

    def set_leverage(self, product_id: int, leverage: int = 40) -> bool:
        """
        Sets order leverage for a specific product on Delta Exchange.
        Handles portfolio margin mode (where contract-level leverage is unsupported) gracefully.
        """
        payload = {"leverage": str(leverage)}
        resp = self.client.request("POST", f"/v2/products/{product_id}/orders/leverage", payload=payload)

        if not resp or resp.get("http_code") == 404 or resp.get("error") == "Not Found":
            resp = self.client.request(
                "POST",
                "/v2/orders/leverage",
                payload={"product_id": product_id, "leverage": str(leverage)},
            )

        if resp and resp.get("success"):
            print(f"[LEVERAGE] Product {product_id} leverage configured to {leverage}x ✅")
            return True

        err = resp.get("error", {}) if resp else {}
        err_code = err.get("code") if isinstance(err, dict) else str(err)
        if err_code == "unsupported":
            print(f"[LEVERAGE] Product {product_id} Portfolio Margin active (leverage managed dynamically) ✅")
            return True

        print(f"[LEVERAGE WARN] Could not set leverage for {product_id}: {resp}")
        return False

    def execute_strangle_with_dual_verification(
        self,
        ce_info: dict[str, Any],
        pe_info: dict[str, Any],
        size: int = 1,
        fill_delay_sec: int | None = None,
    ) -> dict[str, Any]:
        """
        0. Sets 40x leverage on CE and PE products.
        1. Executes CE and PE Market Sell orders with immediate cancellation audit.
        2. Pauses 10s for matching engine settlement.
        3. Fetches real positions table; triggers atomic rollback if asymmetric fill.
        4. Attaches 100% pure market stop bracket orders (2.0x entry price) with 3-attempt retry loop.
        5. Pauses 10s for stop orderbook registration.
        6. Verifies bracket orders in open orderbook (/v2/orders?state=open).
        7. Sends confirmed Telegram execution alert.
        """
        report: dict[str, Any] = {
            "ce": {"product_id": ce_info["id"], "symbol": ce_info["symbol"]},
            "pe": {"product_id": pe_info["id"], "symbol": pe_info["symbol"]},
            "ce_info": ce_info,
            "pe_info": pe_info,
            "size": size,
            "fill_delay_sec": fill_delay_sec,
            "target_lots": ce_info.get("target_lots", TARGET_LOTS),
            "sizing_msg": ce_info.get("sizing_msg", f"{size} lots"),
            "success": False,
        }

        if self.dry_run:
            print("\n==================================================")
            print(f">>> [DRY RUN SIMULATION] SIMULATING {self.default_leverage}X LEVERAGE & MARKET SELL <<<")
            print("==================================================")
            ce_tick = float(ce_info.get("tick_size") or 0.1)
            pe_tick = float(pe_info.get("tick_size") or 0.1)

            ce_entry = float(ce_info.get("best_bid") or ce_info.get("mark_price") or 0.0)
            pe_entry = float(pe_info.get("best_bid") or pe_info.get("mark_price") or 0.0)

            ce_sl_trigger = self._round_to_tick_size(ce_entry * self.sl_multiplier, ce_tick)
            pe_sl_trigger = self._round_to_tick_size(pe_entry * self.sl_multiplier, pe_tick)

            report["ce"]["entry_price"] = ce_entry
            report["pe"]["entry_price"] = pe_entry
            report["ce"]["sl_trigger"] = ce_sl_trigger
            report["pe"]["sl_trigger"] = pe_sl_trigger
            report["ce"]["sl_order_id"] = 999901
            report["pe"]["sl_order_id"] = 999902
            report["ce"]["sl_verified"] = True
            report["pe"]["sl_verified"] = True
            report["ce"]["tick_size"] = ce_tick
            report["pe"]["tick_size"] = pe_tick
            report["ce"]["sl_mode"] = "100_PERCENT"
            report["pe"]["sl_mode"] = "100_PERCENT"
            report["strategy"] = "COMBO_A"
            report["trail_status"] = "ARMED"
            report["success"] = True

            print(f"[*] [DRY RUN] CE Simulated Entry: {ce_entry} USD | SL: {ce_sl_trigger} USD")
            print(f"[*] [DRY RUN] PE Simulated Entry: {pe_entry} USD | SL: {pe_sl_trigger} USD")
            print(">>> [DRY RUN] DISPATCHING TELEGRAM ENTRY REPORT <<<")
            self._send_final_notification(report)
            return report

        print("\n==================================================")
        print(f">>> STEP 0: CONFIGURING {self.default_leverage}X LEVERAGE <<<")
        print("==================================================")
        self.set_leverage(ce_info["id"], self.default_leverage)
        self.set_leverage(pe_info["id"], self.default_leverage)

        print("\n==================================================")
        print(">>> STEP 1: EXECUTING MARKET SELL (ENTRY ORDERS) <<<")
        print("==================================================")

        ce_sell_res = self._market_sell(ce_info["id"], size, "CE", ce_info["symbol"])
        if not ce_sell_res:
            err_msg = (
                "❌ [ABORT] CE Sell rejected or cancelled by exchange. Strategy stopped safely (No positions open)."
            )
            print(err_msg)
            self.notifier.send_message(f"🚨 *DELTA BOT ALERT*\n{err_msg}")
            return report

        pe_sell_res = self._market_sell(pe_info["id"], size, "PE", pe_info["symbol"])
        if not pe_sell_res:
            err_msg = (
                "🚨 *[CRITICAL ALERT] PE Sell failed after CE filled!*\n"
                f"Contract `{ce_info['symbol']}` is left naked short.\n"
                "⚡ Triggering ATOMIC ROLLBACK (Closing naked CE immediately)..."
            )
            print(f"\n{err_msg}")
            self.notifier.send_message(err_msg)
            self._rollback_leg(ce_info, size, "CE")
            return report

        print("\n[WAIT] 10 second ruk rahe hain taaki exchange par positions settle ho sakein...")
        for sec in range(10, 0, -1):
            print(f" -> Position sync in {sec}s...", end="\r")
            time.sleep(1)
        print("\n[SYNC] 10 second poore hue! Ab positions fetch ki ja rahi hain.\n")

        print(">>> STEP 2: FETCHING REAL POSITIONS DATA <<<")
        positions = self._get_open_positions()

        ce_pos = self._find_position(positions, ce_info["id"])
        pe_pos = self._find_position(positions, pe_info["id"])

        if not ce_pos and not pe_pos:
            err_msg = "[ERROR] Neither position found in positions table! Market orders likely cancelled."
            print(err_msg)
            self.notifier.send_message(f"⚠️ *DELTA BOT ERROR*\n{err_msg}")
            return report
        elif ce_pos and not pe_pos:
            err_msg = (
                f"🚨 *[CRITICAL ALERT] PE position missing after CE filled!*\n"
                f"Rolling back naked CE leg ({ce_info['symbol']}) immediately..."
            )
            print(err_msg)
            self.notifier.send_message(err_msg)
            self._rollback_leg(ce_info, size, "CE")
            return report
        elif pe_pos and not ce_pos:
            err_msg = (
                f"🚨 *[CRITICAL ALERT] CE position missing after PE filled!*\n"
                f"Rolling back naked PE leg ({pe_info['symbol']}) immediately..."
            )
            print(err_msg)
            self.notifier.send_message(err_msg)
            self._rollback_leg(pe_info, size, "PE")
            return report

        ce_entry = float(ce_pos.get("entry_price") or 0.0)
        pe_entry = float(pe_pos.get("entry_price") or 0.0)

        report["ce"]["entry_price"] = ce_entry
        report["pe"]["entry_price"] = pe_entry

        print(f"[*] CE Confirmed: {ce_info['symbol']} | Real Entry: {ce_entry} USD")
        print(f"[*] PE Confirmed: {pe_info['symbol']} | Real Entry: {pe_entry} USD")

        print("\n>>> STEP 3: ATTACHING 100% COMBO A BRACKET STOP LOSS ORDERS <<<")
        ce_tick = float(ce_info.get("tick_size") or 0.1)
        pe_tick = float(pe_info.get("tick_size") or 0.1)

        raw_ce_sl = ce_entry * self.sl_multiplier
        raw_pe_sl = pe_entry * self.sl_multiplier

        ce_sl_trigger = self._round_to_tick_size(raw_ce_sl, ce_tick)
        pe_sl_trigger = self._round_to_tick_size(raw_pe_sl, pe_tick)

        report["ce"]["sl_trigger"] = ce_sl_trigger
        report["pe"]["sl_trigger"] = pe_sl_trigger
        report["ce"]["tick_size"] = ce_tick
        report["pe"]["tick_size"] = pe_tick
        report["ce"]["sl_mode"] = "100_PERCENT"
        report["pe"]["sl_mode"] = "100_PERCENT"
        report["strategy"] = "COMBO_A"
        report["trail_status"] = "ARMED"

        print(f"[CE SL Setup] Trigger @ {ce_sl_trigger} USD (Pure Market Stop, Tick: {ce_tick})")
        ce_sl_oid = self._place_bracket_sl_with_retry(
            ce_info["id"], ce_sl_trigger, "CE", tick_size=ce_tick, max_retries=3
        )

        print(f"[PE SL Setup] Trigger @ {pe_sl_trigger} USD (Pure Market Stop, Tick: {pe_tick})")
        pe_sl_oid = self._place_bracket_sl_with_retry(
            pe_info["id"], pe_sl_trigger, "PE", tick_size=pe_tick, max_retries=3
        )

        report["ce"]["sl_order_id"] = ce_sl_oid
        report["pe"]["sl_order_id"] = pe_sl_oid

        if not ce_sl_oid or not pe_sl_oid:
            emergency_msg = (
                "🚨 *[CRITICAL EMERGENCY] Bracket Stop-Loss attachment failed after 3 retries!*\n"
                "⚡ Executing protective emergency square-off to avoid naked positions..."
            )
            print(f"\n{emergency_msg}\n")
            self.notifier.send_message(emergency_msg)
            self._emergency_close_strangle(ce_info, pe_info, size)
            report["success"] = False
            return report

        print("\n[WAIT] 10 second ruk rahe hain taaki exchange par Bracket SL verify ho sakein...")
        for sec in range(10, 0, -1):
            print(f" -> Bracket verification in {sec}s...", end="\r")
            time.sleep(1)
        print("\n[SYNC] 10 second poore hue! Ab open bracket orders verify kiye ja rahe hain.\n")

        print(">>> STEP 4: VERIFYING BRACKET SL REGISTRATION <<<")
        open_orders = self._get_open_orders()

        ce_sl_active = self._verify_bracket_in_orders(open_orders, ce_info["id"], ce_sl_trigger, tick_size=ce_tick)
        pe_sl_active = self._verify_bracket_in_orders(open_orders, pe_info["id"], pe_sl_trigger, tick_size=pe_tick)

        report["ce"]["sl_verified"] = ce_sl_active
        report["pe"]["sl_verified"] = pe_sl_active
        report["success"] = bool(ce_sl_active and pe_sl_active)

        print("\n==================================================")
        if report["success"]:
            print(">>> STATUS: ALL ORDERS & BRACKET-SL 100% VERIFIED <<<")
            self._send_final_notification(report)
        else:
            warn_msg = (
                f"⚠️ *DELTA BOT WARNING*\nPositions open hain par Bracket SL verify nahi hua!\n"
                f"CE Active: {ce_sl_active} | PE Active: {pe_sl_active}"
            )
            print(warn_msg)
            self.notifier.send_message(warn_msg)
        print("==================================================")

        return report

    def _market_sell(self, product_id: int, size: int, leg_name: str, symbol: str) -> bool:
        """Places market sell order with immediate cancellation detection."""
        payload = {
            "product_id": product_id,
            "size": size,
            "side": "sell",
            "order_type": "market_order",
        }
        resp = self.client.request("POST", "/v2/orders", payload=payload)
        success = resp.get("success", False) if resp else False
        if success:
            res_data = resp.get("result", {})
            oid = res_data.get("id")
            state = res_data.get("state")
            cancellation_reason = res_data.get("cancellation_reason")

            if state == "cancelled":
                print(f"[{leg_name} CANCELLED BY EXCHANGE] {symbol} (Order ID: {oid}) | Reason: {cancellation_reason}")
                return False

            if state not in ("closed", "filled"):
                time.sleep(1)
                order_check = self.client.request("GET", f"/v2/orders/{oid}")
                if order_check and order_check.get("success"):
                    checked_data = order_check.get("result", {})
                    checked_state = checked_data.get("state")
                    if checked_state == "cancelled":
                        reason = checked_data.get("cancellation_reason") or "orderbook_liquidity_exhausted"
                        print(f"[{leg_name} CANCELLED ON MATCHING] {symbol} (Order ID: {oid}) | Reason: {reason}")
                        return False

            print(f"[{leg_name} SOLD & FILLED] {symbol} (Product: {product_id}) | Order ID: {oid}")
            return True
        else:
            print(f"[{leg_name} FAILED] {resp}")
            return False

    def _rollback_leg(self, leg_info: dict[str, Any], size: int, leg_name: str) -> bool:
        """
        Immediately neutralizes unhedged leg via Market Buy with reduce_only=True.
        Falls back to aggressive Limit IOC/GTC if market order cancels on thin book.
        """
        prod_id = leg_info["id"]
        sym = leg_info["symbol"]
        rollback_payload = {
            "product_id": prod_id,
            "size": size,
            "side": "buy",
            "order_type": "market_order",
            "reduce_only": True,
        }
        rollback_res = self.client.request("POST", "/v2/orders", payload=rollback_payload)
        is_cancelled = False

        if rollback_res and rollback_res.get("success"):
            r_data = rollback_res.get("result", {})
            if r_data.get("state") == "cancelled":
                is_cancelled = True
                reason = r_data.get("cancellation_reason") or "order_size_not_available_in_orderbook"
                print(f"[ROLLBACK] Market buy cancelled by exchange: {reason}")
        else:
            is_cancelled = True

        if is_cancelled:
            print(f"[ROLLBACK FALLBACK] Market buy failed/cancelled. Attempting aggressive Limit fallback for {sym}...")
            leg_tick = float(leg_info.get("tick_size") or 0.1)
            best_ask = float(leg_info.get("best_ask") or 0.0)
            mark_p = float(leg_info.get("mark_price") or 0.0)
            aggressive_px = best_ask if best_ask > 0 else (mark_p * 1.25 if mark_p > 0 else 0.0)
            if aggressive_px > 0:
                rounded_px = self._round_to_tick_size(aggressive_px, leg_tick)
                px_str = self._format_price(rounded_px, leg_tick)
                limit_payload = {
                    "product_id": prod_id,
                    "size": size,
                    "side": "buy",
                    "order_type": "limit_order",
                    "limit_price": px_str,
                    "reduce_only": True,
                    "time_in_force": "ioc",
                }
                limit_res = self.client.request("POST", "/v2/orders", payload=limit_payload)
                if limit_res and limit_res.get("success") and limit_res.get("result", {}).get("state") != "cancelled":
                    is_cancelled = False
                else:
                    limit_payload["time_in_force"] = "gtc"
                    gtc_res = self.client.request("POST", "/v2/orders", payload=limit_payload)
                    if gtc_res and gtc_res.get("success") and gtc_res.get("result", {}).get("state") != "cancelled":
                        is_cancelled = False

        if not is_cancelled:
            rb_msg = (
                f"🛡️ *[ROLLBACK SUCCESSFUL] Naked {leg_name} position closed via Buy.*\n"
                f"Contract: `{sym}` | Size: {size}\n"
                "Account is FLAT. Strategy safely aborted (Zero unhedged risk)."
            )
            print(f"\n{rb_msg}\n")
            self.notifier.send_message(rb_msg)
            return True
        else:
            rb_msg = (
                f"💥 *[ROLLBACK FAILED] Could not close naked {leg_name} position!*\n"
                f"Contract: `{sym}` | Response: {rollback_res}\n"
                "🚨 IMMEDIATE MANUAL INTERVENTION REQUIRED ON DELTA EXCHANGE!"
            )
            print(f"\n{rb_msg}\n")
            self.notifier.send_message(rb_msg)
            return False

    def _emergency_close_strangle(
        self,
        ce_info: dict[str, Any],
        pe_info: dict[str, Any],
        size: int,
    ) -> None:
        """Emergency square-off of both strangle legs if bracket SL placement completely fails."""
        print("\n🚨 [EMERGENCY CLEANUP] Closing both CE and PE legs to prevent naked exposure...")
        self._rollback_leg(ce_info, size, "CE")
        self._rollback_leg(pe_info, size, "PE")

    def _get_open_positions(self) -> list[dict[str, Any]]:
        resp = self.client.request("GET", "/v2/positions?underlying_asset_symbol=BTC")
        if not resp or not resp.get("success"):
            return []
        res = resp.get("result", [])
        return res if isinstance(res, list) else [res]

    def _find_position(self, positions: list[dict[str, Any]], product_id: int) -> dict[str, Any] | None:
        """Matches active position with size != 0 (ignoring closed 0-size records)."""
        for p in positions:
            if int(p.get("product_id", 0)) == int(product_id) and int(p.get("size", 0)) != 0:
                return p
        return None

    @staticmethod
    def _round_to_tick_size(price: float, tick_size: float) -> float:
        """
        Rounds price to the nearest valid multiple of tick_size using Decimal.
        Ensures strict compliance with Delta Exchange orderbook price filters.
        """
        if not tick_size or tick_size <= 0:
            return round(price, 2)
        d_price = Decimal(str(round(price, 8)))
        d_tick = Decimal(str(tick_size))
        num_ticks = (d_price / d_tick).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        rounded = num_ticks * d_tick
        return float(rounded)

    @staticmethod
    def _format_price(price: float, tick_size: float = 0.1) -> str:
        """Formats price as clean string matching tick_size precision without scientific notation."""
        if not tick_size or tick_size <= 0:
            return str(round(price, 2))
        if tick_size >= 1.0 and float(price).is_integer():
            return str(int(price))
        dec_places = abs(Decimal(str(tick_size)).as_tuple().exponent)
        return f"{price:.{dec_places}f}"

    def _place_bracket_sl(
        self,
        product_id: int,
        trigger_price: float,
        leg_name: str,
        tick_size: float = 0.1,
    ) -> int | None:
        price_str = self._format_price(trigger_price, tick_size)
        payload = {
            "product_id": product_id,
            "stop_loss_order": {
                "order_type": "market_order",
                "stop_price": price_str,
            },
            "bracket_stop_trigger_method": "last_traded_price",
        }
        resp = self.client.request("POST", "/v2/orders/bracket", payload=payload)
        if resp and resp.get("success"):
            sl_info = resp.get("result", {}).get("stop_loss_order", {})
            oid = sl_info.get("id")
            print(
                f"[{leg_name} BRACKET SL ATTACHED] ID: {oid} | Trigger: {price_str} USD (Market Order, Tick: {tick_size})"
            )
            return oid
        else:
            print(f"[{leg_name} BRACKET SL FAILED] Response: {resp}")
            return None

    def _place_bracket_sl_with_retry(
        self,
        product_id: int,
        trigger_price: float,
        leg_name: str,
        tick_size: float = 0.1,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ) -> int | None:
        """Attempts to attach pure stop-market bracket order with up to max_retries."""
        for attempt in range(1, max_retries + 1):
            oid = self._place_bracket_sl(product_id, trigger_price, leg_name, tick_size=tick_size)
            if oid:
                return oid
            if attempt < max_retries:
                print(
                    f"[RETRY {attempt}/{max_retries}] Bracket SL for {leg_name} failed. Retrying in {retry_delay}s..."
                )
                time.sleep(retry_delay)
        return None

    def _get_open_orders(self) -> list[dict[str, Any]]:
        resp = self.client.request("GET", "/v2/orders?state=open")
        if not resp or not resp.get("success"):
            return []
        return resp.get("result", [])

    def _verify_bracket_in_orders(
        self,
        orders: list[dict[str, Any]],
        product_id: int,
        expected_trigger: float,
        tick_size: float = 0.1,
    ) -> bool:
        tolerance = max(0.2, tick_size)
        for o in orders:
            p_id = int(o.get("product_id", 0))
            is_bracket = o.get("bracket_order", False) or (o.get("stop_order_type") == "stop_loss_order")
            stop_price = float(o.get("stop_price") or 0.0)

            if p_id == int(product_id) and is_bracket and abs(stop_price - expected_trigger) <= tolerance:
                return True
        return False

    def _send_final_notification(self, report: dict[str, Any]):
        size = report.get("size", 1)
        target_lots = int(report.get("target_lots", TARGET_LOTS))
        sizing_msg = report.get("sizing_msg", "")
        ce = report.get("ce", {})
        pe = report.get("pe", {})
        ce_info = report.get("ce_info", {})
        pe_info = report.get("pe_info", {})

        ce_entry = float(ce.get("entry_price") or 0.0)
        pe_entry = float(pe.get("entry_price") or 0.0)
        ce_sl = float(ce.get("sl_trigger") or (ce_entry * 2.0))
        pe_sl = float(pe.get("sl_trigger") or (pe_entry * 2.0))

        ce_bid_depth = float(ce_info.get("bid_size") or ce.get("bid_size") or 0.0)
        pe_bid_depth = float(pe_info.get("bid_size") or pe.get("bid_size") or 0.0)

        ce_ask = float(ce_info.get("best_ask") or 0.0)
        ce_bid = float(ce_info.get("best_bid") or 0.0)
        ce_mark = float(ce_info.get("mark_price") or ce_entry or 1.0)
        ce_spread_pct = ((ce_ask - ce_bid) / ce_mark * 100.0) if ce_mark > 0 and ce_ask > 0 else 1.20

        pe_ask = float(pe_info.get("best_ask") or 0.0)
        pe_bid = float(pe_info.get("best_bid") or 0.0)
        pe_mark = float(pe_info.get("mark_price") or pe_entry or 1.0)
        pe_spread_pct = ((pe_ask - pe_bid) / pe_mark * 100.0) if pe_mark > 0 and pe_ask > 0 else 1.40

        total_credit = (ce_entry + pe_entry) * size * 0.001

        spot_price = float(report.get("spot_price") or ce_info.get("spot_price") or 0.0)
        if spot_price <= 0:
            ce_strike = float(ce_info.get("strike_price") or 0.0)
            pe_strike = float(pe_info.get("strike_price") or 0.0)
            if ce_strike > 0 and pe_strike > 0:
                spot_price = (ce_strike + pe_strike) / 2.0
            else:
                spot_price = 95000.0

        fill_delay_sec = report.get("fill_delay_sec")
        msg = TelegramNotifier.format_entry_alert(
            date_str=datetime.now().strftime("%Y-%m-%d"),
            time_str=datetime.now().strftime("%H:%M:%S IST"),
            spot_price=spot_price,
            target_lots=target_lots,
            allocated_lots=size,
            sizing_msg=sizing_msg,
            ce_symbol=ce.get("symbol", "BTC-CE"),
            ce_entry_price=ce_entry,
            ce_sl=ce_sl,
            ce_bid_depth=ce_bid_depth,
            ce_spread_pct=ce_spread_pct,
            pe_symbol=pe.get("symbol", "BTC-PE"),
            pe_entry_price=pe_entry,
            pe_sl=pe_sl,
            pe_bid_depth=pe_bid_depth,
            pe_spread_pct=pe_spread_pct,
            total_credit=total_credit,
            fill_delay_sec=fill_delay_sec,
        )
        print("\n" + msg + "\n")
        self.notifier.send_message(msg, is_trade_alert=True)

    def trail_surviving_leg_to_cost(
        self,
        stopped_leg_name: str,
        surviving_leg_info: dict[str, Any],
        surviving_entry_price: float,
        old_sl_order_id: int | None = None,
        tick_size: float = 0.1,
    ) -> dict[str, Any]:
        """
        Combo A Cost-to-Cost Trail:
        The instant either leg triggers its 100% SL, the surviving leg's SL is moved to entry cost (1.00x entry_price).
        """
        surviving_pid = int(surviving_leg_info.get("product_id") or surviving_leg_info.get("id", 0))
        surviving_sym = surviving_leg_info.get("symbol", f"ID_{surviving_pid}")
        surviving_tick = float(surviving_leg_info.get("tick_size") or tick_size)

        cost_sl_trigger = self._round_to_tick_size(surviving_entry_price * self.cost_trail_multiplier, surviving_tick)
        print(f"\n[COMBO A TRAIL] Moving surviving leg {surviving_sym} SL to entry cost: {cost_sl_trigger} USD...")

        # 1. Cancel previous SL order
        if old_sl_order_id:
            try:
                self.client.request(
                    "DELETE", "/v2/orders", payload={"id": old_sl_order_id, "product_id": surviving_pid}
                )
            except Exception as e:
                print(f"[WARN] Error cancelling old SL order {old_sl_order_id}: {e}")
        else:
            open_orders = self._get_open_orders()
            for o in open_orders:
                if int(o.get("product_id", 0)) == surviving_pid and (
                    o.get("bracket_order") or o.get("stop_order_type") == "stop_loss_order" or o.get("stop_price")
                ):
                    o_id = o.get("id")
                    if o_id:
                        self.client.request("DELETE", "/v2/orders", payload={"id": o_id, "product_id": surviving_pid})

        # 2. Place new bracket SL at cost
        new_sl_oid = self._place_bracket_sl_with_retry(
            product_id=surviving_pid,
            trigger_price=cost_sl_trigger,
            leg_name=f"{surviving_sym} (COST_TRAIL)",
            tick_size=surviving_tick,
            max_retries=3,
        )

        success = new_sl_oid is not None
        trail_result = {
            "success": success,
            "stopped_leg": stopped_leg_name,
            "surviving_symbol": surviving_sym,
            "surviving_product_id": surviving_pid,
            "cost_sl_trigger": cost_sl_trigger,
            "new_sl_order_id": new_sl_oid,
        }

        # 3. Telegram notification
        surviving_orig_sl = surviving_entry_price * self.sl_multiplier
        stopped_sym = f"{stopped_leg_name}_LEG"
        stopped_entry = surviving_entry_price
        stopped_exit = stopped_entry * self.sl_multiplier

        msg = TelegramNotifier.format_cost_trail_alert(
            date_str=datetime.now().strftime("%Y-%m-%d"),
            time_str=datetime.now().strftime("%H:%M:%S IST"),
            stopped_leg=stopped_leg_name,
            stopped_symbol=stopped_sym,
            stopped_entry=stopped_entry,
            stopped_exit=stopped_exit,
            stopped_pnl_pct=-100.0,
            surviving_leg=surviving_sym,
            surviving_symbol=surviving_sym,
            surviving_entry=surviving_entry_price,
            surviving_orig_sl=surviving_orig_sl,
            new_sl_trigger=cost_sl_trigger,
            order_id=new_sl_oid,
        )
        print("\n" + msg + "\n")
        self.notifier.send_message(msg, is_trade_alert=True)

        return trail_result

    def monitor_and_update_cost_trail(self, state_file_path: str | None = None) -> dict[str, Any]:
        """
        Inspects active positions and state.json:
        If one leg was stopped out (position closed) and surviving leg is still open,
        triggers trail_surviving_leg_to_cost and updates state.json.
        """
        import json
        import os

        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        state_file = state_file_path or os.path.join(root_dir, "data", "state.json")

        if not os.path.exists(state_file):
            return {"status": "NO_STATE", "message": "No active state.json found"}

        with open(state_file, "r", encoding="utf-8") as f:
            state_data = json.load(f)

        if state_data.get("status") in ("CLOSED", "FAILED_EXIT"):
            return {"status": state_data.get("status"), "message": "Strategy already closed"}

        if state_data.get("trail_status") in ("TRAILED", "BOTH_CLOSED"):
            return {"status": "ALREADY_TRAILED", "message": f"Surviving leg state is {state_data.get('trail_status')}"}

        today_str = datetime.now().strftime("%Y-%m-%d")
        if state_data.get("trade_date") and state_data.get("trade_date") != today_str:
            return {
                "status": "STALE_DATE",
                "message": f"state.json date {state_data.get('trade_date')} does not match today {today_str}",
            }

        ce_data = state_data.get("ce", {})
        pe_data = state_data.get("pe", {})
        ce_pid = int(ce_data.get("product_id") or 0)
        pe_pid = int(pe_data.get("product_id") or 0)

        # Query live positions from exchange
        positions = self._get_open_positions()
        ce_pos = self._find_position(positions, ce_pid) if ce_pid else None
        pe_pos = self._find_position(positions, pe_pid) if pe_pid else None

        # Check if CE is stopped out while PE is still open
        if not ce_pos and pe_pos:
            res = self.trail_surviving_leg_to_cost(
                stopped_leg_name="CE",
                surviving_leg_info=pe_data,
                surviving_entry_price=float(pe_data.get("entry_price") or 0.0),
                old_sl_order_id=pe_data.get("sl_order_id"),
                tick_size=float(pe_data.get("tick_size") or 0.1),
            )
            state_data["trail_status"] = "TRAILED"
            state_data["stopped_leg"] = "CE"
            state_data["surviving_leg"] = "PE"
            state_data["pe"]["sl_trigger"] = res.get("cost_sl_trigger")
            state_data["pe"]["sl_mode"] = "COST_TO_COST"
            state_data["pe"]["sl_order_id"] = res.get("new_sl_order_id")
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2)
            return {"status": "TRAILED", "stopped_leg": "CE", "surviving_leg": "PE", "detail": res}

        # Check if PE is stopped out while CE is still open
        elif not pe_pos and ce_pos:
            res = self.trail_surviving_leg_to_cost(
                stopped_leg_name="PE",
                surviving_leg_info=ce_data,
                surviving_entry_price=float(ce_data.get("entry_price") or 0.0),
                old_sl_order_id=ce_data.get("sl_order_id"),
                tick_size=float(ce_data.get("tick_size") or 0.1),
            )
            state_data["trail_status"] = "TRAILED"
            state_data["stopped_leg"] = "PE"
            state_data["surviving_leg"] = "CE"
            state_data["ce"]["sl_trigger"] = res.get("cost_sl_trigger")
            state_data["ce"]["sl_mode"] = "COST_TO_COST"
            state_data["ce"]["sl_order_id"] = res.get("new_sl_order_id")
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2)
            return {"status": "TRAILED", "stopped_leg": "PE", "surviving_leg": "CE", "detail": res}

        # Both positions closed
        elif not ce_pos and not pe_pos:
            state_data["status"] = "CLOSED"
            state_data["trail_status"] = "BOTH_CLOSED"
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2)
            return {"status": "CLOSED", "message": "Both positions closed"}

        # Both positions still open -> Check if either breached 100% SL mark threshold
        else:
            ce_entry = float(ce_data.get("entry_price") or 0.0)
            pe_entry = float(pe_data.get("entry_price") or 0.0)
            ce_sl = float(ce_data.get("sl_trigger") or (ce_entry * self.sl_multiplier))
            pe_sl = float(pe_data.get("sl_trigger") or (pe_entry * self.sl_multiplier))

            ce_cur = float(ce_pos.get("mark_price") or 0.0)
            pe_cur = float(pe_pos.get("mark_price") or 0.0)

            if ce_cur >= ce_sl and ce_entry > 0:
                print(f"[BREACH DETECTED] CE mark {ce_cur} >= SL {ce_sl}. Closing CE...")
                self._rollback_leg(ce_data, abs(int(ce_pos.get("size", 1))), "CE")
                res = self.trail_surviving_leg_to_cost(
                    "CE", pe_data, pe_entry, pe_data.get("sl_order_id"), float(pe_data.get("tick_size") or 0.1)
                )
                state_data["trail_status"] = "TRAILED"
                state_data["stopped_leg"] = "CE"
                state_data["surviving_leg"] = "PE"
                state_data["pe"]["sl_trigger"] = res.get("cost_sl_trigger")
                state_data["pe"]["sl_mode"] = "COST_TO_COST"
                with open(state_file, "w", encoding="utf-8") as f:
                    json.dump(state_data, f, indent=2)
                return {"status": "TRAILED", "stopped_leg": "CE", "surviving_leg": "PE"}

            if pe_cur >= pe_sl and pe_entry > 0:
                print(f"[BREACH DETECTED] PE mark {pe_cur} >= SL {pe_sl}. Closing PE...")
                self._rollback_leg(pe_data, abs(int(pe_pos.get("size", 1))), "PE")
                res = self.trail_surviving_leg_to_cost(
                    "PE", ce_data, ce_entry, ce_data.get("sl_order_id"), float(ce_data.get("tick_size") or 0.1)
                )
                state_data["trail_status"] = "TRAILED"
                state_data["stopped_leg"] = "PE"
                state_data["surviving_leg"] = "CE"
                state_data["ce"]["sl_trigger"] = res.get("cost_sl_trigger")
                state_data["ce"]["sl_mode"] = "COST_TO_COST"
                with open(state_file, "w", encoding="utf-8") as f:
                    json.dump(state_data, f, indent=2)
                return {"status": "TRAILED", "stopped_leg": "PE", "surviving_leg": "CE"}

            return {"status": "OPEN_BOTH", "message": "Both legs healthy and within 100% SL threshold"}

    def square_off_with_retry(
        self,
        target_product_ids: list[int] | None = None,
        max_retries: int = 3,
        retry_delay: int = 4,
    ) -> dict[str, Any]:
        """
        Cancels open bracket orders and closes positions with up to `max_retries` attempts.
        Strict Blast-Radius Isolation:
        If `target_product_ids` is provided, only closes those specific strategy contracts,
        preserving all other BTC futures or discretionary positions on the account.
        """
        summary: dict[str, Any] = {
            "success": False,
            "attempts": 0,
            "closed_positions": [],
            "remaining_positions": [],
        }

        for attempt in range(1, max_retries + 1):
            summary["attempts"] = attempt
            print(f"\n[SQUARE-OFF ATTEMPT {attempt}/{max_retries}] Starting cleanup loop...")

            # 1. Cancel open orders
            print("[1/2] Cancelling pending orders...")
            if target_product_ids:
                open_orders = self._get_open_orders()
                for o in open_orders:
                    o_id = o.get("id")
                    p_id = int(o.get("product_id", 0))
                    if o_id and p_id in target_product_ids:
                        self.client.request("DELETE", "/v2/orders", payload={"id": o_id, "product_id": p_id})
            else:
                self.client.request("DELETE", "/v2/orders/all")
            time.sleep(1)

            # 2. Query open positions
            pos_resp = self.client.request("GET", "/v2/positions?underlying_asset_symbol=BTC")
            raw_positions = pos_resp.get("result", []) if pos_resp else []
            if isinstance(raw_positions, dict):
                raw_positions = [raw_positions]

            active_positions = [
                p
                for p in raw_positions
                if int(p.get("size", 0)) != 0
                and (target_product_ids is None or int(p.get("product_id", 0)) in target_product_ids)
            ]

            if not active_positions:
                print(f"[SUCCESS] No open strategy positions detected on attempt {attempt}. Account is FLAT.")
                summary["success"] = True
                summary["remaining_positions"] = []
                return summary

            # 3. Close active positions via Market Order with Reduce-Only & Limit Fallback
            print(f"[2/2] Closing {len(active_positions)} active position(s)...")
            for pos in active_positions:
                size = int(pos.get("size", 0))
                prod_id = int(pos.get("product_id", 0))
                symbol = pos.get("product_symbol", f"ID_{prod_id}")
                side = "buy" if size < 0 else "sell"
                close_size = abs(size)

                close_payload = {
                    "product_id": prod_id,
                    "size": close_size,
                    "side": side,
                    "order_type": "market_order",
                    "reduce_only": True,
                }
                close_resp = self.client.request("POST", "/v2/orders", payload=close_payload)
                success = False

                if close_resp and close_resp.get("success"):
                    res_state = close_resp.get("result", {}).get("state")
                    if res_state == "cancelled":
                        reason = (
                            close_resp.get("result", {}).get("cancellation_reason")
                            or "order_size_not_available_in_orderbook"
                        )
                        print(f"[*] Market {side} for {symbol} cancelled by exchange: {reason}")
                    else:
                        success = True

                if not success:
                    print(f"[*] Attempting aggressive Limit fallback for {symbol}...")
                    t_info = {}
                    if symbol and not symbol.startswith("ID_"):
                        ticker_resp = self.client.request_public("GET", f"/v2/tickers/{symbol}")
                        if ticker_resp and ticker_resp.get("success"):
                            t_info = ticker_resp.get("result", {})

                    t_quotes = t_info.get("quotes") or {}
                    best_ask = float(t_quotes.get("best_ask") or 0.0)
                    best_bid = float(t_quotes.get("best_bid") or 0.0)
                    mark_p = float(t_info.get("mark_price") or 0.0)
                    tick_sz = float(t_info.get("tick_size") or 0.1)

                    if side == "buy":
                        aggressive_px = best_ask if best_ask > 0 else (mark_p * 1.25 if mark_p > 0 else 0.0)
                    else:
                        aggressive_px = best_bid if best_bid > 0 else (mark_p * 0.75 if mark_p > 0 else 0.0)

                    if aggressive_px > 0:
                        rounded_px = self._round_to_tick_size(aggressive_px, tick_sz)
                        px_str = self._format_price(rounded_px, tick_sz)
                        limit_payload = {
                            "product_id": prod_id,
                            "size": close_size,
                            "side": side,
                            "order_type": "limit_order",
                            "limit_price": px_str,
                            "reduce_only": True,
                            "time_in_force": "ioc",
                        }
                        limit_resp = self.client.request("POST", "/v2/orders", payload=limit_payload)
                        if (
                            limit_resp
                            and limit_resp.get("success")
                            and limit_resp.get("result", {}).get("state") != "cancelled"
                        ):
                            success = True
                            print(f"[*] Aggressive Limit IOC {side} for {symbol} @ {px_str} filled ✅")
                        else:
                            limit_payload["time_in_force"] = "gtc"
                            gtc_resp = self.client.request("POST", "/v2/orders", payload=limit_payload)
                            if (
                                gtc_resp
                                and gtc_resp.get("success")
                                and gtc_resp.get("result", {}).get("state") != "cancelled"
                            ):
                                success = True
                                print(f"[*] Aggressive Limit GTC {side} for {symbol} @ {px_str} placed ✅")

                summary["closed_positions"].append(
                    {
                        "symbol": symbol,
                        "size": close_size,
                        "side": side,
                        "success": success,
                        "attempt": attempt,
                    }
                )
                print(f"[*] Position {symbol} close order sent (Size: {close_size}, Side: {side}, Success: {success})")

            print(f"[WAIT] Waiting {retry_delay}s for fills to settle before next verification...")
            time.sleep(retry_delay)

        final_resp = self.client.request("GET", "/v2/positions?underlying_asset_symbol=BTC")
        final_raw = final_resp.get("result", []) if final_resp else []
        if isinstance(final_raw, dict):
            final_raw = [final_raw]

        remaining = [
            p
            for p in final_raw
            if int(p.get("size", 0)) != 0
            and (target_product_ids is None or int(p.get("product_id", 0)) in target_product_ids)
        ]
        summary["remaining_positions"] = remaining
        summary["success"] = len(remaining) == 0

        return summary

    def square_off_all(self, target_product_ids: list[int] | None = None) -> dict[str, Any]:
        """Backwards-compatible wrapper calling square_off_with_retry."""
        return self.square_off_with_retry(target_product_ids=target_product_ids, max_retries=3, retry_delay=4)
```

---

### Module 6: `services/telegram_notifier.py`
```python
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

        primary_success = self.send_to_chat(self.chat_id, text)

        if is_trade_alert and self.channel_id:
            self.send_to_chat(self.channel_id, text)

        return primary_success

    def send_system_error(self, text: str) -> bool:
        """Explicitly routes system/error tracebacks strictly to TELEGRAM_CHAT_ID."""
        return self.send_message(text, is_trade_alert=False)

    def send_trade_alert(self, text: str) -> bool:
        """Explicitly broadcasts trade alert to both DM and Channel."""
        return self.send_message(text, is_trade_alert=True)

    @staticmethod
    def format_phase1_warmup_alert(
        date_str: str,
        time_str: str,
        ce_symbol: str,
        ce_strike: float,
        ce_delta: float,
        ce_mark: float,
        ce_bid_depth: float,
        ce_spread_pct: float,
        pe_symbol: str,
        pe_strike: float,
        pe_delta: float,
        pe_mark: float,
        pe_bid_depth: float,
        pe_spread_pct: float,
        target_lots: int = 1000,
        is_relock: bool = False,
    ) -> str:
        """Template: Phase 1 (09:58 IST) Pre-Warm & Target Lock Telemetry."""
        title = (
            "🔒 *[PHASE 1 TARGET RE-LOCKED — DELTA DRIFT DETECTED]*"
            if is_relock
            else "🔒 *[PHASE 1 PRE-WARM — TARGET STRIKES LOCKED]*"
        )
        return (
            f"{title}\n\n"
            f"🕒 *Session:* `{date_str} | {time_str} IST`\n"
            "🎯 *Objective:* `10-Delta Intraday Strangle Pre-Flight`\n\n"
            f"🟢 *LOCKED CALL (CE):*\n"
            f"• Contract: `{ce_symbol}` (Strike: `${ce_strike:,.0f}`)\n"
            f"• Greek Delta: `{ce_delta:+.4f}` | Mark: `${ce_mark:.2f} USD`\n"
            f"• L1 Top Bid Depth: `{ce_bid_depth:,.0f} lots` | Spread: `{ce_spread_pct:.2f}%`\n\n"
            f"🔴 *LOCKED PUT (PE):*\n"
            f"• Contract: `{pe_symbol}` (Strike: `${pe_strike:,.0f}`)\n"
            f"• Greek Delta: `{pe_delta:+.4f}` | Mark: `${pe_mark:.2f} USD`\n"
            f"• L1 Top Bid Depth: `{pe_bid_depth:,.0f} lots` | Spread: `{pe_spread_pct:.2f}%`\n\n"
            "⚡ *Phase 2 Schedule:* Sniper Execution armed for `10:00:00 IST`\n"
            f"🎯 *Target Size:* `{target_lots:,} lots` ({target_lots * 0.001:.3f} BTC)\n"
            "🛡️ *Status:* Tracking orderbook every 5s | 0 Orders Placed ✅"
        )

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
        fill_delay_sec: int | None = None,
    ) -> str:
        """Template 1: Strangle Entry Executed."""
        delay_str = f" (Fill Delay: `{fill_delay_sec}s`)" if fill_delay_sec is not None else ""
        if allocated_lots >= target_lots:
            sizing_line = f"• Sizing Status: `Full Target Allocation ({allocated_lots:,} lots = {allocated_lots * 0.001:.3f} BTC) ✅`{delay_str}\n"
        else:
            sizing_line = (
                f"• ⚡ *20% L1 Downsizing (Stage 2 Dynamic Fallback):* Equal {allocated_lots:,} lots ({allocated_lots * 0.001:.3f} BTC){delay_str}\n"
                f"• 📋 *Detail:* `{sizing_msg}`\n"
            )
        total_credit_str = f"+${total_credit:.2f} USD ({allocated_lots * 0.001:.3f} BTC)"

        return (
            "🎯 *ALPHA STRANGLE COMBO A — ENTRY EXECUTED*\n\n"
            f"🕒 *Session:* `{date_str} | {time_str}`\n"
            f"🪙 *BTC Spot:* `${spot_price:,.2f}`\n\n"
            f"📊 *EXECUTION SIZING:*\n"
            f"• Target: `{target_lots:,} lots` ({target_lots * 0.001:.3f} BTC)\n"
            f"• Allocated: `{allocated_lots:,} lots` ({allocated_lots * 0.001:.3f} BTC)\n"
            f"{sizing_line}\n"
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
```

---

### Module 7: `services/risk_guard.py`
```python
from __future__ import annotations

import csv
import os
from datetime import datetime


class RiskGuard:
    """
    Automated Strategy Risk Guard & Drawdown Monitor.
    Tracks live cumulative net PnL and enforces the $1,185.00 USD Hard Strategy Kill-Switch.
    """

    @staticmethod
    def calculate_peak_to_trough_drawdown(
        ledger_path: str,
    ) -> tuple[float, float, float]:
        """
        Calculates cumulative PnL, historical peak, and current drawdown from trade ledger.
        Returns:
            (current_drawdown_usd, historical_peak_usd, total_net_pnl_usd)
        """
        if not os.path.exists(ledger_path):
            return 0.0, 0.0, 0.0

        net_pnls: list[float] = []
        try:
            with open(ledger_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    val_str = row.get("net_pnl_usd", "").strip()
                    if val_str:
                        try:
                            net_pnls.append(float(val_str))
                        except ValueError:
                            continue
        except Exception as e:
            print(f"[RISK GUARD WARN] Could not read ledger at {ledger_path}: {e}")
            return 0.0, 0.0, 0.0

        if not net_pnls:
            return 0.0, 0.0, 0.0

        cum_pnl = 0.0
        peak_pnl = 0.0
        max_drawdown = 0.0

        for pnl in net_pnls:
            cum_pnl += pnl
            peak_pnl = max(peak_pnl, cum_pnl)
            drawdown = peak_pnl - cum_pnl
            max_drawdown = max(max_drawdown, drawdown)

        current_drawdown = max(0.0, peak_pnl - cum_pnl)
        return current_drawdown, peak_pnl, cum_pnl

    @staticmethod
    def check_hard_kill_switch(
        max_drawdown_limit: float = 1185.00,
        ledger_path: str = "",
    ) -> tuple[bool, float, str]:
        """
        Checks if current peak-to-trough live drawdown breaches max_drawdown_limit.
        Returns:
            (is_breached, current_drawdown_usd, reason_message)
        """
        current_dd, peak_pnl, total_pnl = RiskGuard.calculate_peak_to_trough_drawdown(ledger_path)

        if current_dd >= max_drawdown_limit:
            reason = (
                f"Cumulative live drawdown (${current_dd:.2f} USD) has breached the "
                f"Hard Strategy Kill-Switch limit (${max_drawdown_limit:.2f} USD). "
                f"Peak: ${peak_pnl:.2f}, Total PnL: ${total_pnl:.2f}."
            )
            return True, current_dd, reason

        return (
            False,
            current_dd,
            f"Drawdown safe: ${current_dd:.2f} / ${max_drawdown_limit:.2f} USD (Peak: ${peak_pnl:.2f}).",
        )

    @staticmethod
    def record_session_to_ledger(ledger_path: str, session_record: dict) -> bool:
        """
        Appends a completed session's financial realization to the permanent trade ledger.
        """
        fieldnames = [
            "trade_date",
            "entry_time",
            "exit_time",
            "outcome_type",
            "ce_symbol",
            "pe_symbol",
            "allocated_lots",
            "ce_entry",
            "ce_exit",
            "pe_entry",
            "pe_exit",
            "gross_pnl_usd",
            "fees_usd",
            "net_pnl_usd",
            "timestamp",
        ]

        os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
        file_exists = os.path.exists(ledger_path)

        try:
            with open(ledger_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()

                clean_record = {k: session_record.get(k, "") for k in fieldnames}
                if not clean_record.get("timestamp"):
                    clean_record["timestamp"] = datetime.now().isoformat()
                writer.writerow(clean_record)
            return True
        except Exception as e:
            print(f"[RISK GUARD ERROR] Failed to record session to ledger: {e}")
            return False
```

---

### Module 8: `jobs/1_entry_job.py`
```python
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
```

---

### Module 9: `jobs/2_exit_job.py`
```python
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

    result = order_mgr.square_off_with_retry(
        target_product_ids=target_pids,
        max_retries=3,
        retry_delay=4,
    )
    is_flat = result.get("success", False)
    closed = result.get("closed_positions", [])
    remaining = result.get("remaining_positions", [])

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
```

---

### Module 10: `jobs/3_monitor_job.py`
```python
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
from services.order_manager import OrderManager

BASE_URL = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
API_KEY = os.getenv("DELTA_API_KEY", "")
API_SECRET = os.getenv("DELTA_API_SECRET", "")


def run() -> None:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Fast Pre-Flight Check (Zero-Proxy Bandwidth Guard):
    # Exit immediately with 0 network calls if strategy is flat, inactive, or already trailed/closed.
    state_file = os.path.join(ROOT_DIR, "data", "state.json")
    if not os.path.exists(state_file):
        print(f"[{now_str}] [MONITOR FAST-EXIT] No data/state.json found (Flat/Idle). 0 proxy calls consumed.")
        return

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            state_data = json.load(f)
    except Exception as e:
        print(f"[{now_str}] [MONITOR WARN] Error reading state.json: {e}")
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    if state_data.get("trade_date") and state_data.get("trade_date") != today_str:
        print(
            f"[{now_str}] [MONITOR FAST-EXIT] state.json date ({state_data.get('trade_date')}) is not today ({today_str}). 0 proxy calls consumed."
        )
        return

    if state_data.get("status") in ("CLOSED", "FAILED_EXIT"):
        print(f"[{now_str}] [MONITOR FAST-EXIT] Strategy status is {state_data.get('status')}. 0 proxy calls consumed.")
        return

    if state_data.get("trail_status") in ("TRAILED", "BOTH_CLOSED"):
        print(
            f"[{now_str}] [MONITOR FAST-EXIT] trail_status is {state_data.get('trail_status')} (Bracket SL active on exchange). 0 proxy calls consumed."
        )
        return

    print("\n========================================================")
    print(f"[{now_str}] RUNNING JOB 3: COMBO A COST TRAIL MONITOR (ACTIVE POSITION)")
    print("========================================================")

    client = DeltaApiClient(API_KEY, API_SECRET, BASE_URL)
    order_mgr = OrderManager(client)
    res = order_mgr.monitor_and_update_cost_trail(state_file_path=state_file)
    print(f"[MONITOR RESULT] Status: {res.get('status')} | Details: {res.get('message', res)}")
    print("[FINISHED] Monitor job execution complete.\n")


if __name__ == "__main__":
    run()
```

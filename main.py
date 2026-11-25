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
    load_env()
    base_url = os.getenv("DELTA_BASE_URL", BASE_URL)
    api_key = os.getenv("DELTA_API_KEY", API_KEY)
    api_secret = os.getenv("DELTA_API_SECRET", API_SECRET)

    print("\n" + "=" * 60)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DELTA ALPHA STRANGLE BOT — STATUS CHECK")
    print("=" * 60)

    print(f"• Base URL: {base_url}")
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

    client = DeltaApiClient(api_key, api_secret, base_url)

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

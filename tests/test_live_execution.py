import os
import sys
import time
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

from config.settings import load_env, setup_proxy
load_env()
proxy_url = setup_proxy()

from core.api_client import DeltaApiClient
from services.delta_calculator import DeltaCalculator
from services.order_manager import OrderManager
from services.notifier import TelegramNotifier

BASE_URL = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
API_KEY = os.getenv("DELTA_API_KEY", "")
API_SECRET = os.getenv("DELTA_API_SECRET", "")

def run_live_execution_test():
    print("=" * 60)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] STARTING LIVE EXECUTION TEST VIA PROXY")
    print(f"Proxy Active: {proxy_url if proxy_url else 'Direct Connection'}")
    print("=" * 60)

    notifier = TelegramNotifier()
    client = DeltaApiClient(API_KEY, API_SECRET, BASE_URL)
    calc = DeltaCalculator(client)
    order_mgr = OrderManager(client)

    # 0. Initial Pre-flight Cleanup (Ensure Clean Slate)
    print("\n[PRE-FLIGHT] Ensuring clean slate (Cancelling lingering orders)...")
    client.request("DELETE", "/v2/orders/all")
    time.sleep(1)

    # 1. Fetch Nearest Expiry 10-Delta Strikes
    print("\n[STEP 1] Fetching 10-Delta Call (CE) & Put (PE) Strikes...")
    ce, pe = calc.get_10_delta_strikes(symbol="BTC", target_delta=0.10)

    if not ce or not pe:
        err_msg = "❌ [TEST ABORTED] 10-Delta strikes fetch nahi ho sake."
        print(err_msg)
        notifier.send_message(err_msg)
        sys.exit(1)

    print(f"[*] Selected CE: {ce['symbol']} (ID: {ce['id']}, Delta: {ce.get('delta')})")
    print(f"[*] Selected PE: {pe['symbol']} (ID: {pe['id']}, Delta: {pe.get('delta')})")

    # Send Step 1 Telegram Alert (Entry Triggering)
    entry_start_msg = (
        "🚀 *[LIVE TEST 1/4] EXECUTING 10-DELTA STRANGLE ENTRY*\n\n"
        f"🟢 *CE Contract:* `{ce['symbol']}`\n"
        f"• Delta: `{ce.get('delta')}` | Strike: `{ce.get('strike_price')}`\n\n"
        f"🔴 *PE Contract:* `{pe['symbol']}`\n"
        f"• Delta: `{pe.get('delta')}` | Strike: `{pe.get('strike_price')}`\n\n"
        f"🌐 *Proxy Routing:* `{os.getenv('PROXY_HOST', 'Direct')}:{os.getenv('PROXY_PORT', '')}` (Active ✅)\n"
        "⚡ Submitting Market Sell orders (1 lot each)..."
    )
    notifier.send_message(entry_start_msg)

    # 2. Execute Entry & Attach 75% Bracket SL with Dual Verification
    print("\n[STEP 2] Executing Market Sell + 10s Rest + 75% Bracket SL...")
    report = order_mgr.execute_strangle_with_dual_verification(ce_info=ce, pe_info=pe, size=1)

    if not report.get("success"):
        err_msg = "❌ [TEST FAILED] Entry ya Bracket SL verify nahi ho saka."
        print(err_msg)
        notifier.send_message(err_msg)
        sys.exit(1)

    ce_entry = report["ce"]["entry_price"]
    ce_sl = report["ce"]["sl_trigger"]
    pe_entry = report["pe"]["entry_price"]
    pe_sl = report["pe"]["sl_trigger"]

    # Send Step 2 Telegram Alert (SL Placed & Verified)
    sl_verified_msg = (
        "🛡️ *[LIVE TEST 2/4] BRACKET STOP-LOSS PLACED & VERIFIED*\n\n"
        f"🟢 *CALL LEG (CE):* `{ce['symbol']}`\n"
        f"• Executed Fill: `{ce_entry} USD`\n"
        f"• 75% Bracket SL: `{ce_sl} USD` (Market Stop Active ✅)\n\n"
        f"🔴 *PUT LEG (PE):* `{pe['symbol']}`\n"
        f"• Executed Fill: `{pe_entry} USD`\n"
        f"• 75% Bracket SL: `{pe_sl} USD` (Market Stop Active ✅)\n\n"
        "✅ Verified in Exchange Orderbook via Static Proxy!"
    )
    notifier.send_message(sl_verified_msg)

    # 3. Wait / Sleep for 120 Seconds (2 Minutes) Holding Phase
    print("\n" + "=" * 60)
    print(">>> [STEP 3] ENTERING 120-SECOND (2 MINUTE) HOLDING PHASE <<<")
    print("=" * 60)

    wait_msg = (
        "⏳ *[LIVE TEST 3/4] HOLDING PHASE STARTED (120 SECONDS)*\n\n"
        "• Holding short strangle positions with active Bracket SL shields.\n"
        "• Timer: `2 Minutes (120s)` countdown started.\n"
        "• Positions will be automatically squared-off after 2 minutes."
    )
    notifier.send_message(wait_msg)

    total_wait = 120
    for remaining in range(total_wait, 0, -10):
        print(f"[*] Holding positions... {remaining} seconds remaining before auto square-off.")
        time.sleep(10)

    print("[*] 120-second hold complete! Initiating square-off...")

    # 4. Square-off all positions & cancel pending orders
    print("\n" + "=" * 60)
    print(">>> [STEP 4] INITIATING COMPLETE SQUARE-OFF & CLEANUP <<<")
    print("=" * 60)

    square_off_res = order_mgr.square_off_all()
    closed = square_off_res.get("closed_positions", [])

    # Allow 5s for settlement
    print("[WAIT] 5 seconds for square-off fills to settle...")
    time.sleep(5)

    # 5. Verify Account is Completely FLAT (0 open positions, 0 open orders)
    print("\n[VERIFICATION] Verifying 0 Open Orders & 0 Open Positions...")
    open_orders_resp = client.request("GET", "/v2/orders?state=open")
    open_orders = open_orders_resp.get("result", []) if open_orders_resp else []

    pos_resp = client.request("GET", "/v2/positions?underlying_asset_symbol=BTC")
    all_positions = pos_resp.get("result", []) if pos_resp else []
    active_positions = [p for p in all_positions if int(p.get("size", 0)) != 0]

    open_orders_count = len(open_orders)
    open_positions_count = len(active_positions)

    print(f"[*] Open Orders Remaining: {open_orders_count}")
    print(f"[*] Open Positions Remaining: {open_positions_count}")

    is_flat = (open_orders_count == 0 and open_positions_count == 0)

    closed_lines = []
    if closed:
        for c in closed:
            closed_lines.append(f"• `{c.get('symbol')}`: Bought back {c.get('size')} lot (Closed)")
    else:
        closed_lines.append("• Positions closed or stopped out.")

    if is_flat:
        final_msg = (
            "🏁 *[LIVE TEST 4/4] COMPLETE SQUARE-OFF CONFIRMED — FLAT*\n\n"
            f"🕒 Completed At: `{datetime.now().strftime('%H:%M:%S IST')}`\n"
            f"🧹 Pending Orders Remaining: `{open_orders_count}` ✅\n"
            f"📊 Open Positions Remaining: `{open_positions_count}` ✅\n\n"
            "*Closed Positions:*\n" + "\n".join(closed_lines) + "\n\n"
            "🛡️ *Final Account State:* 100% FLAT (Zero Exposure)\n"
            "🎉 *All Proxy, Auth, Order & Bracket SL tests PASSED!*"
        )
        print("\n" + final_msg + "\n")
        notifier.send_message(final_msg)
        print(">>> LIVE EXECUTION TEST COMPLETED SUCCESSFULLY! <<<")
    else:
        warn_msg = (
            "⚠️ *[LIVE TEST WARNING] Account NOT completely flat!*\n\n"
            f"Open Orders: {open_orders_count}\n"
            f"Open Positions: {open_positions_count}\n"
            "Please check Delta console manually."
        )
        print("\n" + warn_msg + "\n")
        notifier.send_message(warn_msg)
        sys.exit(1)

if __name__ == "__main__":
    run_live_execution_test()


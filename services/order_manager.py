import time
from typing import Dict, Any, Optional, List
from services.notifier import TelegramNotifier

class OrderManager:
    def __init__(self, api_client):
        self.client = api_client
        self.notifier = TelegramNotifier()

    def execute_strangle_with_dual_verification(self, ce_info: Dict[str, Any], pe_info: Dict[str, Any], size: int = 1) -> Dict[str, Any]:
        """
        1. CE aur PE Market Sell place karta hai.
        2. 10 SECOND REST leta hai.
        3. Real positions fetch karke exact Entry Price nikalta hai.
        4. Har leg par exact 75% PURE BRACKET SL (/v2/orders/bracket) place karta hai.
        5. 10 SECOND REST leta hai.
        6. Open Stop Orders check karke verify karta hai ki 'Bracket - SL' active hai.
        7. Full report Telegram aur console par deliver karta hai.
        """
        report = {
            "ce": {"product_id": ce_info["id"], "symbol": ce_info["symbol"]},
            "pe": {"product_id": pe_info["id"], "symbol": pe_info["symbol"]},
            "success": False
        }

        print("\n==================================================")
        print(">>> STEP 1: EXECUTING MARKET SELL (ENTRY ORDERS) <<<")
        print("==================================================")

        ce_sell_res = self._market_sell(ce_info["id"], size, "CE", ce_info["symbol"])
        if not ce_sell_res:
            err_msg = "❌ [ABORT] CE Sell rejected by exchange. Strategy stopped safely (No positions open)."
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

            # ATOMIC ROLLBACK: Market Buy back the filled CE leg immediately
            rollback_payload = {
                "product_id": ce_info["id"],
                "size": size,
                "side": "buy",
                "order_type": "market_order"
            }
            rollback_res = self.client.request("POST", "/v2/orders", payload=rollback_payload)
            if rollback_res and rollback_res.get("success"):
                rb_msg = (
                    "🛡️ *[ROLLBACK SUCCESSFUL] Naked CE position closed via Market Buy.*\n"
                    f"Contract: `{ce_info['symbol']}` | Size: {size}\n"
                    "Account is FLAT. Strategy safely aborted (Zero unhedged risk)."
                )
            else:
                rb_msg = (
                    "💥 *[ROLLBACK FAILED] Could not close naked CE position!*\n"
                    f"Contract: `{ce_info['symbol']}` | Response: {rollback_res}\n"
                    "🚨 IMMEDIATE MANUAL INTERVENTION REQUIRED ON DELTA EXCHANGE!"
                )
            print(f"\n{rb_msg}\n")
            self.notifier.send_message(rb_msg)
            return report

        # ------------------------------------------------------------------
        # 10 SECOND REST (Exchange Engine Settlement)
        # ------------------------------------------------------------------
        print("\n[WAIT] 10 second ruk rahe hain taaki exchange par positions settle ho sakein...")
        for sec in range(10, 0, -1):
            print(f" -> Position sync in {sec}s...", end="\r")
            time.sleep(1)
        print("\n[SYNC] 10 second poore hue! Ab positions fetch ki ja rahi hain.\n")

        # ------------------------------------------------------------------
        # STEP 2: FETCH REAL ENTRY PRICES FROM POSITIONS
        # ------------------------------------------------------------------
        print(">>> STEP 2: FETCHING REAL POSITIONS DATA <<<")
        positions = self._get_open_positions()

        ce_pos = self._find_position(positions, ce_info["id"])
        pe_pos = self._find_position(positions, pe_info["id"])

        if not ce_pos or not pe_pos:
            err_msg = "[ERROR] Ek ya dono positions table mein nahi mili!"
            print(err_msg)
            self.notifier.send_message(f"⚠️ *DELTA BOT ERROR*\n{err_msg}")
            return report

        ce_entry = float(ce_pos.get("entry_price") or 0.0)
        pe_entry = float(pe_pos.get("entry_price") or 0.0)

        report["ce"]["entry_price"] = ce_entry
        report["pe"]["entry_price"] = pe_entry

        print(f"[*] CE Confirmed: {ce_info['symbol']} | Real Entry: {ce_entry} USD")
        print(f"[*] PE Confirmed: {pe_info['symbol']} | Real Entry: {pe_entry} USD")

        # ------------------------------------------------------------------
        # STEP 3: ATTACH 75% PURE BRACKET STOP-LOSS
        # ------------------------------------------------------------------
        print("\n>>> STEP 3: ATTACHING 75% BRACKET STOP LOSS ORDERS <<<")
        ce_sl_trigger = round(ce_entry * 1.75, 2)
        pe_sl_trigger = round(pe_entry * 1.75, 2)

        report["ce"]["sl_trigger"] = ce_sl_trigger
        report["pe"]["sl_trigger"] = pe_sl_trigger

        print(f"[CE SL Setup] Trigger @ {ce_sl_trigger} USD (Pure Market Stop)")
        self._place_bracket_sl(ce_info["id"], ce_sl_trigger, "CE")

        print(f"[PE SL Setup] Trigger @ {pe_sl_trigger} USD (Pure Market Stop)")
        self._place_bracket_sl(pe_info["id"], pe_sl_trigger, "PE")

        # ------------------------------------------------------------------
        # 10 SECOND REST (Stop Order Confirmation Wait)
        # ------------------------------------------------------------------
        print("\n[WAIT] 10 second ruk rahe hain taaki exchange par Bracket SL verify ho sakein...")
        for sec in range(10, 0, -1):
            print(f" -> Bracket verification in {sec}s...", end="\r")
            time.sleep(1)
        print("\n[SYNC] 10 second poore hue! Ab open bracket orders verify kiye ja rahe hain.\n")

        # ------------------------------------------------------------------
        # STEP 4: VERIFY ACTIVE BRACKET ORDERS IN ORDERBOOK
        # ------------------------------------------------------------------
        print(">>> STEP 4: VERIFYING BRACKET SL REGISTRATION <<<")
        open_orders = self._get_open_orders()

        ce_sl_active = self._verify_bracket_in_orders(open_orders, ce_info["id"], ce_sl_trigger)
        pe_sl_active = self._verify_bracket_in_orders(open_orders, pe_info["id"], pe_sl_trigger)

        report["ce"]["sl_verified"] = ce_sl_active
        report["pe"]["sl_verified"] = pe_sl_active
        report["success"] = bool(ce_sl_active and pe_sl_active)

        # ------------------------------------------------------------------
        # STEP 5: FINAL CONFIRMATION (DELIVER TO TELEGRAM)
        # ------------------------------------------------------------------
        print("\n==================================================")
        if report["success"]:
            print(">>> STATUS: ALL ORDERS & BRACKET-SL 100% VERIFIED <<<")
            self._send_final_notification(report)
        else:
            warn_msg = f"⚠️ *DELTA BOT WARNING*\nPositions open hain par Bracket SL verify nahi hua!\nCE Active: {ce_sl_active} | PE Active: {pe_sl_active}"
            print(warn_msg)
            self.notifier.send_message(warn_msg)
        print("==================================================")

        return report

    def _market_sell(self, product_id: int, size: int, leg_name: str, symbol: str) -> bool:
        payload = {
            "product_id": product_id,
            "size": size,
            "side": "sell",
            "order_type": "market_order"
        }
        resp = self.client.request("POST", "/v2/orders", payload=payload)
        success = resp.get("success", False) if resp else False
        if success:
            oid = resp.get("result", {}).get("id")
            print(f"[{leg_name} SOLD] {symbol} (Product: {product_id}) | Order ID: {oid}")
            return True
        else:
            print(f"[{leg_name} FAILED] {resp}")
            return False

    def _get_open_positions(self) -> List[Dict[str, Any]]:
        resp = self.client.request("GET", "/v2/positions?underlying_asset_symbol=BTC")
        if not resp or not resp.get("success"):
            return []
        res = resp.get("result", [])
        return res if isinstance(res, list) else [res]

    def _find_position(self, positions: List[Dict[str, Any]], product_id: int) -> Optional[Dict[str, Any]]:
        for p in positions:
            if int(p.get("product_id", 0)) == int(product_id):
                return p
        return None

    def _place_bracket_sl(self, product_id: int, trigger_price: float, leg_name: str) -> Optional[int]:
        payload = {
            "product_id": product_id,
            "stop_loss_order": {
                "order_type": "market_order",
                "stop_price": str(trigger_price)
            },
            "bracket_stop_trigger_method": "last_traded_price"
        }
        resp = self.client.request("POST", "/v2/orders/bracket", payload=payload)
        if resp and resp.get("success"):
            sl_info = resp.get("result", {}).get("stop_loss_order", {})
            oid = sl_info.get("id")
            print(f"[{leg_name} BRACKET SL ATTACHED] ID: {oid} | Trigger: {trigger_price} USD (Market Order)")
            return oid
        else:
            print(f"[{leg_name} BRACKET SL FAILED] Response: {resp}")
            return None

    def _get_open_orders(self) -> List[Dict[str, Any]]:
        resp = self.client.request("GET", "/v2/orders?state=open")
        if not resp or not resp.get("success"):
            return []
        return resp.get("result", [])

    def _verify_bracket_in_orders(self, orders: List[Dict[str, Any]], product_id: int, expected_trigger: float) -> bool:
        for o in orders:
            p_id = int(o.get("product_id", 0))
            is_bracket = o.get("bracket_order", False)
            stop_price = float(o.get("stop_price") or 0.0)

            if p_id == int(product_id) and is_bracket:
                if abs(stop_price - expected_trigger) < 0.2:
                    return True
        return False

    def _send_final_notification(self, report: Dict[str, Any]):
        msg = (
            "🎯 *ALPHA STRANGLE ENTRY & SL VERIFIED*\n\n"
            f"🟢 *CALL LEG (CE):*\n"
            f"• Contract: `{report['ce']['symbol']}`\n"
            f"• Sold @: `{report['ce']['entry_price']} USD`\n"
            f"• 75% Bracket SL: `{report['ce']['sl_trigger']} USD` ✅\n\n"
            f"🔴 *PUT LEG (PE):*\n"
            f"• Contract: `{report['pe']['symbol']}`\n"
            f"• Sold @: `{report['pe']['entry_price']} USD`\n"
            f"• 75% Bracket SL: `{report['pe']['sl_trigger']} USD` ✅\n\n"
            "🛡️ *Status:* Positions Protected by Market Bracket SL"
        )
        print("\n" + msg + "\n")
        self.notifier.send_message(msg)

    def square_off_with_retry(self, max_retries: int = 3, retry_delay: int = 4) -> Dict[str, Any]:
        """
        Cancels all orders and attempts to square-off positions with up to `max_retries` attempts.
        Verifies open positions == 0 after execution.
        """
        summary = {
            "success": False,
            "attempts": 0,
            "closed_positions": [],
            "remaining_positions": []
        }

        for attempt in range(1, max_retries + 1):
            summary["attempts"] = attempt
            print(f"\n[SQUARE-OFF ATTEMPT {attempt}/{max_retries}] Starting cleanup loop...")

            # 1. Cancel all open orders
            print("[1/2] Cancelling all open orders...")
            self.client.request("DELETE", "/v2/orders/all")
            time.sleep(1)

            # 2. Query open positions
            pos_resp = self.client.request("GET", "/v2/positions?underlying_asset_symbol=BTC")
            raw_positions = pos_resp.get("result", []) if pos_resp else []
            if isinstance(raw_positions, dict):
                raw_positions = [raw_positions]

            active_positions = [p for p in raw_positions if int(p.get("size", 0)) != 0]

            if not active_positions:
                print(f"[SUCCESS] No open positions detected on attempt {attempt}. Account is FLAT.")
                summary["success"] = True
                summary["remaining_positions"] = []
                return summary

            # 3. Close active positions via Market Order
            print(f"[2/2] Closing {len(active_positions)} active position(s)...")
            for pos in active_positions:
                size = int(pos.get("size", 0))
                prod_id = pos.get("product_id")
                symbol = pos.get("product_symbol", f"ID_{prod_id}")
                side = "buy" if size < 0 else "sell"
                close_size = abs(size)

                close_payload = {
                    "product_id": prod_id,
                    "size": close_size,
                    "side": side,
                    "order_type": "market_order"
                }
                close_resp = self.client.request("POST", "/v2/orders", payload=close_payload)
                success = close_resp.get("success", False) if close_resp else False

                summary["closed_positions"].append({
                    "symbol": symbol,
                    "size": close_size,
                    "side": side,
                    "success": success,
                    "attempt": attempt
                })
                print(f"[*] Position {symbol} close order sent (Size: {close_size}, Side: {side}, Success: {success})")

            # Wait before re-checking
            print(f"[WAIT] Waiting {retry_delay}s for fills to settle before next verification...")
            time.sleep(retry_delay)

        # Final verification check
        final_resp = self.client.request("GET", "/v2/positions?underlying_asset_symbol=BTC")
        final_raw = final_resp.get("result", []) if final_resp else []
        if isinstance(final_raw, dict):
            final_raw = [final_raw]

        remaining = [p for p in final_raw if int(p.get("size", 0)) != 0]
        summary["remaining_positions"] = remaining
        summary["success"] = (len(remaining) == 0)

        return summary

    def square_off_all(self) -> Dict[str, Any]:
        """Backwards-compatible wrapper calling square_off_with_retry."""
        return self.square_off_with_retry(max_retries=3, retry_delay=4)
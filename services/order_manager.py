import time
from decimal import Decimal, ROUND_HALF_UP
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

            # ATOMIC ROLLBACK: Buy back the filled CE leg immediately with reduce_only=True
            rollback_payload = {
                "product_id": ce_info["id"],
                "size": size,
                "side": "buy",
                "order_type": "market_order",
                "reduce_only": True
            }
            rollback_res = self.client.request("POST", "/v2/orders", payload=rollback_payload)
            if not rollback_res or not rollback_res.get("success"):
                print(f"[ROLLBACK FALLBACK] Market buy failed: {rollback_res}. Attempting aggressive limit fallback...")
                ce_tick = float(ce_info.get("tick_size") or 0.1)
                best_ask = float(ce_info.get("best_ask") or 0.0)
                mark_p = float(ce_info.get("mark_price") or 0.0)
                aggressive_px = best_ask if best_ask > 0 else (mark_p * 1.25 if mark_p > 0 else 0.0)
                if aggressive_px > 0:
                    rounded_px = self._round_to_tick_size(aggressive_px, ce_tick)
                    px_str = self._format_price(rounded_px, ce_tick)
                    limit_payload = {
                        "product_id": ce_info["id"],
                        "size": size,
                        "side": "buy",
                        "order_type": "limit_order",
                        "limit_price": px_str,
                        "reduce_only": True,
                        "time_in_force": "ioc"
                    }
                    rollback_res = self.client.request("POST", "/v2/orders", payload=limit_payload)
                    if not rollback_res or not rollback_res.get("success"):
                        limit_payload["time_in_force"] = "gtc"
                        rollback_res = self.client.request("POST", "/v2/orders", payload=limit_payload)

            if rollback_res and rollback_res.get("success"):
                rb_msg = (
                    "🛡️ *[ROLLBACK SUCCESSFUL] Naked CE position closed via Buy.*\n"
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
        # STEP 3: ATTACH 75% PURE BRACKET STOP-LOSS (TICK-SIZE COMPLIANT)
        # ------------------------------------------------------------------
        print("\n>>> STEP 3: ATTACHING 75% BRACKET STOP LOSS ORDERS <<<")
        ce_tick = float(ce_info.get("tick_size") or 0.1)
        pe_tick = float(pe_info.get("tick_size") or 0.1)

        raw_ce_sl = ce_entry * 1.75
        raw_pe_sl = pe_entry * 1.75

        ce_sl_trigger = self._round_to_tick_size(raw_ce_sl, ce_tick)
        pe_sl_trigger = self._round_to_tick_size(raw_pe_sl, pe_tick)

        report["ce"]["sl_trigger"] = ce_sl_trigger
        report["pe"]["sl_trigger"] = pe_sl_trigger
        report["ce"]["tick_size"] = ce_tick
        report["pe"]["tick_size"] = pe_tick

        print(f"[CE SL Setup] Trigger @ {ce_sl_trigger} USD (Pure Market Stop, Tick: {ce_tick})")
        self._place_bracket_sl(ce_info["id"], ce_sl_trigger, "CE", tick_size=ce_tick)

        print(f"[PE SL Setup] Trigger @ {pe_sl_trigger} USD (Pure Market Stop, Tick: {pe_tick})")
        self._place_bracket_sl(pe_info["id"], pe_sl_trigger, "PE", tick_size=pe_tick)

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

        ce_sl_active = self._verify_bracket_in_orders(open_orders, ce_info["id"], ce_sl_trigger, tick_size=ce_tick)
        pe_sl_active = self._verify_bracket_in_orders(open_orders, pe_info["id"], pe_sl_trigger, tick_size=pe_tick)

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
        num_ticks = (d_price / d_tick).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        rounded = num_ticks * d_tick
        return float(rounded)

    @staticmethod
    def _format_price(price: float, tick_size: float = 0.1) -> str:
        """
        Formats price as clean string matching tick_size precision without scientific notation.
        """
        if not tick_size or tick_size <= 0:
            return str(round(price, 2))
        if tick_size >= 1.0 and float(price).is_integer():
            return str(int(price))
        dec_places = abs(Decimal(str(tick_size)).as_tuple().exponent)
        return f"{price:.{dec_places}f}"

    def _place_bracket_sl(self, product_id: int, trigger_price: float, leg_name: str, tick_size: float = 0.1) -> Optional[int]:
        # Clean string representation without scientific notation or trailing precision artifacts
        price_str = self._format_price(trigger_price, tick_size)

        payload = {
            "product_id": product_id,
            "stop_loss_order": {
                "order_type": "market_order",
                "stop_price": price_str
            },
            "bracket_stop_trigger_method": "last_traded_price"
        }
        resp = self.client.request("POST", "/v2/orders/bracket", payload=payload)
        if resp and resp.get("success"):
            sl_info = resp.get("result", {}).get("stop_loss_order", {})
            oid = sl_info.get("id")
            print(f"[{leg_name} BRACKET SL ATTACHED] ID: {oid} | Trigger: {price_str} USD (Market Order, Tick: {tick_size})")
            return oid
        else:
            print(f"[{leg_name} BRACKET SL FAILED] Response: {resp}")
            return None

    def _get_open_orders(self) -> List[Dict[str, Any]]:
        resp = self.client.request("GET", "/v2/orders?state=open")
        if not resp or not resp.get("success"):
            return []
        return resp.get("result", [])

    def _verify_bracket_in_orders(self, orders: List[Dict[str, Any]], product_id: int, expected_trigger: float, tick_size: float = 0.1) -> bool:
        tolerance = max(0.2, tick_size)
        for o in orders:
            p_id = int(o.get("product_id", 0))
            is_bracket = o.get("bracket_order", False)
            stop_price = float(o.get("stop_price") or 0.0)

            if p_id == int(product_id) and is_bracket:
                if abs(stop_price - expected_trigger) <= tolerance:
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

            # 3. Close active positions via Market Order (with Reduce-Only and Aggressive Limit Fallback)
            print(f"[2/2] Closing {len(active_positions)} active position(s)...")
            for pos in active_positions:
                size = int(pos.get("size", 0))
                prod_id = pos.get("product_id")
                symbol = pos.get("product_symbol", f"ID_{prod_id}")
                side = "buy" if size < 0 else "sell"
                close_size = abs(size)

                # A. Primary Close: Market Order with reduce_only=True
                close_payload = {
                    "product_id": prod_id,
                    "size": close_size,
                    "side": side,
                    "order_type": "market_order",
                    "reduce_only": True
                }
                close_resp = self.client.request("POST", "/v2/orders", payload=close_payload)
                success = close_resp.get("success", False) if close_resp else False

                # B. Automatic Fallback: If market order rejected (e.g. no opposing orders near expiry),
                # fetch best quote or mark_price*1.25 and send aggressive limit order with reduce_only=True
                if not success:
                    print(f"[*] Market {side} for {symbol} rejected ({close_resp}). Attempting aggressive Limit fallback...")
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
                            "time_in_force": "ioc"
                        }
                        limit_resp = self.client.request("POST", "/v2/orders", payload=limit_payload)
                        success = limit_resp.get("success", False) if limit_resp else False
                        print(f"[*] Aggressive Limit IOC {side} for {symbol} @ {px_str} sent (Success: {success})")
                        if not success:
                            limit_payload["time_in_force"] = "gtc"
                            gtc_resp = self.client.request("POST", "/v2/orders", payload=limit_payload)
                            success = gtc_resp.get("success", False) if gtc_resp else False
                            print(f"[*] Aggressive Limit GTC {side} for {symbol} @ {px_str} sent (Success: {success})")

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
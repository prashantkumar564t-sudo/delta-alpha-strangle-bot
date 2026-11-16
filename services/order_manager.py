from __future__ import annotations

import time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from services.notifier import TelegramNotifier


class OrderManager:
    def __init__(self, api_client, default_leverage: int = 40):
        self.client = api_client
        self.notifier = TelegramNotifier()
        self.default_leverage = default_leverage

    def set_leverage(self, product_id: int, leverage: int = 40) -> bool:
        """
        Sets order leverage for a specific product on Delta Exchange.
        Handles portfolio margin mode (where contract-level leverage is unsupported) gracefully.
        """
        payload = {"leverage": str(leverage)}
        # Try standard Delta product-specific leverage endpoint first
        resp = self.client.request("POST", f"/v2/products/{product_id}/orders/leverage", payload=payload)

        # Fallback to general orders/leverage endpoint if 404
        if not resp or resp.get("http_code") == 404 or resp.get("error") == "Not Found":
            resp = self.client.request(
                "POST",
                "/v2/orders/leverage",
                payload={"product_id": product_id, "leverage": str(leverage)},
            )

        if resp and resp.get("success"):
            print(f"[LEVERAGE] Product {product_id} leverage configured to {leverage}x ✅")
            return True

        # Check if portfolio margin mode is active (contract-level leverage is dynamically managed)
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
    ) -> dict[str, Any]:
        """
        0. Sets 40x leverage on CE and PE products.
        1. Executes CE and PE Market Sell orders with immediate cancellation audit.
        2. Pauses 10s for matching engine settlement.
        3. Fetches real positions table; triggers atomic rollback if asymmetric fill.
        4. Attaches 75% pure market stop bracket orders with 3-attempt retry loop.
        5. Pauses 10s for stop orderbook registration.
        6. Verifies bracket orders in open orderbook (/v2/orders?state=open).
        7. Sends confirmed Telegram execution alert.
        """
        report: dict[str, Any] = {
            "ce": {"product_id": ce_info["id"], "symbol": ce_info["symbol"]},
            "pe": {"product_id": pe_info["id"], "symbol": pe_info["symbol"]},
            "success": False,
        }

        # ------------------------------------------------------------------
        # STEP 0: CONFIGURE 40X LEVERAGE
        # ------------------------------------------------------------------
        print("\n==================================================")
        print(f">>> STEP 0: CONFIGURING {self.default_leverage}X LEVERAGE <<<")
        print("==================================================")
        self.set_leverage(ce_info["id"], self.default_leverage)
        self.set_leverage(pe_info["id"], self.default_leverage)

        # ------------------------------------------------------------------
        # STEP 1: EXECUTING MARKET SELL (ENTRY ORDERS)
        # ------------------------------------------------------------------
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

        # Asymmetric fill check
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

        # ------------------------------------------------------------------
        # STEP 3: ATTACH 75% PURE BRACKET STOP-LOSS (WITH 3-ATTEMPT RETRY)
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
        ce_sl_oid = self._place_bracket_sl_with_retry(
            ce_info["id"], ce_sl_trigger, "CE", tick_size=ce_tick, max_retries=3
        )

        print(f"[PE SL Setup] Trigger @ {pe_sl_trigger} USD (Pure Market Stop, Tick: {pe_tick})")
        pe_sl_oid = self._place_bracket_sl_with_retry(
            pe_info["id"], pe_sl_trigger, "PE", tick_size=pe_tick, max_retries=3
        )

        # Fail-Safe: If Bracket SL failed after 3 retries, do NOT leave naked exposure!
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

            # 1. Immediate cancellation check from order placement response
            if state == "cancelled":
                print(f"[{leg_name} CANCELLED BY EXCHANGE] {symbol} (Order ID: {oid}) | Reason: {cancellation_reason}")
                return False

            # 2. If not filled/closed, poll order status to verify fill vs matching cancellation
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

            # Filter active positions matching target_product_ids
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

                # Primary Close: Market Order with reduce_only=True
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

                # Automatic Fallback: If market order failed or cancelled, try aggressive limit order
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

            # Wait before re-checking
            print(f"[WAIT] Waiting {retry_delay}s for fills to settle before next verification...")
            time.sleep(retry_delay)

        # Final verification check
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

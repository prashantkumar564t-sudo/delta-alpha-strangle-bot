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
        # 1. Check local cache validity
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

        # 2. Fetch fresh via direct internet (request_public, gzip enabled)
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

        # 3. Fallback to existing stale cache if live request failed
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

    def check_anti_trap_liquidity(
        self,
        product_id: int,
        symbol: str,
        mark_price: float,
        best_bid: float,
        best_ask: float,
        bid_size: float,
        order_lots: int = 1,
        sleep_fn: Any = time.sleep,
    ) -> tuple[bool, str, dict[str, Any]]:
        """
        4-Layer Pre-Trade Liquidity & Anti-Trap Filter:
        Layer 1: Spread / Mark <= 0.035 (3.5% max spread barrier)
        Layer 2: Top Bid Lots >= max(500, order_lots * 5) (>= 5x depth cushion)
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
        }

        # Pre-check: non-positive prices
        if mark_price <= 0.0 or best_bid <= 0.0 or best_ask <= 0.0:
            err = f"Pre-check failed: Non-positive price/quotes (Mark: {mark_price}, Bid: {best_bid}, Ask: {best_ask})"
            return False, err, metrics

        # Layer 1: Max Spread Slippage Barrier (<= 3.5%)
        spread = best_ask - best_bid
        spread_ratio = spread / mark_price
        metrics["spread"] = spread
        metrics["spread_ratio"] = spread_ratio
        if spread_ratio > 0.035:
            reason = (
                f"Layer 1 Failed: Spread ratio {spread_ratio:.2%} exceeds 3.5% limit "
                f"(Spread: {spread:.2f}, Mark: {mark_price:.2f}, Ask: {best_ask:.2f}, Bid: {best_bid:.2f})"
            )
            return False, reason, metrics

        # Layer 2: Top Bid Lots Depth Cushion (>= max(500, order_lots * 5))
        min_depth = max(500.0, float(order_lots) * 5.0)
        metrics["min_required_depth"] = min_depth
        if bid_size < min_depth:
            reason = (
                f"Layer 2 Failed: Top Bid depth {bid_size:.1f} lots is below required cushion "
                f"of {min_depth:.1f} lots (5x order cushion or 500 lot min floor)"
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
            snap2_quotes = snap2_resp.get("result", {}).get("quotes")
        else:
            all_t_resp = self.client.request_public("GET", "/v2/tickers")
            if all_t_resp and all_t_resp.get("success"):
                for t in all_t_resp.get("result", []):
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

    def get_10_delta_strikes(
        self,
        symbol: str = "BTC",
        target_delta: float = 0.10,
        expiry_date_str: str | None = None,
        lot_size: int = 1,
        enable_anti_trap: bool = True,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """
        Selects optimal 10-Delta Call and Put strikes strictly for today's 0-DTE expiry.
        Enforces two-sided orderbook (bids AND asks required), spread <= 40%, and depth.
        """
        target_date_suffix = expiry_date_str or self.get_target_expiry_date_str()
        print(f"[INFO] Looking for 0-DTE Expiry Date Suffix: {target_date_suffix}")

        # 1. Tickers fetch karein via direct internet (request_public, 0 KB proxy bandwidth)
        tickers_resp = self.client.request_public("GET", "/v2/tickers")
        if not tickers_resp or not tickers_resp.get("success"):
            print(f"[ERROR] Failed to fetch tickers: {tickers_resp}")
            return None, None

        all_tickers = tickers_resp.get("result", [])

        # 2. Products details fetch karein (with 12h local caching)
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

            # Symbol ke aakhri 6 digit expiry date hote hain (DDMMYY)
            parts = symbol_name.split("-")
            if len(parts) >= 4:
                available_expiries.add(parts[-1])

            # Expiry date filter (Strictly target 0-DTE date suffix)
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

            # --- SAFETY BOUND: Enforce 0.07 <= abs(delta) <= 0.13 ---
            if not (0.07 <= abs_delta <= 0.13):
                continue

            quotes = ticker.get("quotes") or {}
            mark_price = float(ticker.get("mark_price") or 0.0)
            best_bid = float(quotes.get("best_bid") or 0.0)
            best_ask = float(quotes.get("best_ask") or 0.0)
            bid_size = float(quotes.get("bid_size") or 0.0)

            # --- SPREAD & LIQUIDITY SANITY CHECKS ---
            # 1. Enforce two-sided orderbook (reject one-sided or empty books)
            if best_bid <= 0.0 or best_ask <= 0.0:
                continue

            # 2. Enforce minimum $5.00 mark price threshold
            if mark_price < 5.0:
                continue

            # 3. Require active buyers in live orderbook with minimum bid floor
            is_testnet = "testnet" in getattr(self.client, "base_url", "").lower()
            min_bid = 1.0 if is_testnet else 5.0
            if best_bid < min_bid:
                continue

            # 4. Filter out contracts where spread / mark_price > 0.40 (excessive slippage protection)
            spread = best_ask - best_bid
            if (spread / mark_price) > 0.40:
                continue

            # 5. Depth check: Ensure orderbook has sufficient buyers for requested lot size
            if bid_size < float(lot_size):
                continue

            # Extract contract tick_size for precise stop-loss rounding
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
            # Calendar-aware sorting for debug log
            valid_expiries = [e for e in available_expiries if parse_expiry_date(e) is not None]
            sorted_expiries = sorted(valid_expiries, key=lambda e: parse_expiry_date(e) or date.min)
            print(f"[DEBUG] Active Expiries found on Delta: {sorted_expiries}")

        # 3. Target delta (0.10) ke sabse kareeb wali strike select karein
        best_ce = min(ce_candidates, key=lambda x: x["delta_diff"]) if ce_candidates else None
        best_pe = min(pe_candidates, key=lambda x: x["delta_diff"]) if pe_candidates else None

        # 4. Strict 0-DTE Mandate: No forward expiry fallback
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

        # 5. 4-Layer Pre-Trade Liquidity & Anti-Trap Filter
        if enable_anti_trap:
            print(f"\n[ANTI-TRAP AUDIT] Auditing CE ({best_ce['symbol']}) through 4-layer filter...")
            ce_ok, ce_reason, _ = self.check_anti_trap_liquidity(
                product_id=best_ce["id"],
                symbol=best_ce["symbol"],
                mark_price=best_ce["mark_price"],
                best_bid=best_ce["best_bid"],
                best_ask=best_ce["best_ask"],
                bid_size=best_ce["bid_size"],
                order_lots=lot_size,
            )
            if not ce_ok:
                print(f"[ANTI-TRAP BLOCKED] CE Rejected: {ce_reason}")
                self.notifier.send_message(
                    f"⚠️ *[ANTI-TRAP FILTER BLOCKED CE]*\n"
                    f"• Contract: `{best_ce['symbol']}`\n"
                    f"• Reason: {ce_reason}\n"
                    "🛡️ Session skipped cleanly (No naked risk)."
                )
                return None, None

            print(f"[ANTI-TRAP AUDIT] Auditing PE ({best_pe['symbol']}) through 4-layer filter...")
            pe_ok, pe_reason, _ = self.check_anti_trap_liquidity(
                product_id=best_pe["id"],
                symbol=best_pe["symbol"],
                mark_price=best_pe["mark_price"],
                best_bid=best_pe["best_bid"],
                best_ask=best_pe["best_ask"],
                bid_size=best_pe["bid_size"],
                order_lots=lot_size,
            )
            if not pe_ok:
                print(f"[ANTI-TRAP BLOCKED] PE Rejected: {pe_reason}")
                self.notifier.send_message(
                    f"⚠️ *[ANTI-TRAP FILTER BLOCKED PE]*\n"
                    f"• Contract: `{best_pe['symbol']}`\n"
                    f"• Reason: {pe_reason}\n"
                    "🛡️ Session skipped cleanly (No naked risk)."
                )
                return None, None

            print("[ANTI-TRAP AUDIT] Both CE and PE successfully cleared all 4 liquidity layers! ✅")

        return best_ce, best_pe

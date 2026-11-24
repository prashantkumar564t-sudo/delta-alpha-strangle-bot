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

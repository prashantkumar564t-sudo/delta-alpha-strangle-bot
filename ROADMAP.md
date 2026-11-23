# 🗺️ Delta Alpha Strangle Bot — Production Roadmap

This roadmap documents the structured milestones and operational phases for scaling `delta-alpha-strangle-bot` from single-bot mobile execution to a multi-contract institutional options fund architecture on Delta Exchange India.

---

## 📌 Strategic Overview & Timeline

```
┌─────────────────────────┐    ┌─────────────────────────┐    ┌─────────────────────────┐    ┌─────────────────────────┐
│        PHASE 1          │    │         PHASE 2         │    │         PHASE 3         │    │         PHASE 4         │
│  Telegram Broadcast &   │───►│ Forward-Testing 1.0 BTC │───►│ Weekly Auto-CSV Channel │───►│ Capital Scaling 5.0 BTC │
│    Channel Admin Sync   │    │  (1,000 Lots on Termux) │    │  Verification Digests   │    │ (₹11.5L/yr Sweet Spot)  │
└─────────────────────────┘    └─────────────────────────┘    └─────────────────────────┘    └─────────────────────────┘
```

---

## 🚀 Phase 1: Community Telegram Channel & Dual-Broadcast (Immediate)

**Objective:** Isolate system/error alerts to private admin DM while publicizing verified, tamper-proof execution alerts to a read-only community Telegram Channel.

### Key Milestones:
1. **Channel Creation & Access Control:**
   - Create a dedicated public or invite-only Telegram Channel (e.g., `Delta Alpha Strangle Verified Live`).
   - Add the bot account as an **Administrator** with exclusive permission: `Post Messages` enabled (all other admin permissions disabled for least-privilege security).
2. **Channel ID Configuration:**
   - Capture the unique numerical Channel ID (prefixed with `-100`, e.g. `-1002345678901`).
   - Add `TELEGRAM_CHANNEL_ID=-100...` to local `.env` and Termux host `.env`.
3. **Dual-Broadcast Verification:**
   - **Trade Alerts (Broadcast to Both DM & Channel):**
     - Template 1: Strangle Entry Executed (`10:00 IST`) with dynamic lot sizing, L1 depth, and 100% SLs.
     - Template 2: Anti-Trap Shield Blocks (`Spread > 3.5%`, `Depth < 500`, `Mark Gap > 2%`, `2.5s Drift`).
     - Template 3: Cost-to-Cost Trail Activated (`Surviving leg moved to 1.0x entry cost`).
     - Template 4: 17:15 IST Daily Session Scorecards (Gross PnL, 4.13% fees, and Net Realized PnL).
   - **System Errors / Tracebacks (Strictly Isolated to Admin DM):**
     - Exceptions, connection retries, and emergency exit notifications remain strictly routed to `TELEGRAM_CHAT_ID`.

---

## 📊 Phase 2: Live Forward-Testing at 1,000 Lots (1.0 BTC Notional)

**Objective:** Validate real-world microstructure slippage, fill ratios, and 20% L1 footprint auto-downsizer behavior on live Delta Exchange India daily options contracts.

### Operating Parameters:
- **Target Notional:** `1,000 Lots` (1.0 BTC per strangle leg).
- **Minimum Execution Floor:** `100 Lots` (0.1 BTC).
- **Margin Mode:** 40x Cross Margin / Portfolio Margin.
- **Safe Capital Allocation:** `$3,499.17` (`₹2,97,429 INR`).
- **Hard Strategy Kill-Switch:** `-$1,185.00 USD / BTC` (`₹1,00,717 INR`).

### Key Milestones:
1. **Automated 24/7 Termux Lifecycle:**
   - `10:00:00 IST`: Entry job executes 4-layer pre-trade anti-trap filter, sizes lots dynamically, and attaches 100% market bracket SLs.
   - `*/2 10-17 IST`: Monitor job checks position state and moves surviving leg to entry cost immediately when one leg is stopped out.
   - `17:15:00 IST`: Exit job performs 3-attempt square-off and calculates verified daily scorecard.
2. **Weekly Slippage & Microstructure Audit:**
   - Compare realized entry prices against AlgoTest backtest theoretical marks.
   - Verify that 20% L1 Footprint Rule maintains average fill slippage $\le 1.1\%$.
   - Monitor the distribution of the 5 Combo A Outcome Types (targeting $> 50\%$ Type 2 runner recoveries).

---

## 📈 Phase 3: Weekly Auto-CSV Channel Digest & Public Transparency

**Objective:** Deliver automated weekly audit digests directly into the Telegram Channel every Sunday evening, establishing an open-source, verifiable track record.

### Key Milestones:
1. **Automated Weekly Ledger Exporter:**
   - Develop `jobs/weekly_digest_job.py` scheduled via cron every Sunday at `18:00 IST`.
   - Aggregates the 7 completed daily session logs from `data/state.json` and exchange fill records.
2. **Weekly Performance Scorecard Format:**
   - Weekly Total Sessions (e.g., 7 / 7).
   - Weekly Outcome Breakdown: Count of Type 1 (Full Decay), Type 2 (1 SL + Runner), Type 3 (Cost Trailed), Type 5 (Double SL).
   - Weekly Gross PnL, Deducted Delta Fees (4.13%), and Net Realized PnL in USD and INR.
   - Trailing Strategy Drawdown vs. $1,185 Kill-Switch ceiling.
3. **Automated Document Dispatch:**
   - Sends formatted markdown summary to Channel.
   - Uploads compiled `weekly_trades_YYYY_WW.csv` file directly to the Telegram Channel using Telegram Bot API `sendDocument`.

---

## 💎 Phase 4: Capital Scaling — 1.0 BTC to 5.0 BTC Sweet Spot

**Objective:** Systematically scale capital allocation from 1.0 BTC up to the institutional liquidity sweet spot of 5.0 BTC (5,000 lots) generating an audited ~₹11.50 Lakhs/year net profit.

### Scaling Milestones:

| Scale Tier | Target Lots | Notional BTC | Safe Capital (40x Cross) | Annualized Net PnL (USD) | Annualized Net PnL (INR) | Projected Net ROI % | Microstructure Capacity Status |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Tier 1** | **1,000 Lots** | 1.0 BTC | **`$3,499`** (`₹2.97L`) | **`$3,618 / yr`** | **`₹3,07,545`** | **`+103.4%`** | 🟢 Baseline (Zero market impact) |
| **Tier 2** | **2,500 Lots** | 2.5 BTC | **`$8,748`** (`₹7.44L`) | **`$7,600 / yr`** | **`₹6,46,000`** | **`+86.9%`** | 🟢 High efficiency |
| **Tier 3** | **5,000 Lots** | 5.0 BTC | **`$17,496`** (`₹14.87L`) | **`$13,528 / yr`** | **`₹11,49,916`** | **`+77.3%`** | 🏆 **INSTITUTIONAL SWEET SPOT** |
| **Tier 4** | **10,000 Lots** | 10.0 BTC | **`$34,992`** (`₹29.74L`) | **`$13,369 / yr`** | **`₹11,36,395`** | **`+38.2%`** | 🟡 Diminishing returns (Depth drag) |

### Scaling Rules & Risk Gates:
1. **20% L1 Footprint Rule Remains Hardcoded:**
   - Even when `TARGET_LOTS` is set to 5,000, if orderbook top-bid depth dips during market stress, the bot automatically downsizes execution size to prevent sweeping into deeper bids.
2. **Hard Kill-Switch Scaling:**
   - 1.0 BTC Kill-Switch: `-$1,185 USD` (`₹1,00,717 INR`).
   - 5.0 BTC Kill-Switch: `-$5,925 USD` (`₹5,03,585 INR`).
   - Immediate automatic shutdown if cumulative peak-to-trough equity drawdown hits the 1.5x MDD threshold.
3. **Multi-Asset Strangle Expansion:**
   - Following successful 5.0 BTC scaling on BTC, introduce parallel `ETHUSD_0DTE_20Delta_Strangle` (Mon & Sat only) for combined cross-margin diversification.

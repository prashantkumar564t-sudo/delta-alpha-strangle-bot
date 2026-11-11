# 📈 Delta Alpha Strangle: Quantitative Strategy & Risk Engine Specification

**Document Version:** 2.0.0 (Production Verified)  
**Target Underlying:** Bitcoin (BTC) Options on Delta Exchange  
**Execution Environment:** Pure Python 3 Standard Library via Datacenter Proxy Tunnel  
**Target Expiration:** Daily Contracts Settling at 17:30:00 IST (12:00:00 UTC)  

---

## 📑 Table of Contents

- [1. Quantitative Strategy Thesis](#1-quantitative-strategy-thesis)
  - [The Intraday Theta Decay Curve](#the-intraday-theta-decay-curve)
  - [Delta-Neutral Statistical Probability](#delta-neutral-statistical-probability)
- [2. Dynamic Strike Selection Engine](#2-dynamic-strike-selection-engine)
  - [Greek Delta Targeting Criteria](#greek-delta-targeting-criteria)
  - [Expiry Date Determination (`DDMMYY`)](#expiry-date-determination-ddmmyy)
- [3. Safety & Liquidity Sanity Filters](#3-safety--liquidity-sanity-filters)
  - [Filter 1: Active Orderbook Liquidity (`best_bid > 0`)](#filter-1-active-orderbook-liquidity-best_bid--0)
  - [Filter 2: Minimum Premium Economic Cutoff (`mark_price >= 5.0 USD`)](#filter-2-minimum-premium-economic-cutoff-mark_price--50-usd)
  - [Filter 3: Maximum Spread Slippage Barrier (`Spread Ratio <= 0.40`)](#filter-3-maximum-spread-slippage-barrier-spread-ratio--040)
- [4. Order Execution & Stop-Loss Protocol](#4-order-execution--stop-loss-protocol)
  - [Sequential Market Sell Execution](#sequential-market-sell-execution)
  - [The 10-Second Matching Engine Settlement Wait](#the-10-second-matching-engine-settlement-wait)
  - [Real Fill Discovery via `/v2/positions`](#real-fill-discovery-via-v2positions)
  - [The 75% Pure Stop-Market Bracket Order](#the-75-pure-stop-market-bracket-order)
  - [Post-Placement Bracket Verification](#post-placement-bracket-verification)
- [5. Fault-Tolerant Atomic Rollback Engine](#5-fault-tolerant-atomic-rollback-engine)
  - [Single-Leg Execution Risk Breakdown](#single-leg-execution-risk-breakdown)
  - [Atomic Rollback Sequence](#atomic-rollback-sequence)
- [6. Guaranteed EOD Square-Off & Settlement](#6-guaranteed-eod-square-off--settlement)
  - [The 17:15:00 IST Square-Off Trigger](#the-171500-ist-square-off-trigger)
  - [3-Attempt Purge & Verification Loop](#3-attempt-purge--verification-loop)
  - [Emergency Escalation Protocol](#emergency-escalation-protocol)
- [7. Operational Parameter Reference](#7-operational-parameter-reference)

---

## 1. Quantitative Strategy Thesis

### The Intraday Theta Decay Curve
Option prices are governed by the Black-Scholes-Merton model and its extensions for jump-diffusion processes in crypto assets. An option's theoretical value $V$ comprises intrinsic value and extrinsic time value:

$$V = \text{Intrinsic Value} + \text{Time Value}$$

For out-of-the-money (OTM) options, intrinsic value is $0$; the entire option premium consists of time value. The rate of time decay is quantified by the Greek **Theta ($\Theta$)**:

$$\Theta = -\frac{\partial V}{\partial t}$$

Under standard option pricing theory, Theta decay is non-linear with respect to time to expiration ($T - t$):

$$\Theta \propto \frac{1}{\sqrt{T - t}}$$

```
Option Premium
    ▲
    │         Accelerated Intraday Theta Decay Zone
    │         (10:00 AM IST to 17:15 PM IST)
    │───────────────────────────────┐
    │                                ╲
    │                                 ╲
    │                                  ╲
    │                                   ╲
    │                                    └──► Expiration (17:30 IST)
────┴─────────────────────────────────────────────► Time
```

On Delta Exchange, daily Bitcoin options expire at **17:30:00 IST (12:00:00 UTC)**. In the final 8 hours leading into expiry, the Theta decay curve steepens dramatically. By opening short positions at **10:00:00 IST** and closing them at **17:15:00 IST**, the strategy captures this terminal decay window while completely sidestepping overnight gap risk.

### Delta-Neutral Statistical Probability
A **Short Strangle** consists of selling an out-of-the-money Call option (CE) and an out-of-the-money Put option (PE) simultaneously.

* **Target Call Delta ($\Delta_{CE}$):** $\approx +0.10$ ($\pm 0.02$)
* **Target Put Delta ($\Delta_{PE}$):** $\approx -0.10$ ($\pm 0.02$)
* **Net Position Delta ($\Delta_{Net}$):** $\Delta_{CE} + \Delta_{PE} \approx +0.10 + (-0.10) = 0.00$

In option pricing theory, absolute delta $|\Delta|$ serves as a first-order proxy for the risk-neutral probability that an option expires in-the-money (ITM):

$$P(\text{ITM}) \approx |\Delta| \approx 0.10 \implies P(\text{OTM Worthless}) \approx 0.90\ (90\%)$$

By deploying short strangle legs at approximately $10$-Delta, both legs statistically enjoy an approximately **90% theoretical probability of expiring out-of-the-money**, yielding a wide non-directional profit corridor around current Bitcoin spot price.

---

## 2. Dynamic Strike Selection Engine

The bot never hardcodes strikes or uses static offset distances. It dynamically queries live option chains to select optimal strikes based on market Greeks.

### Greek Delta Targeting Criteria
Every morning at 10:00:00 IST, `services/delta_calculator.py` calls:
1. `GET /v2/tickers`: Retrieves real-time implied volatility (IV), Greeks ($\Delta, \Gamma, \Theta, \nu$), mark prices, and best bid/ask quotes for all contracts.
2. `GET /v2/products`: Retrieves contract metadata including strike prices, underlying asset, and contract type (`call_options` vs `put_options`).

For every contract matching the target daily expiry date, the engine calculates the absolute delta deviation from target $0.10$:

$$\text{Delta Diff} = \big||\Delta| - 0.10\big|$$

The contract minimizing $\text{Delta Diff}$ is selected for each leg.

### Expiry Date Determination (`DDMMYY`)
Delta Exchange formats contract symbols using a strict naming pattern:
- Call format: `C-BTC-<STRIKE>-<DDMMYY>` (e.g., `C-BTC-75400-121126`)
- Put format: `P-BTC-<STRIKE>-<DDMMYY>` (e.g., `P-BTC-72000-121126`)

Because settlement occurs at 17:30 IST:
- If current time is **before 17:30 IST**, target expiry date is **today** (`current_ist.date()`).
- If current time is **after 17:30 IST**, target expiry date rolls over to **tomorrow** (`current_ist.date() + timedelta(days=1)`).

---

## 3. Safety & Liquidity Sanity Filters

Crypto derivatives orderbooks can become illiquid during low-volume sessions. Submitting market orders into thin orderbooks leads to catastrophic fill slippage. The selection engine enforces **3 mandatory liquidity filters** before a strike can qualify:

### Filter 1: Active Orderbook Liquidity (`best_bid > 0`)
* **Rule:** `if best_bid <= 0: continue`
* **Purpose:** Ensures active buy limit orders are present in the orderbook. Selling into an orderbook with zero bids either causes order rejection or fills at an absurdly low price.

### Filter 2: Minimum Premium Economic Cutoff (`mark_price >= 5.0 USD`)
* **Rule:** `if mark_price < 5.0: continue`
* **Purpose:** Eliminates dead options trading below \$5 USD. Selling contracts with \$1 or \$2 of premium yields negligible return while still incurring exchange trading fees and margin lockup.

### Filter 3: Maximum Spread Slippage Barrier (`Spread Ratio <= 0.40`)
* **Rule:** 
  $$\text{Spread Ratio} = \frac{\text{best\_ask} - \text{best\_bid}}{\text{mark\_price}} \le 0.40$$
* **Purpose:** Rejects contracts where the bid-ask gap exceeds $40\%$ of the mark price. In illiquid contracts, a wide spread causes the market sell order to fill at a steep discount to fair value. When the 75% Bracket SL is subsequently calculated on this discounted fill, the fair mark price immediately triggers the stop-loss, causing an instantaneous, avoidable loss.

---

## 4. Order Execution & Stop-Loss Protocol

```
[10:00:00 IST]
      │
      ▼
Market Sell CE & PE (Sequential Execution)
      │
      ▼
⏳ 10-Second Countdown (Matching Engine Settlement)
      │
      ▼
GET /v2/positions (Extract Real Fill Prices)
      │
      ▼
Calculate 75% SL = Fill Price × 1.75
      │
      ▼
POST /v2/orders/bracket (Attach Pure Market Stops)
      │
      ▼
⏳ 10-Second Countdown (Stop Orderbook Registration)
      │
      ▼
GET /v2/orders?state=open (Verify bracket_order == True)
      │
      ▼
Dispatch Verified Telegram Notification
```

### Sequential Market Sell Execution
At 10:00:00 IST, the bot submits two market sell orders via `POST /v2/orders`:
- CE: `{"product_id": ce_id, "size": LOT_SIZE, "side": "sell", "order_type": "market_order"}`
- PE: `{"product_id": pe_id, "size": LOT_SIZE, "side": "sell", "order_type": "market_order"}`

### The 10-Second Matching Engine Settlement Wait
Exchange trade processing is asynchronous. Immediately calling `/v2/positions` within milliseconds often returns empty data or stale average entry rates. The bot pauses for **10 full seconds** with a terminal countdown, allowing the exchange ledger to finalize position settlement.

### Real Fill Discovery via `/v2/positions`
The bot queries `GET /v2/positions?underlying_asset_symbol=BTC` and reads the exact, realized `entry_price` recorded by the exchange (e.g., CE filled at \$44.00, PE filled at \$101.30).

### The 75% Pure Stop-Market Bracket Order
Using realized fill rates, the stop-loss trigger price is computed:

$$\text{Trigger Price} = \text{round}(\text{Real Entry Price} \times 1.75,\, 2)$$

The order is transmitted to `POST /v2/orders/bracket`:
```json
{
  "product_id": 208989,
  "stop_loss_order": {
    "order_type": "market_order",
    "stop_price": "77.0"
  },
  "bracket_stop_trigger_method": "last_traded_price"
}
```

#### Why Pure Stop-Market (No Limit Price)?
In volatile crypto breakouts, Stop-Limit orders often fail: the market price skips past the limit price, leaving short options unfilled. A **Pure Stop-Market Order** guarantees execution by executing an unconditional market buy the moment the Last Traded Price touches the trigger.

### Post-Placement Bracket Verification
The bot pauses for another 10 seconds, then queries `GET /v2/orders?state=open`. It verifies that:
1. `bracket_order == True` on each leg.
2. The registered `stop_price` matches within \$0.20 of the expected trigger.

---

## 5. Fault-Tolerant Atomic Rollback Engine

### Single-Leg Execution Risk Breakdown
In options trading, holding an unhedged single short leg is an existential risk:
- If a Call option is sold naked without a Put or stop, an unexpected spot pump results in unlimited upside loss.
- If Leg 1 (CE) fills but Leg 2 (PE) fails (e.g., margin cutoff, tick size change, or network timeout), normal bots abort, leaving Leg 1 naked with no stop-loss.

### Atomic Rollback Sequence
In `services/order_manager.py`:
```
   Order 1: Market Sell CE (FILLED)
                 │
                 ▼
   Order 2: Market Sell PE (FAILED / REJECTED)
                 │
                 ▼
      [TRIGGER ATOMIC ROLLBACK]
                 │
                 ▼
   Emergency Market Buy CE (FILLED)
                 │
                 ▼
      Portfolio 100% FLAT (Zero Exposure)
                 │
                 ▼
      Send Telegram Critical Incident Alert
```

If `pe_sell_res` is False, the engine immediately submits:
```json
{
  "product_id": ce_id,
  "size": LOT_SIZE,
  "side": "buy",
  "order_type": "market_order"
}
```
The strategy then aborts safely with zero open exposure.

---

## 6. Guaranteed EOD Square-Off & Settlement

### The 17:15:00 IST Square-Off Trigger
Delta Exchange daily options settle at **17:30:00 IST**. To avoid physical settlement volatility, pin risk, and exchange settlement fees, `jobs/2_exit_job.py` triggers at **17:15:00 IST** (15 minutes prior).

### 3-Attempt Purge & Verification Loop
The square-off engine executes `square_off_with_retry(max_retries=3, retry_delay=4)`:

```
[Attempt 1/3] ──► Purge All Orders (DELETE /v2/orders/all)
              ──► Scan Active Positions (size != 0)
              ──► Market Buy Open Short Legs
              ──► ⏳ Wait 4s
              ──► Query /v2/positions: Are positions == 0?
                    ├─► YES: Log SUCCESS, Send FLAT Alert ✅
                    └─► NO:  Proceed to Attempt 2/3
```

### Emergency Escalation Protocol
If positions remain open after all 3 attempts (due to extreme API outages or liquidity locks):
1. State is updated to `FAILED_EXIT` in `data/state.json`.
2. A **`🚨🚨 [CRITICAL EMERGENCY] AUTO SQUARE-OFF FAILED! 🚨🚨`** alert is dispatched to Telegram with remaining contract IDs and quantities, instructing the user to close positions manually before the 17:30 IST deadline.

---

## 7. Operational Parameter Reference

| Parameter | Value | Location in Codebase |
| :--- | :--- | :--- |
| **Strategy Style** | Intraday Short Strangle | `jobs/1_entry_job.py` |
| **Target Greek Delta ($\Delta$)** | $0.10 \pm 0.02$ | `services/delta_calculator.py` |
| **Minimum Option Premium** | $\ge \$5.00\text{ USD}$ | `services/delta_calculator.py` |
| **Maximum Bid-Ask Spread Ratio** | $\le 40\%\ (0.40)$ | `services/delta_calculator.py` |
| **Order Type (Entry)** | Market Sell (`market_order`) | `services/order_manager.py` |
| **Stop-Loss Multiplier** | $+75\%\ (1.75\times)$ | `services/order_manager.py` |
| **Stop-Loss Execution Type** | Pure Market Bracket Stop | `services/order_manager.py` |
| **Settlement Wait Buffers** | $10\text{ seconds} \times 2$ | `services/order_manager.py` |
| **Entry Schedule** | `10:00:00 IST` | Crontab / `1_entry_job.py` |
| **Exit Schedule** | `17:15:00 IST` | Crontab / `2_exit_job.py` |
| **Square-Off Max Retries** | $3\text{ attempts}$ ($4\text{s}$ backoff) | `services/order_manager.py` |
| **Overnight Position Exposure** | $0\text{ (100% FLAT)}$ | `jobs/2_exit_job.py` |

---

**Algorithmic execution. Cryptographic authentication. Systematic risk control.**


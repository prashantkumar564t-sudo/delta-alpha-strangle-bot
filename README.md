# ⚡ Delta Alpha Strangle Trading Bot

[![Dependencies](https://img.shields.io/badge/Dependencies-Standard%20Library%20Only-success?style=for-the-badge&logo=python&logoColor=white)](requirements.txt)
[![Target Exchange](https://img.shields.io/badge/Exchange-Delta%20Exchange%20India-orange?style=for-the-badge)](https://india.delta.exchange)
[![Platform](https://img.shields.io/badge/Platform-Termux%20Android%20Ready-blue?style=for-the-badge&logo=android&logoColor=white)](https://termux.dev)
[![Python Version](https://img.shields.io/badge/Python-3.8%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Security](https://img.shields.io/badge/Auth-HMAC--SHA256%20Secured-red?style=for-the-badge)](core/api_client.py)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

> **Autonomous, delta-neutral 10-delta options selling bot designed for lightweight execution on Termux / Linux.**

An institutional-grade, fully automated **Bitcoin (BTC) Short Strangle** trading bot tailored specifically for **Delta Exchange India**. It sells Out-Of-The-Money (OTM) 10-Delta Call and Put options on daily expirations to harvest accelerated intraday **Theta (Time Decay)**, protected by a **Dual-Verified 75% Pure Market Bracket Stop-Loss Shield**.

Engineered with **Zero External Dependencies** (`requirements.txt` is 100% empty), the entire system operates exclusively using Python's native standard library (`urllib`, `hmac`, `hashlib`, `json`, `time`, `os`, `sys`). This guarantees zero build-tool crashes, negligible RAM consumption, and rock-solid 24/7 reliability on an Android device running **Termux** or any low-spec Linux cloud server.

---

## 📑 Table of Contents

- [1. Strategy & Mathematical Logic](#1-strategy--mathematical-logic)
  - [Why BTC 10-Delta Short Strangle?](#why-btc-10-delta-short-strangle)
  - [Dynamic 10-Delta Strike Selection](#dynamic-10-delta-strike-selection)
  - [Morning Entry Protocol (10:00 AM IST)](#morning-entry-protocol-1000-am-ist)
  - [The 10-Second Settlement Delay (Matching Engine Settle)](#the-10-second-settlement-delay-matching-engine-settle)
  - [Real Fill Discovery from `/v2/positions`](#real-fill-discovery-from-v2positions)
  - [75% Pure Stop-Market Bracket SL (`/v2/orders/bracket`)](#75-pure-stop-market-bracket-sl-v2ordersbracket)
  - [10-Second Bracket Verification Protocol](#10-second-bracket-verification-protocol)
  - [Evening Auto Square-Off (05:15 PM IST)](#evening-auto-square-off-0515-pm-ist)
- [2. System Architecture & Workflow](#2-system-architecture--workflow)
  - [Workflow Diagram: Job 1 (Morning Entry & Shield)](#workflow-diagram-job-1-morning-entry--shield-1000-am-ist)
  - [Workflow Diagram: Job 2 (Evening Auto Square-Off)](#workflow-diagram-job-2-evening-auto-square-off-0515-pm-ist)
  - [Zero External Dependencies Architecture Table](#zero-external-dependencies-architecture-table)
- [3. Repository Directory Structure](#3-repository-directory-structure)
- [4. Configuration & Environment Setup](#4-configuration--environment-setup)
  - [Step 1: Obtain Delta Exchange India API Keys](#step-1-obtain-delta-exchange-india-api-keys)
  - [Step 2: Create Telegram Bot & Obtain Chat ID](#step-2-create-telegram-bot--obtain-chat-id)
  - [Step 3: Setup `.env` File](#step-3-setup-env-file)
- [5. Local Testing & Verification (PC / Laptop)](#5-local-testing--verification-pc--laptop)
  - [Test 1: Verify Telegram Bot Connectivity](#test-1-verify-telegram-bot-connectivity)
  - [Test 2: Verify Delta Authentication & Account Balances](#test-2-verify-delta-authentication--account-balances)
  - [Manual Execution of Job 1 (Entry & Bracket SL)](#manual-execution-of-job-1-entry--bracket-sl)
  - [Manual Execution of Job 2 (Square-Off)](#manual-execution-of-job-2-square-off)
- [6. Complete 24/7 Termux Setup Guide (Android Mobile)](#6-complete-247-termux-setup-guide-android-mobile)
  - [Step 1: Install Termux via F-Droid](#step-1-install-termux-via-f-droid)
  - [Step 2: Install Essential Linux Packages](#step-2-install-essential-linux-packages)
  - [Step 3: Prevent Android CPU Sleep (Wake-Lock)](#step-3-prevent-android-cpu-sleep-wake-lock)
  - [Step 4: Clone Repository & Configure Environment](#step-4-clone-repository--configure-environment)
  - [Step 5: Setup Cron Daemon & Crontab](#step-5-setup-cron-daemon--crontab)
  - [Step 6: Live Log Monitoring](#step-6-live-log-monitoring)
- [7. State Management (`data/state.json`)](#7-state-management-datastatejson)
- [8. Real-time Telegram Notifications](#8-real-time-telegram-notifications)
- [9. Risk Disclaimer & Security Best Practices](#9-risk-disclaimer--security-best-practices)

---

## 1. Strategy & Mathematical Logic

### Why BTC 10-Delta Short Strangle?
A Short Strangle involves simultaneously shorting an Out-Of-The-Money (OTM) Call option and an OTM Put option on the same underlying asset:
* **Call Leg (CE):** Strike selected with Greek Delta $\Delta \approx +0.10$ ($\sim 90\%$ statistical probability of expiring worthless OTM).
* **Put Leg (PE):** Strike selected with Greek Delta $\Delta \approx -0.10$ ($\sim 90\%$ statistical probability of expiring worthless OTM).

Delta Exchange offers daily Bitcoin (BTC) options settling at **05:30 PM IST (12:00 UTC)**. Option premium decay (**Theta $\Theta$**) follows an exponential curve: decay speeds up aggressively in the final 8 hours prior to settlement. By entering the market at **10:00 AM IST** and exiting at **05:15 PM IST**, the bot extracts this intraday Theta collapse while staying far away from spot price action.

```
                            PROFIT & LOSS PROFILE
                          Max Profit (Both Premiums)
                              ┌───────────────┐
                              │               │
            Loss              │               │              Loss
      ────────────────────────┼───────────────┼────────────────────────
                              ▲               ▲
                         Put Strike      Call Strike
                       (Delta ~ -0.10) (Delta ~ +0.10)
```

### Dynamic 10-Delta Strike Selection
The bot does not hardcode strike levels. Every morning at 10:00 AM IST, `services/delta_calculator.py`:
1. Constructs today's contract expiry suffix in `DDMMYY` format (e.g., `101126`).
2. Calls `GET /v2/tickers` to fetch live Greeks and quotes for all contracts.
3. Calls `GET /v2/products` to fetch product symbols, contract types, and strike prices.
4. Identifies active contracts ending with today's expiry suffix.
5. Computes absolute delta deviation:
   $$\text{Delta Difference} = \big||\Delta| - 0.10\big|$$
6. Picks the Call and Put strike with the absolute minimum deviation from target $0.10$.

### Morning Entry Protocol (10:00 AM IST)
Once the optimal CE and PE contracts are selected, `services/order_manager.py` places two immediate Market Sell orders via `POST /v2/orders`:
```json
{
  "product_id": 208591,
  "size": 1,
  "side": "sell",
  "order_type": "market_order"
}
```

### The 10-Second Settlement Delay (Matching Engine Settle)
In crypto derivatives, market order fills are executed asynchronously. Attempting to fetch positions immediately (sub-second) can result in stale averages or empty responses. 

The bot initiates an active terminal countdown of **10 full seconds** (`time.sleep(1)` loop). This deliberate pause guarantees that Delta's matching engine has settled the trade, updated the account balance, and registered the exact filled entry price in the exchange position ledger.

### Real Fill Discovery from `/v2/positions`
Rather than calculating Stop-Loss on estimated orderbook quotes or theoretical mark prices, the bot calls:
```http
GET /v2/positions?underlying_asset_symbol=BTC
```
It reads the true, executed `entry_price` recorded by the exchange engine for both legs (e.g., CE filled @ \$20.00, PE filled @ \$10.00).

### 75% Pure Stop-Market Bracket SL (`/v2/orders/bracket`)
Using real fill prices, the bot computes a $+75\%$ stop trigger:
$$\text{SL Trigger Price} = \text{round}(\text{Real Executed Entry Price} \times 1.75,\, 2)$$

* If CE sold at **\$20.00**, Stop-Loss triggers at **\$35.00** ($20 \times 1.75$).
* If PE sold at **\$10.00**, Stop-Loss triggers at **\$17.50** ($10 \times 1.75$).

The bot attaches this stop directly to the open position using `POST /v2/orders/bracket`:
```json
{
  "product_id": 208591,
  "stop_loss_order": {
    "order_type": "market_order",
    "stop_price": "35.0"
  },
  "bracket_stop_trigger_method": "last_traded_price"
}
```

#### Why Pure Market Stop (No Limit Price Cap)?
In traditional Stop-Limit orders, if the market spikes violently, the market price can bypass the limit price, leaving naked short options unclosed (order freeze). By issuing a **pure stop-market order** via the bracket endpoint, the moment the Last Traded Price touches the stop trigger, the order converts into an unconditional market buy, protecting the account from catastrophic black-swan spikes.

### 10-Second Bracket Verification Protocol
After submitting the bracket orders, the bot pauses for another **10 seconds** to allow Delta's matching engine to register the stop orders in the stop orderbook. It then queries:
```http
GET /v2/orders?state=open
```
It iterates through open orders and verifies that:
1. An open order exists for each `product_id`.
2. `bracket_order == True`.
3. The registered `stop_price` matches within \$0.20 of the expected trigger.

Only when both legs pass this verification does the bot log success and trigger the Telegram alert.

### Evening Auto Square-Off (05:15 PM IST)
Daily options on Delta Exchange settle at **05:30 PM IST**. To prevent unexpected delivery fees, physical settlement risks, or last-minute pinning volatility:
1. At **05:15 PM IST**, `jobs/2_exit_job.py` fires.
2. It sends `DELETE /v2/orders/all` to flush any lingering stop orders.
3. It fetches `/v2/positions?underlying_asset_symbol=BTC` to find any remaining open short positions (`size < 0`). If one leg was already stopped out during the day, it is safely ignored.
4. For all remaining open legs, it sends `POST /v2/orders` with `side: "buy"` and `order_type: "market_order"`.
5. The portfolio returns to **100% FLAT (cash)** with **zero overnight risk**.

---

## 2. System Architecture & Workflow

### Workflow Diagram: Job 1 (Morning Entry & Shield, 10:00 AM IST)

```
[10:00 AM IST] ── Cronie / Manual Trigger
       │
       ▼
[Step 1: Strike Selection]
  ├─► GET /v2/tickers (Fetch Greeks, Mark Prices, Quotes)
  ├─► GET /v2/products (Filter today's DDMMYY expiry)
  └─► Select minimum ||Delta| - 0.10| for CE and PE
       │
       ▼
[Step 2: Market Sell Execution]
  ├─► POST /v2/orders ➔ Market Sell CE (Size = LOT_SIZE)
  └─► POST /v2/orders ➔ Market Sell PE (Size = LOT_SIZE)
       │
       ▼
[Step 3: Settlement Countdown]
  └─► ⏳ Wait 10 Seconds (Matching Engine Settlement)
       │
       ▼
[Step 4: Real Fill Discovery]
  └─► GET /v2/positions ➔ Read real executed entry_price
       │
       ▼
[Step 5: Attach 75% Bracket Stop-Loss]
  ├─► Calculate SL = round(entry_price * 1.75, 2)
  ├─► POST /v2/orders/bracket (CE Pure Market Stop)
  └─► POST /v2/orders/bracket (PE Pure Market Stop)
       │
       ▼
[Step 6: Registration Countdown]
  └─► ⏳ Wait 10 Seconds (Stop Orderbook Registration)
       │
       ▼
[Step 7: Verification Barrier]
  └─► GET /v2/orders?state=open ➔ Verify bracket_order == True & Stop Price
       │
       ▼
[Step 8: State Recording & Alerting]
  ├─► Write active trade to data/state.json
  └─► Send Markdown Alert to Telegram Bot
```

### Workflow Diagram: Job 2 (Evening Auto Square-Off, 05:15 PM IST)

```
[05:15 PM IST] ── Cronie / Manual Trigger
       │
       ▼
[Step 1: Cancel Pending Orders]
  └─► DELETE /v2/orders/all (Purge all open bracket stops)
       │
       ▼
[Step 2: Scan Open Positions]
  └─► GET /v2/positions?underlying_asset_symbol=BTC
       │
       ▼
[Step 3: Market Buy Remaining Legs]
  ├─► If short position exists (size < 0):
  │     └─► POST /v2/orders (side: "buy", order_type: "market_order")
  └─► If already stopped out during day: Skip
       │
       ▼
[Step 4: State Finalization]
  └─► Update data/state.json (status: "CLOSED", exit_timestamp)
       │
       ▼
[Step 5: Telegram Flat Confirmation]
  └─► Send Flat Status Alert (Zero Overnight Risk Confirmed)
```

### Zero External Dependencies Architecture Table

| Standard Library Module | Exact Purpose in Codebase | Replaced Heavy Third-Party Library |
| :--- | :--- | :--- |
| `urllib.request` | Communicates with Delta REST API and Telegram Bot API via native HTTPS. | `requests`, `urllib3`, `httpx` |
| `hmac` & `hashlib` | Generates official cryptographic HMAC-SHA256 signatures for Delta API authentication. | `cryptography`, `pycryptodome` |
| `json` | Serializes payloads with strict `separators=(',', ':')` matching wire payload to signature. | `ujson`, `orjson` |
| `time` & `datetime` | Handles Unix timestamps, countdown delays, and IST (`UTC+5:30`) daily expiry math. | `pytz`, `pandas` |
| `os` & `sys` | In-built line-by-line `.env` parser supporting `utf-8-sig` (handling Windows BOM characters). | `python-dotenv` |

> **Why is this critical for Android Termux?**  
> External libraries often require C-compilers, GCC tools, or large wheel binaries (`pandas`, `numpy`, `cryptography`) that frequently fail to compile on Android ARM architectures or run out of memory. By using Python's standard library only, this bot installs in seconds with zero build dependencies.

---

## 3. Repository Directory Structure

```text
delta-alpha-strangle-bot/
├── .env.example              # Template configuration file for API & Telegram secrets
├── .gitignore                # Strictly excludes .env, state.json, cache, and logs
├── README.md                 # Production documentation (this file)
├── requirements.txt          # Intentionally empty (Zero External Dependencies)
├── main.py                   # Master entrypoint stub
│
├── config/
│   ├── __init__.py
│   └── settings.py           # Native environment loader and settings manager
│
├── core/
│   ├── __init__.py
│   └── api_client.py         # Standard library HTTP engine with HMAC-SHA256 signing
│
├── data/
│   └── state.json            # Dynamic runtime state (active positions, entry fills, stops)
│
├── jobs/
│   ├── __init__.py
│   ├── 1_entry_job.py        # Morning 10:00 AM IST execution script (Entry + 75% Bracket SL)
│   └── 2_exit_job.py         # Evening 05:15 PM IST execution script (Auto Square-off)
│
├── logs/
│   └── .gitkeep              # Directory for execution logs
│
├── services/
│   ├── __init__.py
│   ├── delta_calculator.py   # Options chain parser & 10-Delta strike filtering engine
│   ├── notifier.py           # Native urllib Telegram alert broadcaster
│   └── order_manager.py      # Dual-verification execution, bracket placement, and square-off
│
└── tests/
    ├── __init__.py
    ├── test_auth.py          # Verifies Delta API authentication and wallet balance
    ├── test_telegram.py      # Verifies Telegram Bot token and chat delivery
    └── test_execution_flow.py# Complete end-to-end dry run on Testnet
```

---

## 4. Configuration & Environment Setup

### Step 1: Obtain Delta Exchange India API Keys
1. Log in to [Delta Exchange India](https://india.delta.exchange) (or [Delta Testnet](https://cdn-ind.testnet.deltaex.org)).
2. Navigate to **Settings > API Keys > Create New API Key**.
3. Configure Permissions:
   * **Read:** Enabled ✅
   * **Write (Trading):** Enabled ✅
   * **Withdrawal:** **DISABLED ❌** (Never grant withdrawal permissions to any trading bot).
4. Save your **API Key** and **API Secret** in a secure location.

### Step 2: Create Telegram Bot & Obtain Chat ID
1. Open Telegram and search for [@BotFather](https://t.me/BotFather).
2. Send `/newbot`, provide a name and username, and copy the generated **Bot Token** (e.g., `123456789:ABCdefGHI...`).
3. Search for [@userinfobot](https://t.me/userinfobot) and tap `/start` to get your numeric **Chat ID** (e.g., `987654321`).
4. Start a chat with your newly created bot by clicking `/start` so it has permission to message you.

### Step 3: Setup `.env` File
Copy `.env.example` to `.env`:

```bash
# On Linux / Termux / macOS:
cp .env.example .env

# On Windows PowerShell:
Copy-Item .env.example .env
```

Open `.env` and fill in your credentials:

```ini
# Delta Exchange API Credentials
DELTA_API_KEY=your_actual_api_key_here
DELTA_API_SECRET=your_actual_api_secret_here

# API Gateway Base URL
# Testnet (India):    https://cdn-ind.testnet.deltaex.org
# Production (India): https://api.india.delta.exchange
# Global Production:  https://api.delta.exchange
DELTA_BASE_URL=https://cdn-ind.testnet.deltaex.org

# Position Sizing (Contracts per leg)
LOT_SIZE=1

# Telegram Alerts
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=987654321
```

---

## 5. Local Testing & Verification (PC / Laptop)

Before deploying live or running on Termux, verify your setup locally.

### Test 1: Verify Telegram Bot Connectivity
```bash
python tests/test_telegram.py
```
*Expected Output:*
```text
Checking Telegram Configuration...
Bot Token: Configured (12345678...)
Chat ID:   987654321

Sending test message to Telegram...
[SUCCESS] Message successfully delivered to Telegram!
```

### Test 2: Verify Delta Authentication & Account Balances
```bash
python tests/test_auth.py
```
*Expected Output:*
```text
Connecting to: https://cdn-ind.testnet.deltaex.org/v2/wallet/balances
[SUCCESS] Demo Account Authenticated!
Response: True
 - Asset: USDT | Balance: 10000.00
```

### Manual Execution of Job 1 (Entry & Bracket SL)
```bash
python jobs/1_entry_job.py
```
**What happens on execution:**
1. Fetches current BTC 10-Delta Call and Put options for today's daily expiry.
2. Market sells both legs.
3. Displays a live 10-second countdown in terminal.
4. Queries `/v2/positions`, retrieves the filled `entry_price`, and calculates the $+75\%$ stop-loss.
5. Attaches pure market bracket stop orders.
6. Displays a second 10-second verification countdown.
7. Checks `/v2/orders?state=open` and verifies active bracket stop-losses.
8. Writes trade state to `data/state.json`.
9. Delivers a verified trade report to your Telegram chat.

### Manual Execution of Job 2 (Square-Off)
```bash
python jobs/2_exit_job.py
```
**What happens on execution:**
1. Sends `DELETE /v2/orders/all` cancelling all open stop orders.
2. Market buys all open short positions.
3. Updates `data/state.json` status to `"CLOSED"`.
4. Sends a square-off confirmation to Telegram verifying a 100% flat portfolio.

---

## 6. Complete 24/7 Termux Setup Guide (Android Mobile)

Run your trading bot 24/7 on an Android phone with zero hosting fees.

### Step 1: Install Termux via F-Droid
* Download and install the latest Termux APK from **[F-Droid](https://f-droid.org/packages/com.termux/)** or the **[Termux GitHub Releases](https://github.com/termux/termux-app/releases)**.  
*(Do not install from Google Play Store; that version is deprecated).*

### Step 2: Install Essential Linux Packages
Open Termux and execute:
```bash
pkg update && pkg upgrade -y
pkg install python git cronie termux-api nano -y
```

### Step 3: Prevent Android CPU Sleep (Wake-Lock)
Android battery management kills background applications by default. You must disable this:
1. Go to your phone's **Settings > Apps > Termux > Battery** and select **"Unrestricted"** (No restrictions).
2. In Termux, run:
   ```bash
   termux-wake-lock
   ```
   *(A persistent notification will appear confirming Termux is holding a wake-lock).*

### Step 4: Clone Repository & Configure Environment
```bash
cd ~
git clone https://github.com/your-username/delta-alpha-strangle-bot.git
cd delta-alpha-strangle-bot
cp .env.example .env
nano .env
```
Paste your API keys, Base URL, and Telegram details in `nano`. Press `Ctrl + O` then `Enter` to save, and `Ctrl + X` to exit.

Run the test suite to verify:
```bash
python tests/test_auth.py
python tests/test_telegram.py
```

### Step 5: Setup Cron Daemon & Crontab

1. **Start the cron daemon:**
   ```bash
   crond
   ```

2. **Auto-start `crond` whenever Termux opens:**
   ```bash
   echo "crond" >> ~/.bashrc
   ```

3. **Open the crontab configuration:**
   ```bash
   crontab -e
   ```

4. **Add the two automation jobs (IST Timings):**
   *(Replace `/data/data/com.termux/files/home` with your actual `$HOME` path if customized):*
   ```cron
   # ====================================================================
   # DELTA ALPHA STRANGLE AUTOMATION CRON (IST TIMEZONE)
   # ====================================================================
   # Job 1: Every day at 10:00 AM IST -> Execute Entry & 75% Bracket SL
   00 10 * * * cd /data/data/com.termux/files/home/delta-alpha-strangle-bot && /data/data/com.termux/files/usr/bin/python jobs/1_entry_job.py >> logs/trading.log 2>&1

   # Job 2: Every day at 05:15 PM IST (17:15) -> Auto Square-off & Cleanup
   15 17 * * * cd /data/data/com.termux/files/home/delta-alpha-strangle-bot && /data/data/com.termux/files/usr/bin/python jobs/2_exit_job.py >> logs/trading.log 2>&1
   ```

> **Timezone Note:**  
> Verify your Termux time by running `date`. If your Termux runs in UTC:
> * **10:00 AM IST** = **04:30 AM UTC** (`30 04 * * *`)
> * **05:15 PM IST** = **11:45 AM UTC** (`45 11 * * *`)

### Step 6: Live Log Monitoring
To monitor real-time execution logs directly from your phone:
```bash
tail -f ~/delta-alpha-strangle-bot/logs/trading.log
```

---

## 7. State Management (`data/state.json`)

To ensure transparency and recoverability, the bot writes full trade parameters to `data/state.json`:

```json
{
  "trade_date": "2026-11-10",
  "entry_timestamp": "2026-11-10T10:00:15.528875",
  "ce": {
    "product_id": 208591,
    "symbol": "C-BTC-75200-101126",
    "entry_price": 20.0,
    "sl_trigger": 35.0,
    "sl_verified": true
  },
  "pe": {
    "product_id": 208924,
    "symbol": "P-BTC-74200-101126",
    "entry_price": 10.0,
    "sl_trigger": 17.5,
    "sl_verified": true
  },
  "status": "CLOSED",
  "exit_timestamp": "2026-11-10T17:15:02.032650",
  "closed_count": 2
}
```

---

## 8. Real-time Telegram Notifications

### Entry Alert (Dispatched at 10:00 AM IST)
```text
🎯 ALPHA STRANGLE ENTRY & SL VERIFIED

🟢 CALL LEG (CE):
• Contract: C-BTC-75200-101126
• Sold @: 20.0 USD
• 75% Bracket SL: 35.0 USD ✅

🔴 PUT LEG (PE):
• Contract: P-BTC-74200-101126
• Sold @: 10.0 USD
• 75% Bracket SL: 17.5 USD ✅

🛡️ Status: Positions Protected by Market Bracket SL
```

### Square-Off Alert (Dispatched at 05:15 PM IST)
```text
🏁 DELTA ALPHA STRANGLE — SQUARE-OFF COMPLETE

🕒 Time: 17:15:02 IST
🧹 Pending Orders: Cancelled
📊 Positions Closed: 2

• C-BTC-75200-101126 : Market Buy (Closed)
• P-BTC-74200-101126 : Market Buy (Closed)

🛡️ Status: Flat (Zero Overnight Risk)
```

---

## 9. Risk Disclaimer & Security Best Practices

### Financial Risk Disclaimer
> **⚠️ WARNING:** Cryptocurrency derivatives trading and naked option selling carry substantial financial risk. While this strategy incorporates a $+75\%$ stop-loss barrier and a strict intraday flat policy, severe market volatility, liquidity vacuums, exchange downtime, or network latency can result in execution slippage. 
> 
> * Always test thoroughly on the **Delta Exchange Testnet** before deploying live funds.
> * Maintain adequate maintenance margin to avoid unexpected account liquidations.
> * Never risk capital you cannot afford to lose. The developers and contributors of this software accept no responsibility for any financial loss.

### Security Best Practices
1. **Never commit `.env` to Git:** The included `.gitignore` protects `.env`. Always verify with `git status` that `.env` is never staged.
2. **Restrict API Key Privileges:** When generating your API key on Delta Exchange, enable **Read** and **Write (Trading)** only. **NEVER enable Withdrawals**.
3. **Use Dedicated IP / Mobile:** If running on Termux, ensure your device has a stable internet connection or fallback SIM mobile data.

---

**Institutional architecture. Zero bloat. Pure algorithmic precision.**

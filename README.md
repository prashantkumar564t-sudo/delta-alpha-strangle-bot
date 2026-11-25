# ⚡ Delta Alpha Strangle Trading Bot

[![Dependencies](https://img.shields.io/badge/Dependencies-Standard%20Library%20Only-success?style=for-the-badge&logo=python&logoColor=white)](requirements.txt)
[![Target Exchange](https://img.shields.io/badge/Exchange-Delta%20Exchange%20India%20%2F%20Global-orange?style=for-the-badge)](https://india.delta.exchange)
[![Platform](https://img.shields.io/badge/Platform-Termux%20Android%20%7C%20Linux%20VPS-blue?style=for-the-badge&logo=android&logoColor=white)](https://termux.dev)
[![Python Version](https://img.shields.io/badge/Python-3.8%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Security](https://img.shields.io/badge/Auth-HMAC--SHA256%20%26%20Static%20Tunnel-red?style=for-the-badge)](core/api_client.py)
[![Test Suite](https://img.shields.io/badge/Tests-46%20Passed%20%7C%20100%25-brightgreen?style=for-the-badge&logo=pytest)](tests/)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

> **An institutional-grade, fully automated 10-Delta Bitcoin (BTC) options selling bot engineered specifically for Delta Exchange. Runs 24/7 on Android Termux or bare-metal Linux VPS with ZERO external Python dependencies.**

---

## 📑 Table of Contents

- [1. Project Overview & Architecture](#1-project-overview--architecture)
  - [Core Philosophy: Zero External Dependencies](#core-philosophy-zero-external-dependencies)
  - [High-Reliability Engineering Highlights](#high-reliability-engineering-highlights)
- [2. Step 1: Obtaining Delta Exchange Testnet Credentials](#2-step-1-obtaining-delta-exchange-testnet-credentials)
- [3. Step 2: Webshare Static Proxy Setup (Bypassing Dynamic IP)](#3-step-2-webshare-static-proxy-setup-bypassing-dynamic-ip)
  - [Why a Static Proxy is Mandatory](#why-a-static-proxy-is-mandatory)
  - [ISP DNS Block Workaround (Jio / Airtel in India)](#isp-dns-block-workaround-jio--airtel-in-india)
  - [Obtaining Proxy Credentials](#obtaining-proxy-credentials)
  - [Whitelisting Proxy IP in Delta Exchange](#whitelisting-proxy-ip-in-delta-exchange)
- [4. Step 3: Telegram Bot & Telemetry Setup](#4-step-3-telegram-bot--telemetry-setup)
- [5. Step 4: Environment Variables & Security (`.env`)](#5-step-4-environment-variables--security-env)
- [6. Step 5: Local Laptop Verification & Test Suite](#6-step-5-local-laptop-verification--test-suite)
  - [Running Unit Tests (46 Tests)](#running-unit-tests-46-tests)
  - [Test 1: Authentication & Balance](#test-1-authentication--balance)
  - [Test 2: Telegram Alerts](#test-2-telegram-alerts)
  - [Test 3: End-to-End Live Execution Pipeline](#test-3-end-to-end-live-execution-pipeline)
- [7. Step 6: Complete Mobile (Termux) Installation & Setup](#7-step-6-complete-mobile-termux-installation--setup)
- [8. Step 7: Production Scheduling via Crontab (Cronie)](#8-step-7-production-scheduling-via-crontab-cronie)
  - [Crontab Configuration](#crontab-configuration)
  - [Android Battery Optimization Bypass](#android-battery-optimization-bypass)
  - [Live Log Monitoring](#live-log-monitoring)
- [9. Strategy & Operational Logic](#9-strategy--operational-logic)
- [10. Repository Directory Structure](#10-repository-directory-structure)
- [11. Risk Disclaimer & Safety Rules](#11-risk-disclaimer--safety-rules)
- [12. Strategic Production Roadmap (`ROADMAP.md`)](ROADMAP.md)

---

## 1. Project Overview & Architecture

**Delta Alpha Strangle Bot** is an autonomous quantitative trading system designed to monetize intraday **Theta (Time Decay)** on daily Bitcoin (BTC) options traded on Delta Exchange India (`cdn-ind.testnet.deltaex.org` / `api.india.delta.exchange`).

The bot strictly executes a **Pure Intraday Short Strangle (Combo A Architecture)** according to verified institutional rules:

1. **2-Phase Entry Engine:**
   - **Phase 1 (`09:58:00`–`09:59:59 IST`) — Pre-Warm Target Lock:** Scans the 0DTE option chain 2 minutes before market open. Selects candidate Call (CE) and Put (PE) strikes targeting Greek Delta $\approx 0.10$ within absolute bounds $[0.07, 0.13]$ and minimum mark price $\ge \$5.00$. Uses direct public REST endpoints (**0 KB proxy bandwidth consumed**). Emits Phase 1 Pre-Warm Telegram Telemetry to private chat and public channel. Continuously polls every 5s; if spot moves and delta drifts outside $[0.07, 0.13]$, automatically re-locks targets with an update alert.
   - **Phase 2 (`10:00:00`–`10:02:00 IST`) — Sniper Execution Retry Loop:** At exactly 10:00:00 IST, executes candidate quotes against the 4-layer Anti-Trap liquidity filter. If orderbook spreads or depth are temporarily settling at market open, polls every 5 seconds for up to **120 seconds (24 attempts)** until both legs pass and execute cleanly.
2. **Two-Stage Patience & Dynamic Equal-Leg Fallback Sizing:**
   - **Stage 1 (`0s` to `90s` after 10:00:00 IST):** Mandatory **Full Target Patience**. Requires full `TARGET_LOTS` ($1,000\text{ lots} = 1.0\text{ BTC}$) on both legs under the **20% L1 Footprint Rule** ($\text{Top Bid Depth} \ge 5,000\text{ lots}$). Prevents premature auto-downsizing during early 10:00 AM market-maker quote placement.
   - **Stage 2 (`90s` to `120s` after 10:00:00 IST):** **Dynamic Equal-Leg Fallback**. If full 1,000 lots are unavailable after 90s, dynamically sizes both legs to:
     $$\text{equal\_lots} = \min(\text{safe\_call},\, \text{safe\_put},\, 1000)$$
     Executes immediately if $\text{equal\_lots} \ge 500\text{ lots}$ ($0.5\text{ BTC}$). If depth yields $< 500\text{ lots}$ across the full 120s, entry is safely skipped with a Telegram notification.
3. **Pre-Trade 4-Layer Anti-Trap Liquidity Filter:**
   - *Layer 1 (Spread Ratio Gate):* $\text{Spread} / \text{Mark} \le 0.080$ ($8.0\%$ maximum spread cap, accommodating institutional 2-tick quotes on \$25–\$40 options).
   - *Layer 2 (Depth Cushion):* Two-Stage allocation with $\text{Top Bid} \times 0.20$ footprint cap and 100-lot absolute tradeable floor.
   - *Layer 3 (Mark Discount):* $(\text{Mark} - \text{Best Bid}) / \text{Mark} \le 0.020$ ($2.0\%$ maximum discount barrier).
   - *Layer 4 (2.5s Snapshot Stability):* Samples book twice 2.5s apart; rejects entry if Best Bid shifts $> 1.5\%$ or Top Bid lots drop $> 50\%$.
4. **Risk Management (Combo A: 100% SL + Cost-to-Cost Trail):**
   - Attaches an initial $+100\%$ Stop-Market Bracket Stop-Loss ($\text{Real Entry Price} \times 2.00$) on each leg.
   - **Cost-to-Cost Trail State Machine:** Monitored every 2 minutes. The instant either leg (CE or PE) triggers its 100% SL, the surviving leg's SL is immediately moved to its exact entry cost ($\text{Real Entry Price} \times 1.00$), locking in zero directional risk (+110.15% backtested net ROI vs. +48.24% with 75% static SL).
   - **Non-Blocking Drawdown Warning:** Evaluates cumulative peak-to-trough equity drawdown against the threshold ($\$1,185.00$). Sends an advisory Telegram warning (`⚠️ DRAWDOWN ALERT: Account drawdown exceeded threshold — strategy needs attention`) while allowing entry execution to continue uninterrupted.
5. **Exit (`17:15:00 IST`):** 15 minutes before the 17:30 IST exchange settlement, executes an automated 3-attempt square-off loop, closes open positions via market buys, and purges all open orders, leaving the account **100% FLAT** overnight.

```
                           DELTA ALPHA BOT ARCHITECTURE
                    
        ┌────────────────────────────────────────────────────────┐
        │            Python 3 Standard Library Engine            │
        │     (urllib.request + hmac + hashlib + json + time)    │
        └───────────────────────────┬────────────────────────────┘
                                    │
                       HTTP / HTTPS Proxy Tunnel
                     (Private Authenticated Calls)
                                    │
                                    ▼
        ┌──────────────────────────────────────────────────────────┐
        │     Dedicated Datacenter Proxy (e.g., 198.51.100.42)     │
        │           (Bypasses Mobile CGNAT Dynamic IPs)            │
        └────────────────────────────┬─────────────────────────────┘
                                    │
                                    ▼
        ┌──────────────────────────────────────────────────────────┐
        │            Delta Exchange India / Global API             │
        │             (IP-Whitelisted REST Gateway)                │
        └──────────────────────────────────────────────────────────┘
```

### Core Philosophy: Zero External Dependencies
Most algorithmic trading repositories rely heavily on third-party libraries such as `requests`, `urllib3`, `pandas`, `ccxt`, and `python-dotenv`. On mobile Linux environments like Android **Termux** or lightweight VPS instances, compiling and maintaining these dependencies often triggers C-extension build failures, memory crashes, or pip version breaks.

This bot is engineered from the ground up to use **strictly Python's built-in standard library**:
- `urllib.request` / `urllib.error`: Native HTTP/HTTPS network client with proxy authentication and direct public endpoints.
- `hmac` & `hashlib`: Cryptographic HMAC-SHA256 signature generator.
- `json`: Wire payload serialization matching signature bytes.
- `time` & `datetime`: Unix epoch timestamps and IST (`UTC+5:30`) daily expiry calculations.
- `os` & `sys`: Custom `.env` line parser supporting UTF-8 and Windows UTF-8 BOM encoding.

`requirements.txt` is intentionally **empty** — clone the repo and run it immediately!

### High-Reliability Engineering Highlights
1. **Static Datacenter Proxy Tunneling:** Routes private authenticated trading API traffic through a dedicated IP address (`urllib.request.ProxyHandler`), solving Delta's strict `ip_not_whitelisted_for_api_key` restrictions, while routing public market quotes directly to preserve proxy bandwidth.
2. **Atomic Single-Leg Rollback:** If the Call (CE) sell fills but the Put (PE) sell gets rejected (due to margin, tick size, or network drop), the engine immediately triggers an emergency Market Buy order to close the naked CE leg, eliminating unhedged overnight exposure.
3. **Dual-Settlement 10s Verifications:** Incorporates two deliberate 10-second countdown waits to allow exchange matching engines to settle fills before querying `/v2/positions` and `/v2/orders`.
4. **3-Attempt Square-off Retry Engine:** The 17:15 IST exit job executes up to 3 purge-and-close cycles with 4-second backoffs, verifies positions count == 0, and dispatches a Critical Emergency Alarm to Telegram if any position remains open.

---

## 2. Step 1: Obtaining Delta Exchange Testnet Credentials

Before risking real capital, test everything on the official Delta Exchange Testnet.

1. Navigate to the **Delta Exchange Testnet Portal**:
   - India Testnet: [https://cdn-ind.testnet.deltaex.org](https://cdn-ind.testnet.deltaex.org)
   - Global Testnet: [https://testnet.deltaex.org](https://testnet.deltaex.org)
2. Log in (or register a demo account). Virtual balances are preloaded.
3. Navigate to **API Keys**:
   - Click on your **Profile Icon** (top right) -> **Settings** -> **API Management / API Keys**.
   - Click **Create New API Key**.
4. Configure Permissions:
   - **Key Name:** `AlphaStrangleBot`
   - **Permissions:** Select **Trading / Orders** ONLY.
   - ⚠️ **CRITICAL SECURITY RULE:** **NEVER enable the "Withdrawal" permission** on any trading bot API key.
   - **IP Whitelist Field:** Leave blank for a moment (we will paste our static proxy IP from Step 2 here).
5. Click **Generate API Key**.
6. Copy both the **API Key** and **API Secret** to a secure temporary location.

---

## 3. Step 2: Webshare Static Proxy Setup (Bypassing Dynamic IP)

### Why a Static Proxy is Mandatory
When running on mobile internet (Jio, Airtel, Vodafone) or home broadband, your Internet Service Provider uses **Carrier-Grade NAT (CGNAT)**. Your outbound public IP changes frequently.

Delta Exchange enforces strict API security: if an API Key has IP Whitelisting enabled, an IP change immediately produces this fatal error:
```json
[HTTP 401] {"error":{"code":"ip_not_whitelisted_for_api_key","context":{"client_ip":"..."}},"success":false}
```
By routing the bot's private authenticated trading calls through a permanent static datacenter proxy, your outbound IP **never changes**, regardless of whether your phone switches between 4G, 5G, or Wi-Fi.

### ISP DNS Block Workaround (Jio / Airtel in India)
If `webshare.io` fails to load due to ISP DNS blocking:
1. On Android: Go to **Settings** -> **Network & Internet** -> **Private DNS**.
2. Select **Private DNS provider hostname** and enter `one.one.one.one` (or `dns.google`).
3. On Windows / Mac: Change adapter DNS to Cloudflare (`1.1.1.1`) or Google (`8.8.8.8`).

### Obtaining Proxy Credentials
1. Sign up for an account at [https://www.webshare.io](https://www.webshare.io) (free tier includes 10 proxies).
2. Extract the connection parameters from the Webshare dashboard:
   - **Proxy IP (Host):** e.g., `198.51.100.42`
   - **Port:** e.g., `8080`
   - **Username:** e.g., `proxy_user_demo`
   - **Password:** e.g., `proxy_pass_sample`

### Whitelisting Proxy IP in Delta Exchange
1. In Delta Exchange API Keys settings, paste the **Proxy IP** (e.g., `198.51.100.42`) into the **IP Whitelist** input box.
2. Save the API Key. Delta will now strictly accept authenticated calls originating from this static IP.

---

## 4. Step 3: Telegram Bot & Telemetry Setup

The bot features a standard-library **Dual-Broadcast Alerting Engine**:

1. **Create the Telegram Bot:**
   - In Telegram, open [@BotFather](https://t.me/BotFather) and send `/newbot`.
   - Copy the HTTP API token (`TELEGRAM_BOT_TOKEN`).
2. **Retrieve Admin Chat ID (`TELEGRAM_CHAT_ID`):**
   - Open [@userinfobot](https://t.me/userinfobot) and tap `/start` to copy your numeric ID.
3. **Optional Public Channel (`TELEGRAM_CHANNEL_ID`):**
   - Add your bot as an Administrator with permission `Post Messages`.
   - Set `TELEGRAM_CHANNEL_ID=-100...` in your `.env`.
4. **Dual-Broadcast Routing Invariants:**
   - **Trade Alerts (Broadcast to Both DM & Channel):**
     - Phase 1 Pre-Warm Lock Telemetry (`09:58:00 IST`).
     - Template 1: Strangle Entry Executed (`10:00:00 IST`) with sizing, fill delay, L1 depth, and 100% SLs.
     - Template 2: Anti-Trap Shield Blocks (`Spread > 8.0%`, `Depth < 500`, `Mark Gap > 2%`, `2.5s Drift`).
     - Template 3: Cost-to-Cost Trail Activated (`Surviving leg moved to 1.0x entry cost`).
     - Template 4: 17:15 IST Daily Session Scorecard (Gross PnL, 4.13% fees, and Net Realized PnL).
   - **System Errors & Warnings (Strictly Isolated to Admin DM):**
     - Drawdown Advisory Warnings (`⚠️ DRAWDOWN ALERT`).
     - Connection retries, execution warnings, and unhandled tracebacks are strictly routed to `TELEGRAM_CHAT_ID` only.

---

## 5. Step 4: Environment Variables & Security (`.env`)

Configuration is managed via `.env`.

### 1. The Template File (`.env.example`)
```ini
# Delta Exchange Credentials
DELTA_API_KEY=your_delta_api_key_here
DELTA_API_SECRET=your_delta_api_secret_here
DELTA_BASE_URL=https://cdn-ind.testnet.deltaex.org

# Position Sizing & Two-Stage Allocation
TARGET_LOTS=1000
MIN_TRADEABLE_LOTS=100
FULL_TARGET_WAIT_SECONDS=90
MIN_FALLBACK_LOTS=500
LOT_SIZE=1000
DEFAULT_LEVERAGE=40

# Entry Timing & Liquidity Parameters
WARMUP_START_HOUR=9
WARMUP_START_MINUTE=58
EXECUTION_HOUR=10
EXECUTION_MINUTE=0
WARMUP_POLL_INTERVAL_SECONDS=5
MAX_SPREAD_RATIO=0.080
ENTRY_WINDOW_SECONDS=120
ENTRY_RETRY_INTERVAL_SECONDS=5

# Combo A Stop-Loss & Risk Management
SL_MULTIPLIER=2.00
COST_TRAIL_MULTIPLIER=1.00
HARD_KILL_SWITCH_USD=1185.00

# Telegram Alerts & Dual-Broadcast
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
TELEGRAM_CHANNEL_ID=your_telegram_channel_id_here # Optional (e.g. -100xxxxxxxxxx)

# Static Proxy Credentials
PROXY_HOST=198.51.100.42
PROXY_PORT=8080
PROXY_USER=proxy_user_demo
PROXY_PASS=proxy_pass_sample
```

### 2. Creating your Local `.env`
```bash
cp .env.example .env
```
Open `.env` in your editor and paste your credentials. `.gitignore` protects `.env` from being committed.

---

## 6. Step 5: Local Laptop Verification & Test Suite

### Running Unit Tests (46 Tests)
The repository includes a comprehensive 46-test test suite verifying all execution flows, anti-trap filters, two-stage sizing, error routing, and alert templates:

```bash
python -m pytest -v
```
*Expected Output:*
```text
============================= 46 passed in 0.35s ==============================
```

### Test 1: Authentication & Balance
Verifies static proxy tunnel and Delta API key authentication:
```bash
python tests/test_auth.py
```

### Test 2: Telegram Alerts
Verifies delivery to private admin chat and public channel:
```bash
python tests/test_telegram.py
```

### Test 3: End-to-End Live Execution Pipeline
Runs a complete simulated trade cycle (Select 10-Delta -> Sell 1 lot -> Attach 100% SL -> 120s hold -> Auto square-off):
```bash
python tests/test_live_execution.py
```

---

## 7. Step 6: Complete Mobile (Termux) Installation & Setup

Turn any Android phone into a 24/7 dedicated low-power trading server.

### Step 1: Install Termux via F-Droid
> ⚠️ **DO NOT install Termux from Google Play Store** (Play Store build is obsolete).
Download from **[F-Droid](https://f-droid.org/packages/com.termux/)** or **[GitHub Releases](https://github.com/termux/termux-app/releases)**.

### Step 2: Install Packages & Prevent Sleep
```bash
pkg update && pkg upgrade -y
pkg install git python cronie termux-api nano -y
termux-wake-lock
```

### Step 3: Clone Repository & Configure Environment
```bash
cd ~
git clone https://github.com/your-username/delta-alpha-strangle-bot.git
cd delta-alpha-strangle-bot
cp .env.example .env
nano .env
```

### Step 4: Verify Connectivity on Termux
```bash
python tests/test_auth.py
python tests/test_telegram.py
pytest -v
```

---

## 8. Step 7: Production Scheduling via Crontab (Cronie)

### Crontab Configuration
Configure Termux's built-in cron daemon (`cronie`):

```bash
crontab -e
```

Paste the production schedule:

```cron
# ====================================================================
# DELTA ALPHA STRANGLE AUTOMATION CRON (IST TIMEZONE)
# ====================================================================
# 09:58:00 AM IST - 2-Phase Pre-Warm & Target Lock (Sniper Execution at 10:00:00 AM IST)
58 9 * * * cd /data/data/com.termux/files/home/delta-alpha-strangle-bot && /data/data/com.termux/files/usr/bin/python3 main.py entry >> logs/entry.log 2>&1

# 10:00 - 17:00 IST - Cost-to-Cost Trail State Machine Monitor (Every 2 Mins)
*/2 10-17 * * * cd /data/data/com.termux/files/home/delta-alpha-strangle-bot && /data/data/com.termux/files/usr/bin/python3 main.py monitor >> logs/monitor.log 2>&1

# 05:15:00 PM IST - Guaranteed Exit, 3-Attempt Retry & Flat Audit
15 17 * * * cd /data/data/com.termux/files/home/delta-alpha-strangle-bot && /data/data/com.termux/files/usr/bin/python3 main.py exit >> logs/exit.log 2>&1
```

Start the daemon and ensure it auto-starts:
```bash
crond
echo "crond" >> ~/.bashrc
```

### Android Battery Optimization Bypass
1. Android **Settings** -> **Apps** -> **Termux** -> **Battery** -> Select **"Unrestricted"**.
2. Lock Termux in recent apps so memory cleaners do not kill the process.

### Live Log Monitoring
```bash
tail -f ~/delta-alpha-strangle-bot/logs/entry.log
tail -f ~/delta-alpha-strangle-bot/logs/monitor.log
```

---

## 9. Strategy & Operational Logic

For a deep mathematical and quantitative specification of the trading system, refer to:

👉 **[STRANGLE_STRATEGY.md](STRANGLE_STRATEGY.md)**

Key mechanics:
- **2-Phase Entry:** Pre-warm target lock at 09:58 IST, sniper retry execution over 120s at 10:00 IST.
- **Two-Stage Sizing:** Stage 1 (0–90s) full 1,000 lots patience; Stage 2 (90–120s) dynamic equal-leg fallback down to 500 lots.
- **4-Layer Anti-Trap Filter:** Spread cap $\le 8.0\%$, Top Bid depth $\times 0.20$, Mark-to-Bid discount $\le 2.0\%$, and 2.5s snapshot stability.
- **Atomic Single-Leg Rollback:** Immediate emergency market buy if Leg 2 fails execution.
- **Combo A 100% Bracket SL + Cost Trail:** 2.0x entry stop loss, trailed to 1.0x cost on the surviving leg when one leg stops out.
- **17:15 IST Guaranteed Square-off:** 3-attempt purge loop ensuring 100% flat position overnight.

---

## 10. Repository Directory Structure

```text
delta-alpha-strangle-bot/
├── .env.example              # Public configuration template with dummy placeholders
├── .gitignore                # Protects .env, state, cache, and logs from Git tracking
├── README.md                 # Complete operational manual (this file)
├── ROADMAP.md                # Strategic production scaling & milestone roadmap
├── STRANGLE_STRATEGY.md      # Quantitative strategy & risk engine specification
├── requirements.txt          # Intentionally empty (100% Python Standard Library)
├── ruff.toml                 # Code linter & formatter configuration
├── main.py                   # Master CLI entrypoint router
│
├── config/
│   ├── __init__.py
│   └── settings.py           # Standard library .env loader, proxy setup & constants
│
├── core/
│   ├── __init__.py
│   └── api_client.py         # Native urllib client with HMAC-SHA256 & isolated proxy
│
├── data/
│   ├── state.json            # Dynamic runtime state recording active trades and stops
│   └── trade_ledger.csv      # Persistent trade ledger tracking session PnL & drawdowns
│
├── jobs/
│   ├── __init__.py
│   ├── 1_entry_job.py        # 2-Phase 09:58 Pre-Warm & 10:00 Two-Stage Sniper Entry
│   ├── 2_exit_job.py         # 17:15 PM IST Auto Square-off & Flat Verification job
│   └── 3_monitor_job.py      # Combo A Cost-to-Cost Trail state monitor daemon
│
├── logs/
│   └── .gitkeep              # Log output directory (entry.log, monitor.log, exit.log)
│
├── services/
│   ├── __init__.py
│   ├── delta_calculator.py   # Greeks parser, 10-Delta selection, 4 Anti-Trap layers
│   ├── order_manager.py      # Dual-verification orders, atomic rollback, bracket SLs
│   ├── risk_guard.py         # Non-blocking drawdown calculation & advisory alert
│   └── telegram_notifier.py  # Dual-broadcast Telegram client with 4 templates + telemetry
│
└── tests/
    ├── __init__.py
    ├── test_combo_a_anti_trap.py         # Anti-Trap 4-layer validation & sizing tests
    ├── test_execution_flow.py            # 2-Phase entry, two-stage patience, fallback tests
    ├── test_proxy_and_monitor_guard.py   # Proxy isolation & monitor job state tests
    ├── test_risk_guard_and_crash_alert.py# Drawdown warning & crash alert tests
    ├── test_telegram_templates.py        # Telegram formatting & routing tests
    ├── test_auth.py                      # Validates proxy tunnel and Delta wallet balance
    ├── test_telegram.py                  # Validates Telegram Bot connectivity
    └── test_live_execution.py            # Full simulated pipeline test
```

---

## 11. Risk Disclaimer & Safety Rules

> **⚠️ FINANCIAL DISCLAIMER:** Options selling involves substantial risk of loss. While this software incorporates an automated $+100\%$ Stop-Market Bracket Shield, Atomic Single-Leg Rollback, and mandatory 17:15 IST square-offs, exchange outages or extreme volatility spikes can result in financial loss.
>
> 1. Always validate your setup on **Delta Exchange Testnet** before deploying live capital.
> 2. Ensure adequate margin cushion (40x Cross Margin / Portfolio Margin recommended).
> 3. Never commit or expose your real `.env` file or API secrets.

---

**Crafted with algorithmic discipline. Zero bloat. Pure Python Standard Library.**

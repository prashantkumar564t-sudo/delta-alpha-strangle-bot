# ⚡ Delta Alpha Strangle Trading Bot

[![Dependencies](https://img.shields.io/badge/Dependencies-Standard%20Library%20Only-success?style=for-the-badge&logo=python&logoColor=white)](requirements.txt)
[![Target Exchange](https://img.shields.io/badge/Exchange-Delta%20Exchange%20India%20%2F%20Global-orange?style=for-the-badge)](https://india.delta.exchange)
[![Platform](https://img.shields.io/badge/Platform-Termux%20Android%20%7C%20Linux%20VPS-blue?style=for-the-badge&logo=android&logoColor=white)](https://termux.dev)
[![Python Version](https://img.shields.io/badge/Python-3.8%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Security](https://img.shields.io/badge/Auth-HMAC--SHA256%20%26%20Static%20Tunnel-red?style=for-the-badge)](core/api_client.py)
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
- [6. Step 5: Local Laptop Verification & Tests](#6-step-5-local-laptop-verification--tests)
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

---

## 1. Project Overview & Architecture

**Delta Alpha Strangle Bot** is an autonomous quantitative trading system designed to monetize intraday **Theta (Time Decay)** on daily Bitcoin (BTC) options traded on Delta Exchange India (`cdn-ind.testnet.deltaex.org` / `api.india.delta.exchange`). 

Every morning at **10:00 AM IST**, the bot scans the live option chain for contracts expiring at **17:30 IST**, identifies Out-Of-The-Money (OTM) Call (CE) and Put (PE) strikes with a Greek Delta $\approx 0.10$ ($\sim 90\%$ statistical probability of expiring worthless), and sells 1 lot of each. It immediately locks in a **75% Pure Stop-Market Bracket Stop-Loss** based on the real executed entry price. At **17:15 IST** (15 minutes before exchange settlement), it automatically closes all remaining positions, leaving the account **100% FLAT** overnight.

```
                           DELTA ALPHA BOT ARCHITECTURE
                    
        ┌────────────────────────────────────────────────────────┐
        │            Python 3 Standard Library Engine            │
        │     (urllib.request + hmac + hashlib + json + time)    │
        └───────────────────────────┬────────────────────────────┘
                                    │
                       HTTP / HTTPS Proxy Tunnel
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
- `urllib.request` / `urllib.error`: Native HTTP/HTTPS network client with proxy authentication.
- `hmac` & `hashlib`: Official Delta Exchange cryptographic HMAC-SHA256 signature generator.
- `json`: Wire payload serialization matching signature bytes.
- `time` & `datetime`: Unix epoch timestamps and IST (`UTC+5:30`) daily expiry calculations.
- `os` & `sys`: Custom `.env` line parser supporting UTF-8 and Windows UTF-8 BOM encoding.

`requirements.txt` is intentionally **empty** — clone the repo and run it immediately!

### High-Reliability Engineering Highlights
1. **Static Datacenter Proxy Tunneling:** Routes all outgoing API traffic through a dedicated IP address (`urllib.request.ProxyHandler`), solving Delta's strict `ip_not_whitelisted_for_api_key` restrictions.
2. **Atomic Single-Leg Rollback:** If the Call (CE) sell fills but the Put (PE) sell gets rejected (due to margin, tick size, or network drop), the engine immediately triggers an emergency Market Buy order to close the naked CE leg, eliminating unhedged overnight exposure.
3. **Dual-Settlement 10s Verifications:** Incorporates two deliberate 10-second countdown waits to allow exchange matching engines to settle fills before querying `/v2/positions` and `/v2/orders`.
4. **3-Attempt Square-off Retry Engine:** The 17:15 IST exit job does not execute once and assume closure. It executes up to 3 purge-and-close cycles with 4-second backoffs, verifies positions count == 0, and dispatches a Critical Emergency Alarm to Telegram if any position remains open.

---

## 2. Step 1: Obtaining Delta Exchange Testnet Credentials

Before risking real capital, test everything on the official Delta Exchange Testnet.

1. Navigate to the **Delta Exchange Testnet Portal**:
   - India Testnet: [https://cdn-ind.testnet.deltaex.org](https://cdn-ind.testnet.deltaex.org)
   - Global Testnet: [https://testnet.deltaex.org](https://testnet.deltaex.org)
2. Log in (or register a demo account). Your demo account comes preloaded with virtual USDT/USD balances.
3. Navigate to **API Keys**:
   - Click on your **Profile Icon** (top right) -> **Settings** -> **API Management / API Keys**.
   - Click **Create New API Key**.
4. Configure Permissions:
   - **Key Name:** `AlphaStrangleBot`
   - **Permissions:** Select **Trading / Orders** ONLY.
   - ⚠️ **CRITICAL SECURITY RULE:** **NEVER enable the "Withdrawal" permission** on any trading bot API key.
   - **IP Whitelist Field:** Leave blank for a moment (we will paste our static proxy IP from Step 2 here).
5. Click **Generate API Key**.
6. Immediately copy both the **API Key** and **API Secret** to a secure temporary notepad (Delta will only display the secret once).

---

## 3. Step 2: Webshare Static Proxy Setup (Bypassing Dynamic IP)

### Why a Static Proxy is Mandatory
When running on mobile internet (Jio, Airtel, Vodafone) or home broadband, your Internet Service Provider uses **Carrier-Grade NAT (CGNAT)**. Your outbound public IP changes every few minutes or whenever your mobile radio reconnects.

Delta Exchange enforces strict API security: if an API Key has IP Whitelisting enabled, an IP change immediately produces this fatal error:
```json
[HTTP 401] {"error":{"code":"ip_not_whitelisted_for_api_key","context":{"client_ip":"..."}},"success":false}
```
If you leave the API key without an IP whitelist, Delta enforces severe rate limits and security flags. By routing the bot through a permanent static datacenter proxy, your outbound IP **never changes**, regardless of whether your phone switches between 4G, 5G, or Wi-Fi.

### ISP DNS Block Workaround (Jio / Airtel in India)
In India, major ISPs occasionally block the domain `webshare.io` at the DNS level. If the site fails to load:
1. On Android: Go to **Settings** -> **Network & Internet** -> **Private DNS**.
2. Select **Private DNS provider hostname** and enter:
   ```text
   one.one.one.one
   ```
   *(or enter `dns.google`)*
3. On Windows / Mac: Change your network adapter's DNS server to Cloudflare (`1.1.1.1`) or Google (`8.8.8.8`).
4. Refresh your browser; [webshare.io](https://www.webshare.io) will open instantly.

### Obtaining Proxy Credentials
1. Sign up for a free account at [https://www.webshare.io](https://www.webshare.io) (the free tier provides 10 free permanent proxies).
2. Inside the Webshare dashboard, navigate to **Proxy** -> **Proxy List**.
3. Under the list view, extract the 4 connection parameters:
   - **Proxy IP (Host):** e.g., `198.51.100.42` *(dummy example)*
   - **Port:** e.g., `8080` *(dummy example)*
   - **Username:** e.g., `proxy_user_demo` *(dummy example)*
   - **Password:** e.g., `proxy_pass_sample` *(dummy example)*

### Whitelisting Proxy IP in Delta Exchange
1. Return to your open **Delta Exchange API Keys** settings page.
2. In the **IP Whitelist** input box, paste the exact **Proxy IP** you obtained from Webshare (e.g., `198.51.100.42`).
3. Save the API Key. Now Delta will **ONLY** accept requests originating from this static IP address.

---

## 4. Step 3: Telegram Bot & Telemetry Setup

The bot sends real-time Markdown trade telemetry directly to your phone via Telegram.

1. **Create the Telegram Bot:**
   - Open Telegram and search for [@BotFather](https://t.me/BotFather).
   - Send the message `/newbot`.
   - Provide a display name (e.g., `My Delta Strangle Bot`) and a unique username ending in `bot` (e.g., `my_delta_strangle_alerts_bot`).
   - BotFather will reply with your **HTTP API Token**:
     ```text
     1234567890:ABCdefGhIJKlmNoPQRstuVWXyz
     ```
   - Copy this token; this is your `TELEGRAM_BOT_TOKEN`.
2. **Retrieve your Chat ID:**
   - In Telegram, search for [@userinfobot](https://t.me/userinfobot) and tap `/start`.
   - It will reply with your personal numeric **Id** (e.g., `987654321`).
   - Copy this number; this is your `TELEGRAM_CHAT_ID`.
3. **Activate your Bot:**
   - Search for your newly created bot username in Telegram and tap **Start** (or send `/start`).
   - *Note: Bots cannot initiate messages to users until the user has sent at least one message.*

---

## 5. Step 4: Environment Variables & Security (`.env`)

In the project root, configuration is handled via `.env`.

### 1. The Template File (`.env.example`)
This file is tracked by Git and contains dummy placeholders for public reference:

```ini
# Delta Exchange Credentials
DELTA_API_KEY=your_delta_api_key_here
DELTA_API_SECRET=your_delta_api_secret_here
DELTA_BASE_URL=https://cdn-ind.testnet.deltaex.org

# Position Sizing
LOT_SIZE=1

# Telegram Alerts
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here

# Static Proxy Credentials (Example Placeholders)
PROXY_HOST=198.51.100.42
PROXY_PORT=8080
PROXY_USER=proxy_user_demo
PROXY_PASS=proxy_pass_sample
```

### 2. Creating your Local `.env`
Create your personal `.env` by copying the template:

```bash
# On Linux / Termux / macOS:
cp .env.example .env

# On Windows PowerShell:
Copy-Item .env.example .env
```

Open `.env` in a text editor (`nano .env` or Notepad) and paste your real credentials.

### 3. Repository Leak Protection
The included `.gitignore` strictly blocks `.env`, runtime state, and logs from being committed:
```gitignore
.env
.env.*
!.env.example
data/state.json
logs/
*.log
__pycache__/
```
Verify with `git status` that `.env` never shows up as an untracked or staged file.

---

## 6. Step 5: Local Laptop Verification & Tests

Before moving to mobile Termux, run the three standalone test utilities on your computer.

### Test 1: Authentication & Balance
Verifies that your static proxy tunnel functions and Delta recognizes your IP whitelist:
```bash
python tests/test_auth.py
```
*Expected Output:*
```text
[*] Proxy Enabled: 198.51.100.42:8080
Connecting to: https://cdn-ind.testnet.deltaex.org/v2/wallet/balances

[SUCCESS] Demo Account Authenticated!
Response: True
 - Asset: USD | Balance: 199.829993
```

### Test 2: Telegram Alerts
Verifies that your Telegram Bot token and Chat ID are communicating properly:
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
*(Check your Telegram app for the test notification).*

### Test 3: End-to-End Live Execution Pipeline
Runs a complete simulated trade cycle: selects 10-Delta strikes -> sells 1 lot CE & PE -> attaches 75% Bracket SL -> holds for 120 seconds -> executes auto square-off:
```bash
python tests/test_live_execution.py
```
*Expected Output:*
```text
[STEP 1] Selected CE: C-BTC-75400-121126 | Selected PE: P-BTC-72000-121126
[STEP 2] CE SOLD (Order ID: ...) | PE SOLD (Order ID: ...)
         Real Fills: CE = 44.0 USD, PE = 101.3 USD
         Attached 75% Bracket SLs: CE @ 77.0 USD, PE @ 177.3 USD (Verified Active ✅)
[STEP 3] Holding positions... 120 seconds countdown.
[STEP 4] Initiating square-off: Orders cancelled, positions bought back.
         Verification: 0 Open Orders, 0 Open Positions remaining (100% FLAT ✅)
```

---

## 7. Step 6: Complete Mobile (Termux) Installation & Setup

Turn any spare or primary Android phone into a 24/7 dedicated low-power trading server.

### Step 1: Install Termux via F-Droid
> ⚠️ **DO NOT install Termux from Google Play Store** (the Play Store build is obsolete and fails to fetch package repositories).
- Download and install the latest APK from **[F-Droid](https://f-droid.org/packages/com.termux/)** or **[Termux GitHub Releases](https://github.com/termux/termux-app/releases)**.

### Step 2: Install Packages & Prevent Sleep
Open Termux and run the following commands sequentially:

```bash
# Update package repositories
pkg update && pkg upgrade -y

# Install Git, Python, Cronie, and Termux API
pkg install git python cronie termux-api nano -y

# Prevent Android CPU sleep while running in background
termux-wake-lock
```
*(A persistent Android notification will appear confirming Termux wake-lock is active).*

### Step 3: Clone Repository & Configure Environment
```bash
# Navigate to home directory
cd ~

# Clone the repository
git clone https://github.com/your-username/delta-alpha-strangle-bot.git
cd delta-alpha-strangle-bot

# Setup .env
cp .env.example .env
nano .env
```
In `nano`, use the volume keys/touch controls to paste your real credentials. Press `Ctrl + O` and `Enter` to save, then `Ctrl + X` to exit.

### Step 4: Verify Connectivity on Termux
```bash
python tests/test_auth.py
python tests/test_telegram.py
```
If both tests print `[SUCCESS]`, your mobile terminal is ready for autonomous production scheduling.

---

## 8. Step 7: Production Scheduling via Crontab (Cronie)

### Crontab Configuration
To run fully autonomously without manual intervention, configure Termux's built-in cron daemon (`cronie`).

1. Open crontab editor:
   ```bash
   crontab -e
   ```
2. Paste the following schedule:

```cron
# ====================================================================
# DELTA ALPHA STRANGLE AUTOMATION CRON (IST TIMEZONE)
# ====================================================================
# 10:00:00 AM IST - Morning Entry Job with 75% Bracket SL
00 10 * * * cd /data/data/com.termux/files/home/delta-alpha-strangle-bot && python jobs/1_entry_job.py >> logs/trading.log 2>&1

# 05:15:00 PM IST - Guaranteed Exit, 3-Attempt Retry & Flat Audit
15 17 * * * cd /data/data/com.termux/files/home/delta-alpha-strangle-bot && python jobs/2_exit_job.py >> logs/trading.log 2>&1
```

3. Save and exit (`Ctrl + O`, `Enter`, `Ctrl + X`).
4. Start the cron daemon:
   ```bash
   crond
   ```
5. Ensure `crond` auto-starts whenever Termux launches:
   ```bash
   echo "crond" >> ~/.bashrc
   ```

### Android Battery Optimization Bypass
Android OS aggressive battery managers terminate background apps unless explicitly exempted:
1. Open Android **Settings** -> **Apps** -> **Termux**.
2. Tap **Battery** -> Select **"Unrestricted"** (Disable battery optimization).
3. If your phone has an app lock / task manager, lock Termux in memory so it is not cleared when tapping "Clear All Apps".

### Live Log Monitoring
To inspect live trade execution on your phone:
```bash
tail -f ~/delta-alpha-strangle-bot/logs/trading.log
```

---

## 9. Strategy & Operational Logic

For a deep mathematical, quantitative, and operational breakdown of the trading system, refer to the companion specification document:

👉 **[STRANGLE_STRATEGY.md](STRANGLE_STRATEGY.md)**

Key strategy mechanics include:
- **Daily Theta Collapse:** Selling options 7.5 hours prior to the 17:30 IST daily settlement.
- **Liquidity & Spread Sanity Filters:** Filtering out dead bids (`best_bid <= 0`), sub-\$5 premiums (`mark_price < 5.0`), and wide spreads (`spread / mark_price > 0.40`).
- **Atomic Rollback Engine:** Automatic emergency market buy of Leg 1 if Leg 2 fails execution.
- **75% Bracket Stop-Loss:** Automatic market stop placement directly linked to exchange positions.
- **3-Attempt Square-off Loop:** Triple-pass square-off loop guaranteeing 100% flat portfolios at 17:15 IST.

---

## 10. Repository Directory Structure

```text
delta-alpha-strangle-bot/
├── .env.example              # Public configuration template with dummy placeholders
├── .gitignore                # Protects .env, state, cache, and logs from Git tracking
├── README.md                 # Complete operational manual (this file)
├── STRANGLE_STRATEGY.md      # Quantitative strategy & risk engine specification
├── requirements.txt          # Intentionally empty (100% Python Standard Library)
├── main.py                   # Master entrypoint stub
│
├── config/
│   ├── __init__.py
│   └── settings.py           # Standard library .env loader & static proxy tunnel setup
│
├── core/
│   ├── __init__.py
│   └── api_client.py         # Native urllib client with HMAC-SHA256 signature generator
│
├── data/
│   └── state.json            # Dynamic runtime state recording active trades and stops
│
├── jobs/
│   ├── __init__.py
│   ├── 1_entry_job.py        # 10:00 AM IST Entry & 75% Bracket SL job
│   └── 2_exit_job.py         # 17:15 PM IST Auto Square-off & Flat Verification job
│
├── logs/
│   └── .gitkeep              # Log output directory (trading.log)
│
├── services/
│   ├── __init__.py
│   ├── delta_calculator.py   # Greeks parser, 10-Delta selection, and liquidity filters
│   ├── notifier.py           # Pure urllib Telegram messaging client
│   └── order_manager.py      # Dual-verification orders, atomic rollback, and retry engine
│
└── tests/
    ├── __init__.py
    ├── test_auth.py          # Validates proxy tunnel and Delta wallet balance
    ├── test_telegram.py      # Validates Telegram Bot connectivity
    └── test_live_execution.py# Full pipeline test (Entry -> SL -> 120s hold -> Square-off)
```

---

## 11. Risk Disclaimer & Safety Rules

> **⚠️ FINANCIAL DISCLAIMER:** Options selling involves substantial risk of loss and is not suitable for every investor. While this software incorporates an automated $+75\%$ Stop-Market Bracket Shield, Atomic Single-Leg Rollback, and mandatory 17:15 IST square-offs, unexpected exchange outages, high network latency, or market black-swan spikes can result in financial loss.
>
> 1. Always validate your setup on **Delta Exchange Testnet** before deploying live capital.
> 2. Ensure your account maintains adequate margin cushion to avoid liquidation during intraday volatility.
> 3. Never commit or expose your real `.env` file or API secrets.
> 4. The authors and contributors assume no liability for financial outcomes resulting from the use of this software.

---

**Crafted with algorithmic discipline. Zero bloat. Pure Python Standard Library.**

import json

import numpy as np
import pandas as pd

CSV_PATH = "C:/Users/ASUS/projects/00_RESEARCH_REPORTS/algotest_backtests/2026-11-23_ComboA_10Delta_100SL/BTC_10Delta_Strangle_1000to1715_100SL_CostTrail_Trades.csv"
CONFIG_PATH = "C:/Users/ASUS/projects/00_RESEARCH_REPORTS/algotest_backtests/2026-11-23_ComboA_10Delta_100SL/btcdelta-10alphastrangle.algtst"

# 1. Load data
df = pd.read_csv(CSV_PATH)
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

df["Index_str"] = df["Index"].astype(str)
parent = df[df["Index_str"].str.endswith(".0")].copy()
legs = df[~df["Index_str"].str.endswith(".0")].copy()

# Add session ID
legs["Session_Id"] = legs["Index_str"].apply(lambda x: int(float(x.split(".")[0])))
legs["Entry-Date"] = pd.to_datetime(legs["Entry-Date"])
legs["Entry-Weekday"] = legs["Entry-Date"].dt.day_name()

# 2. Friction Model: Delta Exchange India 4.13%
# Round-trip fee = (Entry_Price + ExitPrice) * 0.0413 (per 1 BTC notional)
legs["Entry_Prem"] = legs["Entry-Price"]
legs["Exit_Prem"] = legs["ExitPrice"]
legs["Gross_PnL_per_BTC"] = legs["Entry_Prem"] - legs["Exit_Prem"]
legs["Fee_per_BTC"] = (legs["Entry_Prem"] + legs["Exit_Prem"]) * 0.0413
legs["Net_PnL_per_BTC"] = legs["Gross_PnL_per_BTC"] - legs["Fee_per_BTC"]

# 3. Aggregate by Session
session_agg = (
    legs.groupby(["Session_Id", "Entry-Date", "Entry-Weekday"])
    .agg(
        n_legs=("Index_str", "count"),
        gross_pnl=("Gross_PnL_per_BTC", "sum"),
        total_fee=("Fee_per_BTC", "sum"),
        net_pnl=("Net_PnL_per_BTC", "sum"),
        entry_prices=("Entry_Prem", list),
        exit_prices=("Exit_Prem", list),
        remarks=("Remarks", list),
        kinds=("Instrument-Kind", list),
    )
    .reset_index()
    .sort_values("Entry-Date")
)

session_agg["cum_net_pnl"] = session_agg["net_pnl"].cumsum()
session_agg["running_peak"] = session_agg["cum_net_pnl"].cummax()
session_agg["drawdown"] = session_agg["cum_net_pnl"] - session_agg["running_peak"]


# 4. Combo A Behavior Breakdown
def classify_session(row):
    rem = row["remarks"]
    p_in = row["entry_prices"]
    p_out = row["exit_prices"]
    n = row["n_legs"]

    if n == 1:
        return "Single_Leg"

    sl_count = sum(1 for r in rem if "Stop Loss Hit" in str(r))

    if sl_count == 0:
        return "Both_Expired_OTM"
    elif sl_count == 1:
        return "1_SL_Hit_Runner_Survived"
    elif sl_count == 2:
        # Check if one was Cost Trail (exit == entry)
        cost_trail = False
        for pin, pout in zip(p_in, p_out):
            if abs(pin - pout) < 0.05 or pout == pin:
                cost_trail = True
                break
        if cost_trail:
            return "1_SL_Hit_2nd_Trailed_Cost"
        else:
            return "Both_SL_Hit"
    return "Other"


session_agg["combo_a_category"] = session_agg.apply(classify_session, axis=1)

print("=== COMBO A BEHAVIOR BREAKDOWN ===")
cat_counts = session_agg["combo_a_category"].value_counts()
for cat, cnt in cat_counts.items():
    pnl = session_agg[session_agg["combo_a_category"] == cat]["net_pnl"].sum()
    print(f"{cat}: {cnt} sessions ({cnt / len(session_agg) * 100:.1f}%) | Total Net PnL (1 BTC): ${pnl:,.2f}")

# 5. Core Performance Metrics
total_sessions = len(session_agg)
win_sessions = (session_agg["net_pnl"] > 0).sum()
loss_sessions = (session_agg["net_pnl"] < 0).sum()
scratch_sessions = (session_agg["net_pnl"] == 0).sum()
win_rate = win_sessions / total_sessions * 100

total_gross = session_agg["gross_pnl"].sum()
total_fee = session_agg["total_fee"].sum()
total_net = session_agg["net_pnl"].sum()
fee_drag = (total_fee / session_agg[session_agg["gross_pnl"] > 0]["gross_pnl"].sum()) * 100

gross_wins = session_agg[session_agg["gross_pnl"] > 0]["gross_pnl"].sum()
gross_losses = abs(session_agg[session_agg["gross_pnl"] < 0]["gross_pnl"].sum())
gross_pf = gross_wins / gross_losses if gross_losses > 0 else 999.0

net_wins = session_agg[session_agg["net_pnl"] > 0]["net_pnl"].sum()
net_losses = abs(session_agg[session_agg["net_pnl"] < 0]["net_pnl"].sum())
net_pf = net_wins / net_losses if net_losses > 0 else 999.0

expectancy = session_agg["net_pnl"].mean()
mdd_dollars = session_agg["drawdown"].min()

# Daily Sharpe & Sortino (annualized with sqrt(365))
daily_returns = session_agg["net_pnl"]
mean_daily = daily_returns.mean()
std_daily = daily_returns.std()
downside_std = daily_returns[daily_returns < 0].std()

ann_sharpe = (mean_daily / std_daily) * np.sqrt(365) if std_daily > 0 else 0
ann_sortino = (mean_daily / downside_std) * np.sqrt(365) if downside_std > 0 else 0

# Streaks
loss_flags = (session_agg["net_pnl"] < 0).astype(int)
win_flags = (session_agg["net_pnl"] > 0).astype(int)


def calc_max_streak(flags):
    max_s = 0
    cur_s = 0
    for f in flags:
        if f == 1:
            cur_s += 1
            max_s = max(max_s, cur_s)
        else:
            cur_s = 0
    return max_s


max_win_streak = calc_max_streak(win_flags)
max_loss_streak = calc_max_streak(loss_flags)

print("\n=== CORE PERFORMANCE METRICS (PER 1.0 BTC NOTIONAL) ===")
print(f"Total Sessions: {total_sessions}")
print(f"Total Option Legs: {len(legs)}")
print(f"Win Rate: {win_rate:.2f}% ({win_sessions} wins / {loss_sessions} losses / {scratch_sessions} scratch)")
print(f"Gross PnL: ${total_gross:,.2f}")
print(f"Total Fees (4.13%): ${total_fee:,.2f}")
print(f"Fee Drag: {fee_drag:.2f}%")
print(f"Net PnL: ${total_net:,.2f} (₹{total_net * 85:,.2f} INR @ ₹85/USD)")
print(f"Gross Profit Factor: {gross_pf:.2f}")
print(f"Net Profit Factor: {net_pf:.2f}")
print(f"Net Expectancy per Session: ${expectancy:.2f}")
print(f"Annualized Sharpe: {ann_sharpe:.2f}")
print(f"Annualized Sortino: {ann_sortino:.2f}")
print(f"Historical Max Drawdown: ${mdd_dollars:,.2f}")
print(f"Return / MDD: {abs(total_net / mdd_dollars):.2f}x")
print(f"Max Consecutive Win Streak: {max_win_streak} sessions")
print(f"Max Consecutive Loss Streak: {max_loss_streak} sessions")

# 6. 70/30 Chronological Walk-Forward Audit
split_idx = int(len(session_agg) * 0.70)
is_df = session_agg.iloc[:split_idx].copy()
oos_df = session_agg.iloc[split_idx:].copy()


def get_stats(df_sub):
    tot = len(df_sub)
    wins = (df_sub["net_pnl"] > 0).sum()
    wr = wins / tot * 100
    net = df_sub["net_pnl"].sum()
    gross = df_sub["gross_pnl"].sum()
    fee = df_sub["total_fee"].sum()
    nw = df_sub[df_sub["net_pnl"] > 0]["net_pnl"].sum()
    nl = abs(df_sub[df_sub["net_pnl"] < 0]["net_pnl"].sum())
    npf = nw / nl if nl > 0 else 999.0
    exp = df_sub["net_pnl"].mean()
    m_d = df_sub["net_pnl"].mean()
    s_d = df_sub["net_pnl"].std()
    d_d = df_sub[df_sub["net_pnl"] < 0]["net_pnl"].std()
    sh = (m_d / s_d) * np.sqrt(365) if s_d > 0 else 0
    so = (m_d / d_d) * np.sqrt(365) if d_d > 0 else 0
    cum = df_sub["net_pnl"].cumsum()
    dd = (cum - cum.cummax()).min()
    return {
        "days": tot,
        "date_range": f"{df_sub['Entry-Date'].min().strftime('%Y-%m-%d')} to {df_sub['Entry-Date'].max().strftime('%Y-%m-%d')}",
        "win_rate": wr,
        "gross": gross,
        "fee": fee,
        "net": net,
        "npf": npf,
        "exp": exp,
        "sharpe": sh,
        "sortino": so,
        "mdd": dd,
    }


is_stats = get_stats(is_df)
oos_stats = get_stats(oos_df)
retention = oos_stats["sharpe"] / is_stats["sharpe"] if is_stats["sharpe"] > 0 else 0

print("\n=== 70/30 WALK-FORWARD AUDIT ===")
print(f"In-Sample (70%): {is_stats['date_range']} ({is_stats['days']} days)")
print(
    f"  Net PnL: ${is_stats['net']:,.2f} | PF: {is_stats['npf']:.2f} | WR: {is_stats['win_rate']:.1f}% | Sharpe: {is_stats['sharpe']:.2f} | MDD: ${is_stats['mdd']:,.2f}"
)
print(f"Out-of-Sample (30%): {oos_stats['date_range']} ({oos_stats['days']} days)")
print(
    f"  Net PnL: ${oos_stats['net']:,.2f} | PF: {oos_stats['npf']:.2f} | WR: {oos_stats['win_rate']:.1f}% | Sharpe: {oos_stats['sharpe']:.2f} | MDD: ${oos_stats['mdd']:,.2f}"
)
print(f"Sharpe Retention Ratio: {retention:.2%} (Threshold >= 65%)")

# 7. Weekday Breakdown (Monday-Sunday)
print("\n=== WEEKDAY STABILITY MATRIX ===")
days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
weekday_summary = []
for d in days_order:
    sub_all = session_agg[session_agg["Entry-Weekday"] == d]
    sub_is = is_df[is_df["Entry-Weekday"] == d]
    sub_oos = oos_df[oos_df["Entry-Weekday"] == d]

    is_npf = (
        sub_is[sub_is["net_pnl"] > 0]["net_pnl"].sum() / abs(sub_is[sub_is["net_pnl"] < 0]["net_pnl"].sum())
        if (sub_is["net_pnl"] < 0).any()
        else 999.0
    )
    oos_npf = (
        sub_oos[sub_oos["net_pnl"] > 0]["net_pnl"].sum() / abs(sub_oos[sub_oos["net_pnl"] < 0]["net_pnl"].sum())
        if (sub_oos["net_pnl"] < 0).any()
        else 999.0
    )
    all_npf = (
        sub_all[sub_all["net_pnl"] > 0]["net_pnl"].sum() / abs(sub_all[sub_all["net_pnl"] < 0]["net_pnl"].sum())
        if (sub_all["net_pnl"] < 0).any()
        else 999.0
    )

    row_data = {
        "Day": d,
        "IS_Days": len(sub_is),
        "IS_Net": sub_is["net_pnl"].sum(),
        "IS_WR": (sub_is["net_pnl"] > 0).mean() * 100,
        "IS_NPF": is_npf,
        "OOS_Days": len(sub_oos),
        "OOS_Net": sub_oos["net_pnl"].sum(),
        "OOS_WR": (sub_oos["net_pnl"] > 0).mean() * 100,
        "OOS_NPF": oos_npf,
        "All_Days": len(sub_all),
        "All_Net": sub_all["net_pnl"].sum(),
        "All_WR": (sub_all["net_pnl"] > 0).mean() * 100,
        "All_NPF": all_npf,
        "Gate": "PASS" if (sub_is["net_pnl"].sum() > 0 and sub_oos["net_pnl"].sum() > 0) else "FAIL",
    }
    weekday_summary.append(row_data)
    print(
        f"{d:9}: IS ${row_data['IS_Net']:>8.2f} (PF {row_data['IS_NPF']:.2f}) | OOS ${row_data['OOS_Net']:>8.2f} (PF {row_data['OOS_NPF']:.2f}) | Total ${row_data['All_Net']:>9.2f} (WR {row_data['All_WR']:.1f}%) | Gate: {row_data['Gate']}"
    )

# 8. Monte Carlo Simulation (10,000 runs)
np.random.seed(42)
returns_arr = session_agg["net_pnl"].values
n_days = len(returns_arr)
mc_dds = []
mc_streaks = []

for _ in range(10000):
    shuffled = np.random.choice(returns_arr, size=n_days, replace=True)
    eq = np.cumsum(shuffled)
    pk = np.maximum.accumulate(eq)
    dd = eq - pk
    mc_dds.append(np.min(dd))

    losses = (shuffled < 0).astype(int)
    cur_s = 0
    max_s = 0
    for l in losses:
        if l == 1:
            cur_s += 1
            max_s = max(max_s, cur_s)
        else:
            cur_s = 0
    mc_streaks.append(max_s)

mc_res = {
    "hist_mdd": float(mdd_dollars),
    "median_mdd": float(np.percentile(mc_dds, 50)),
    "p95_mdd": float(np.percentile(mc_dds, 5)),  # 5th percentile of negative values
    "p99_mdd": float(np.percentile(mc_dds, 1)),
    "worst_sim_mdd": float(np.min(mc_dds)),
    "p99_losing_streak": int(np.percentile(mc_streaks, 99)),
    "worst_losing_streak": int(np.max(mc_streaks)),
}

print("\n=== 10,000-RUN MONTE CARLO STRESS TEST ===")
print(f"Historical MDD: ${mc_res['hist_mdd']:,.2f}")
print(f"Median MDD (50th percentile): ${mc_res['median_mdd']:,.2f}")
print(f"P95 MDD (95% confidence): ${mc_res['p95_mdd']:,.2f}")
print(f"P99 MDD (99% confidence): ${mc_res['p99_mdd']:,.2f}")
print(f"Worst Simulated MDD: ${mc_res['worst_sim_mdd']:,.2f}")
print(f"P99 Max Losing Streak: {mc_res['p99_losing_streak']} days")
print(f"Worst Simulated Losing Streak: {mc_res['worst_losing_streak']} days")

# 9. Worst 5 Days
print("\n=== WORST 5 SINGLE-DAY DRAWDOWNS ===")
worst_5 = session_agg.sort_values("net_pnl").head(5)
for _, r in worst_5.iterrows():
    print(
        f"Date: {r['Entry-Date'].strftime('%Y-%m-%d')} ({r['Entry-Weekday']}) | Net PnL: ${r['net_pnl']:,.2f} | Category: {r['combo_a_category']} | Entry Prems: {r['entry_prices']} | Exit Prems: {r['exit_prices']}"
    )

# 10. Monthly Performance
session_agg["YearMonth"] = session_agg["Entry-Date"].dt.to_period("M")
monthly = (
    session_agg.groupby("YearMonth")
    .agg(
        days=("net_pnl", "count"),
        wins=("net_pnl", lambda x: (x > 0).sum()),
        net_pnl=("net_pnl", "sum"),
        gross_pnl=("gross_pnl", "sum"),
        fees=("total_fee", "sum"),
    )
    .reset_index()
)
monthly["win_rate"] = monthly["wins"] / monthly["days"] * 100
print("\n=== MONTHLY BREAKDOWN ===")
for _, m in monthly.iterrows():
    print(
        f"{m['YearMonth']}: Days {m['days']:2d} | Net PnL: ${m['net_pnl']:>8.2f} | WR: {m['win_rate']:>5.1f}% | Fees: ${m['fees']:>6.2f}"
    )

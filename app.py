import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import io

# ── 頁面設定 ──────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Monthly Meta-Audit Pipeline",
    layout="wide",
    page_icon="📈",
    initial_sidebar_state="expanded",
)

# ── TradingView 風格 CSS ──────────────────────────────────────────────────────
st.markdown("""
<style>
/* 全域深色背景 */
[data-testid="stAppViewContainer"] { background-color: #131722; color: #d1d4dc; }
[data-testid="stSidebar"]          { background-color: #1e222d; }
[data-testid="stHeader"]           { background-color: #131722; }

/* 指標卡片風格 */
[data-testid="stMetric"] {
    background: #1e222d;
    border: 1px solid #2a2e39;
    border-radius: 6px;
    padding: 12px 16px;
}
[data-testid="stMetric"] label { color: #787b86 !important; font-size: 12px !important; }
[data-testid="stMetricValue"]  { color: #d1d4dc !important; font-size: 22px !important; font-weight: 600; }
[data-testid="stMetricDelta"]  { font-size: 12px !important; }

/* 分隔線 */
hr { border-color: #2a2e39; }

/* 子標題 */
h2, h3 { color: #d1d4dc !important; }

/* 下載按鈕 */
.stDownloadButton button {
    background: #2962ff !important;
    color: white !important;
    border: none !important;
    border-radius: 4px !important;
}
</style>
""", unsafe_allow_html=True)

# ── TradingView 暗色圖表 Layout 模板 ─────────────────────────────────────────
TV_LAYOUT = dict(
    paper_bgcolor="#131722",
    plot_bgcolor="#131722",
    font=dict(color="#787b86", family="Inter, Trebuchet MS, sans-serif", size=11),
    xaxis=dict(
        gridcolor="#2a2e39", zerolinecolor="#2a2e39",
        showgrid=True, rangeslider_visible=False,
        type="date", tickformat="%b %Y",
    ),
    yaxis=dict(gridcolor="#2a2e39", zerolinecolor="#363a45", showgrid=True),
    legend=dict(
        bgcolor="rgba(30,34,45,0.9)",
        bordercolor="#2a2e39", borderwidth=1,
        font=dict(color="#d1d4dc"),
    ),
    hovermode="x unified",
    hoverlabel=dict(bgcolor="#1e222d", bordercolor="#2a2e39", font_color="#d1d4dc"),
    margin=dict(l=60, r=20, t=40, b=40),
)

# ── 側邊欄 ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📈 Meta-Audit Pipeline")
    st.markdown("### ⚙️ 基礎時間區間")
    is_start_date = st.date_input("In-Sample 起始日", value=pd.to_datetime("2020-01-01"))
    is_end_date   = st.date_input("In-Sample 截止日", value=pd.to_datetime("2023-12-31"))
    st.markdown("---")
    st.markdown("### 📊 CUSUM 基準設定")
    baseline_mode = st.radio(
        "CUSUM 基準獲取方式", 
        ["從 IS 區間自動計算", "手動輸入機構基準 (R倍數)"],
        index=0
    )

    if baseline_mode == "手動輸入機構基準 (R倍數)":
        manual_mu = st.number_input("基準期望值 μ0 (R)", value=0.25, step=0.01, format="%.3f")
        manual_sigma = st.number_input("基準標準差 σ (R)", value=1.20, step=0.01, format="%.3f")
    else:
        manual_mu = None
        manual_sigma = None

    h_multiplier  = st.number_input("控制界限 H (× σ)", value=4.0, step=0.5, min_value=1.0, max_value=10.0)

    st.markdown("---")
    st.markdown("### ⚙️ 風險單位 (R) 換算設定")
    is_fixed_risk = st.number_input("IS 回測固定風險 (USD)", value=5000.0, step=500.0)
    oos_dyn_risk_pct = st.number_input("OOS 實盤動態風險 (%)", value=0.2, step=0.1)
    manual_capital = st.number_input("手動指定起始資金 (0 為自動偵測)", value=0.0, step=10000.0)
    st.markdown("---")
    uploaded_file = st.file_uploader(
        "📂 上傳 TradingView 報表", type=["xlsx", "csv", "xls"],
        help="請上傳包含 'List of trades' 工作表的 Excel 或 CSV 檔案",
    )

# ── 標題 ─────────────────────────────────────────────────────────────────────
st.markdown("## 📈 策略量化稽核系統 (Monthly Meta-Audit Pipeline)")
st.markdown("##### CUSUM 向下漂移結構斷裂偵測 · TradingView 風格視覺化")

if uploaded_file is None:
    st.info("💡 請從左側面板上傳 TradingView 匯出的交易清單 (Excel / CSV) 以開始分析。")
    st.stop()

# ── 讀取 & 清洗 ───────────────────────────────────────────────────────────────
with st.spinner("載入與解析資料中..."):
    try:
        if uploaded_file.name.endswith(".csv"):
            df_raw = pd.read_csv(uploaded_file)
        else:
            xl = pd.ExcelFile(uploaded_file)
            sheet_name = "List of trades" if "List of trades" in xl.sheet_names else xl.sheet_names[0]
            df_raw = xl.parse(sheet_name)
    except Exception as e:
        st.error(f"讀取檔案失敗：{e}")
        st.stop()

# ── 尋找初始資金與欄位 ───────────────────────────────────────────────────
initial_capital = 500000.0
if xl:
    for sname in xl.sheet_names:
        test_df = xl.parse(sname)
        mask = test_df.map(lambda x: any(kw in str(x) for kw in ["初始", "Initial"])).any(axis=1)
        if mask.any():
            row_vals = test_df[mask].values.flatten()
            for rv in row_vals:
                try:
                    val = float(rv.replace(",", "").replace("$", ""))
                    if val > 1000:
                        initial_capital = val
                        break
                except: continue
            break

col_date    = next((c for c in df_raw.columns if str(c).strip() in ["日期/時間", "Date and time", "Date & time"]), "日期/時間")
col_type    = next((c for c in df_raw.columns if str(c).strip() in ["類型", "Type"]), "類型")
col_pnl_usd = next((c for c in df_raw.columns if str(c).strip() in ["淨損益 USD", "Net P&L USD", "Net P&L"]), "淨損益 USD")
col_pnl_roi = next((c for c in df_raw.columns if str(c).strip() in ["淨損益 %", "Net P&L %"]), "淨損益 %")
col_mae     = next((c for c in df_raw.columns if str(c).strip() in ["逆勢回撤 %", "Adverse excursion %", "MAE %"]), "逆勢回撤 %")
col_symbol  = next((c for c in df_raw.columns if str(c).strip().lower() in ["商品", "symbol", "ticker", "商品代碼", "商品名稱", "instrument", "asset", "item", "market"]), None)

# 如果還是找不到品種，嘗試模糊搜尋
if col_symbol is None:
    for c in df_raw.columns:
        if any(k in str(c).lower() for k in ["sym", "tick", "商品", "instr", "asset"]):
            col_symbol = c
            break
if col_symbol is None: col_symbol = "Symbol" # 最終保底

# ── 針對特殊格式解析品種 (Symbol Extraction) ──
if (col_symbol not in df_raw.columns) and ("交易 #" in df_raw.columns):
    # 範例格式: THINKMARKETS:BTCUSD-1 -> 提取 BTCUSD
    def extract_symbol(val):
        s = str(val)
        if ":" in s and "-" in s:
            return s.split(":")[1].split("-")[0]
        elif "-" in s:
            return s.split("-")[0]
        return s
    df_raw["Symbol_Auto"] = df_raw["交易 #"].apply(extract_symbol)
    col_symbol = "Symbol_Auto"
elif (col_symbol not in df_raw.columns) and ("Trade #" in df_raw.columns):
    def extract_symbol(val):
        s = str(val)
        if ":" in s and "-" in s:
            return s.split(":")[1].split("-")[0]
        elif "-" in s:
            return s.split("-")[0]
        return s
    df_raw["Symbol_Auto"] = df_raw["Trade #"].apply(extract_symbol)
    col_symbol = "Symbol_Auto"

for c in [col_type, col_date]:
    if c not in df_raw.columns:
        st.error(f"找不到必要欄位「{c}」，請確認上傳正確的 List of trades 工作表。")
        st.stop()

df_raw[col_date] = pd.to_datetime(df_raw[col_date])

def to_float_pct(series):
    if series.dtype == "object":
        return pd.to_numeric(series.astype(str).str.replace("%", ""), errors="coerce").fillna(0)
    return series.fillna(0)

# 過濾平倉資料並排序
df_exits = df_raw[df_raw[col_type].str.contains("Exit", case=False, na=False)].copy()
df_exits = df_exits.sort_values(by=col_date).reset_index(drop=True)

if df_exits.empty:
    st.error("找不到任何 Exit 平倉紀錄。")
    st.stop()

# ── 重建基礎數據 (核心 R 倍數轉換引擎) ──────────────────────────────
if manual_capital > 0:
    initial_capital = manual_capital

is_end_ts = pd.to_datetime(is_end_date)
r_multiples = []
running_equity = float(initial_capital)

if col_pnl_usd in df_exits.columns:
    for _, row in df_exits.iterrows():
        trade_date = pd.to_datetime(row[col_date])
        pnl_usd = float(row[col_pnl_usd])
        
        if trade_date <= is_end_ts:
            # IS 區間：回測使用固定風險 (如 $5000)
            r = pnl_usd / is_fixed_risk
        else:
            # OOS 區間：實習使用動態複利風險
            # 1R = 當前淨值 * 風險百分比
            risk_unit = running_equity * (oos_dyn_risk_pct / 100.0)
            r = pnl_usd / risk_unit if risk_unit > 0 else 0
            
        r_multiples.append(r)
        running_equity += pnl_usd  # 始終使用真實 USD P&L 更新淨值

    df_exits["Trade_Account_PnL_Pct"] = r_multiples
else:
    # 降級處理：如果沒有 USD 欄位，退回原始百分比
    df_exits["Trade_Account_PnL_Pct"] = to_float_pct(df_exits[col_pnl_roi])

df_exits["Cum_PnL_Pct"] = df_exits["Trade_Account_PnL_Pct"].cumsum()

# 計算「相對峰值回撤」 (此處單位為 R)
df_exits["Account_Value"] = 0.0 + df_exits["Cum_PnL_Pct"]
df_exits["Peak_Value"]    = df_exits["Account_Value"].cummax()
df_exits["Drawdown_Pct"]  = df_exits["Account_Value"] - df_exits["Peak_Value"]

# ── CUSUM 計算 ────────────────────────────────────────────────────────────────
is_start_ts = pd.to_datetime(is_start_date)
is_end_ts   = pd.to_datetime(is_end_date)
is_mask     = (df_exits[col_date] >= is_start_ts) & (df_exits[col_date] <= is_end_ts)
is_data     = df_exits[is_mask]
oos_data    = df_exits[df_exits[col_date] > is_end_ts].copy().reset_index(drop=True)

if is_data.empty:
    st.error(f"在 {is_start_date} 到 {is_end_date} 之間找不到 In-Sample 資料。")
    st.stop()

if baseline_mode == "手動輸入機構基準 (R倍數)":
    mu = manual_mu
    sigma = manual_sigma
else:
    mu    = is_data["Trade_Account_PnL_Pct"].mean()
    sigma = is_data["Trade_Account_PnL_Pct"].std()

if pd.isna(sigma) or sigma == 0:
    st.error("標準差為 0，無法計算 CUSUM。")
    st.stop()

k = 0.5 * sigma
H = h_multiplier * sigma

s_minus_arr  = []
s_minus      = 0.0
break_detected   = False
break_date       = None
break_trade_info = None

for _, row in oos_data.iterrows():
    s_minus = max(0.0, s_minus - row["Trade_Account_PnL_Pct"] + mu - k)
    s_minus_arr.append(s_minus)
    if s_minus >= H and not break_detected:
        break_detected = True
        break_date = row[col_date]
        break_trade_info = row

oos_data["S_Minus"] = s_minus_arr

# ── 統計摘要 ──────────────────────────────────────────────────────────────────
total_trades     = len(df_exits)
profitable       = (df_exits["Trade_Account_PnL_Pct"] > 0).sum()
win_rate         = profitable / total_trades * 100 if total_trades else 0
total_pnl_pct    = df_exits["Cum_PnL_Pct"].iloc[-1] if not df_exits.empty else 0
max_dd           = df_exits["Drawdown_Pct"].min()
avg_win          = df_exits.loc[df_exits["Trade_Account_PnL_Pct"] > 0, "Trade_Account_PnL_Pct"].mean() if profitable else 0
avg_loss         = df_exits.loc[df_exits["Trade_Account_PnL_Pct"] <= 0, "Trade_Account_PnL_Pct"].mean() if (total_trades - profitable) else 0

total_pnl_usd    = df_exits[col_pnl_usd].sum() if col_pnl_usd in df_exits.columns else None

# ── 頂部 KPI 指標列 ───────────────────────────────────────────────────────────
st.markdown("---")
kpi_cols = st.columns(6)
kpi_data = [
    ("Total Perf (R)",    f"{total_pnl_pct:+.2f} R",      f"Cap: ${initial_capital:,.0f}"),
    ("Max Drawdown (R)", f"{max_dd:.2f} R",               None),
    ("Total Trades",     str(total_trades),               None),
    ("Profitable",       f"{profitable}/{total_trades}", f"{win_rate:.1f}%"),
    ("Avg Trade (R)",    f"{total_pnl_pct/total_trades:+.3f} R" if total_trades else "0 R", None),
    ("CUSUM Status",     "🔴 BREAK" if break_detected else "🟢 STABLE", None),
]
for col, (label, val, delta) in zip(kpi_cols, kpi_data):
    col.metric(label, val, delta)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 分頁
# ─────────────────────────────────────────────────────────────────────────────
tab_tv, tab_cusum, tab_data = st.tabs(["📊 TradingView 模擬圖表", "🔬 CUSUM 稽核監控", "📋 資料與報表下載"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — TradingView 風格圖表（模擬官方 Strategy Tester）
# ══════════════════════════════════════════════════════════════════════════════
with tab_tv:
    st.markdown("#### Equity Chart — 策略績效總覽")

    # ─── 子圖布局：上方 Equity，下方 Drawdown ───────────────────────────────
    fig_eq = make_subplots(
        rows=3, cols=1,
        row_heights=[0.50, 0.25, 0.25],
        shared_xaxes=True,
        vertical_spacing=0.03,
        subplot_titles=("Equity (累計 R 倍數)", "Drawdown / Run-up (R)", "逐筆損益 (R Multiples)"),
    )

    dates_all = df_exits[col_date]

    # ── IS / OOS 背景色帶 ──────────────────────────────────────────────────
    if not oos_data.empty:
        oos_start = oos_data[col_date].iloc[0]
        oos_end   = df_exits[col_date].iloc[-1]
        for row_i in [1, 2, 3]:
            fig_eq.add_vrect(
                x0=oos_start, x1=oos_end,
                fillcolor="rgba(41,98,255,0.05)",
                layer="below", line_width=0,
                row=row_i, col=1,
            )
        # IS 開始與結束垂直線
        for row_i in [1, 2, 3]:
            # IS Start
            fig_eq.add_shape(
                type="line", x0=is_start_ts, x1=is_start_ts,
                y0=0, y1=1, yref="paper",
                line=dict(color="#787b86", width=1, dash="dot"),
                row=row_i, col=1
            )
            # IS End
            fig_eq.add_shape(
                type="line", x0=is_end_ts, x1=is_end_ts,
                y0=0, y1=1, yref="paper",
                line=dict(color="#2962ff", width=1, dash="dot"),
                row=row_i, col=1
            )

    # ── Row1：Equity 曲線 ──────────────────────────────────────────────────
    equity_color = "#26a69a"  # TradingView 綠

    # IS 區段
    if not is_data.empty:
        fig_eq.add_trace(go.Scatter(
            x=is_data[col_date], y=is_data["Cum_PnL_Pct"],
            mode="lines", name="Equity (R) - IS",
            line=dict(color=equity_color, width=2),
            fill="tozeroy", fillcolor="rgba(38,166,154,0.15)",
            hovertemplate="%{x|%Y-%m-%d}<br>Cum P&L: %{y:.2f} R<extra>In-Sample</extra>",
        ), row=1, col=1)

    # OOS 區段（稍亮色以示區別）
    if not oos_data.empty:
        fig_eq.add_trace(go.Scatter(
            x=oos_data[col_date], y=oos_data["Cum_PnL_Pct"],
            mode="lines", name="Equity (R) - OOS",
            line=dict(color="#00e5ff", width=2.5),
            fill="tozeroy", fillcolor="rgba(0,229,255,0.08)",
            hovertemplate="%{x|%Y-%m-%d}<br>Cum P&L: %{y:.2f} R<extra>Out-of-Sample</extra>",
        ), row=1, col=1)

    # IS / OOS 標籤
    if not is_data.empty:
        fig_eq.add_annotation(
            x=is_data[col_date].iloc[0], y=is_data["Cum_PnL_Pct"].max() * 0.95,
            text="◀ In-Sample", showarrow=False, font=dict(color="#787b86", size=10),
            xanchor="left", row=1, col=1,
        )
    if not oos_data.empty:
        fig_eq.add_annotation(
            x=oos_data[col_date].iloc[0], y=oos_data["Cum_PnL_Pct"].max() * 0.95,
            text="Out-of-Sample ▶", showarrow=False, font=dict(color="#2962ff", size=10),
            xanchor="left", row=1, col=1,
        )

    # 最終值標籤
    if not df_exits.empty:
        final_val = df_exits["Cum_PnL_Pct"].iloc[-1]
        fig_eq.add_annotation(
            x=df_exits[col_date].iloc[-1], y=final_val,
            text=f" {final_val:+.2f}%",
            showarrow=False,
            font=dict(color="#00e5ff", size=12, family="monospace"),
            xanchor="left", bgcolor="rgba(30,34,45,0.85)",
            bordercolor="#00e5ff", borderwidth=1, borderpad=4,
            row=1, col=1,
        )

    # ── Row2：回撤面積圖（連續填充，深紅）────────────────────────────────
    fig_eq.add_trace(go.Scatter(
        x=dates_all, y=df_exits["Drawdown_Pct"],
        mode="lines",
        name="Drawdown",
        line=dict(color="#ef5350", width=1.2),
        fill="tozeroy",
        fillcolor="rgba(239,83,80,0.35)",
        hovertemplate="%{x|%Y-%m-%d}<br>DD: %{y:.2f}%<extra>Drawdown</extra>",
    ), row=2, col=1)

    # 最大回撤標記
    max_dd_idx = df_exits["Drawdown_Pct"].idxmin()
    fig_eq.add_annotation(
        x=df_exits[col_date].iloc[max_dd_idx],
        y=df_exits["Drawdown_Pct"].iloc[max_dd_idx],
        text=f"Max DD {max_dd:.2f}%",
        showarrow=True, arrowhead=2, arrowcolor="#ef5350",
        font=dict(color="#ef5350", size=10),
        bgcolor="rgba(30,34,45,0.85)", bordercolor="#ef5350", borderwidth=1, borderpad=3,
        ax=30, ay=-20, row=2, col=1,
    )

    # ── Row3：逐筆損益 Bar ──────────────────────────────────────────────────
    bar_colors = [
        "#26a69a" if v >= 0 else "#ef5350" for v in df_exits["Trade_Account_PnL_Pct"]
    ]
    fig_eq.add_trace(go.Bar(
        x=dates_all, y=df_exits["Trade_Account_PnL_Pct"],
        name="Net P&L per trade",
        marker_color=bar_colors,
        hovertemplate="%{x|%Y-%m-%d}<br>P&L: %{y:.3f} R<extra></extra>",
    ), row=3, col=1)

    # 零線
    fig_eq.add_hline(y=0, line_color="#363a45", line_width=1, row=3, col=1)

    # ── MAE / MFE 散點（逐筆貿易回撤／延伸）──────────────────────────────
    if col_mae in df_exits.columns:
        fig_eq.add_trace(go.Bar(
            x=dates_all, y=-df_exits[col_mae].abs(),
            name="MAE (Adverse)",
            marker_color="rgba(239,83,80,0.35)",
            hovertemplate="%{x|%Y-%m-%d}<br>MAE: %{y:.3f} R<extra></extra>",
        ), row=3, col=1)

    # ── 全域 Layout ────────────────────────────────────────────────────────
    layout_eq = dict(**TV_LAYOUT)
    layout_eq.update(
        height=780,
        showlegend=True,
        legend=dict(**TV_LAYOUT["legend"], orientation="h", y=-0.05),
        title=dict(
            text=f"<b>{uploaded_file.name.replace('.xlsx','').replace('.csv','')}</b>",
            font=dict(color="#d1d4dc", size=13),
        ),
    )
    layout_eq["xaxis3"] = dict(gridcolor="#2a2e39", tickformat="%Y-%m", rangeslider_visible=False)
    layout_eq["yaxis2"] = dict(gridcolor="#2a2e39", zerolinecolor="#363a45")
    layout_eq["yaxis3"] = dict(gridcolor="#2a2e39", zerolinecolor="#363a45")
    fig_eq.update_layout(**layout_eq)
    st.plotly_chart(fig_eq, use_container_width=True)

    # ─── Profit Structure（模擬 TradingView Performance 區塊）──────────────
    st.markdown("---")
    st.markdown("#### Performance — 利潤結構 & 交易分佈")
    pc1, pc2 = st.columns([1, 1])

    with pc1:
        # 利潤結構 Bar Chart
        total_profit = df_exits.loc[df_exits["Trade_Account_PnL_Pct"] > 0, "Trade_Account_PnL_Pct"].sum()
        total_loss   = df_exits.loc[df_exits["Trade_Account_PnL_Pct"] <= 0, "Trade_Account_PnL_Pct"].sum()
        avg_trade    = df_exits["Trade_Account_PnL_Pct"].mean()

        fig_ps = go.Figure()
        fig_ps.add_trace(go.Bar(
            x=["Total Profit", "Total Loss", "Avg Trade"],
            y=[total_profit, total_loss, avg_trade],
            marker_color=["#26a69a", "#ef5350",
                          "#26a69a" if avg_trade >= 0 else "#ef5350"],
            text=[f"{total_profit:.2f}%", f"{total_loss:.2f}%", f"{avg_trade:.3f}%"],
            textposition="outside",
            textfont=dict(color="#d1d4dc"),
        ))
        ps_layout = {**TV_LAYOUT, "height": 300, "showlegend": False,
                     "title": dict(text="Profit Structure", font=dict(color="#d1d4dc")),
                     "yaxis": dict(gridcolor="#2a2e39", showticklabels=False),
                     "xaxis": dict(gridcolor="rgba(0,0,0,0)")}
        fig_ps.update_layout(**ps_layout)
        st.plotly_chart(fig_ps, use_container_width=True)

    with pc2:
        # 月度績效熱力圖
        df_exits["Year"]  = df_exits[col_date].dt.year
        df_exits["Month"] = df_exits[col_date].dt.month
        monthly = df_exits.groupby(["Year", "Month"])["Trade_Account_PnL_Pct"].sum().reset_index()
        pivot   = monthly.pivot(index="Year", columns="Month", values="Trade_Account_PnL_Pct").fillna(0)
        month_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

        fig_heat = go.Figure(go.Heatmap(
            z=pivot.values,
            x=[month_labels[m-1] for m in pivot.columns],
            y=[str(y) for y in pivot.index],
            colorscale=[[0,"#ef5350"],[0.5,"#131722"],[1,"#26a69a"]],
            zmid=0,
            text=[[f"{v:.1f}%" for v in row] for row in pivot.values],
            texttemplate="%{text}",
            textfont=dict(size=9, color="#d1d4dc"),
            hovertemplate="%{y} %{x}: %{z:.2f}%<extra></extra>",
            showscale=True,
            colorbar=dict(tickfont=dict(color="#787b86"), outlinecolor="#2a2e39"),
        ))
        heat_layout = {**TV_LAYOUT, "height": 300,
                      "title": dict(text="月度損益熱力圖 (Monthly P&L %)", font=dict(color="#d1d4dc")),
                      "xaxis": dict(side="top", gridcolor="rgba(0,0,0,0)"),
                      "yaxis": dict(gridcolor="rgba(0,0,0,0)")}
        fig_heat.update_layout(**heat_layout)
        st.plotly_chart(fig_heat, use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — CUSUM 稽核監控
# ══════════════════════════════════════════════════════════════════════════════
with tab_cusum:
    st.markdown("#### 📊 基準線摘要 (In-Sample Baseline)")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("IS 交易筆數", f"{len(is_data)} 筆")
    m2.metric("OOS 實盤筆數", f"{len(oos_data)} 筆")
    m3.metric("基準期望值 μ (R)", f"{mu:.3f} R")
    m4.metric("基準標準差 σ (R)", f"{sigma:.3f} R")
    m5.metric("控制界限 H (R)", f"{H:.3f} R ({h_multiplier}σ)")

    st.markdown("---")
    st.markdown("#### 審計裁定 (CUSUM Verdict)")
    if break_detected:
        st.error(f"""
**🔴 狀態：斷裂 (Structural Break Detected)**

累積向下漂移已穿越控制界限，Alpha 出現衰減跡象。

| **觸發品種** | **{break_trade_info[col_symbol] if col_symbol in break_trade_info else 'N/A'}** |
| 該筆交易損益 | **{break_trade_info['Trade_Account_PnL_Pct']:.3f} R** |
| 當前漂移量 S⁻ | **{s_minus_arr[-1]:.4f}** |
| 控制界限 H | **{H:.4f}** |

**>>> 系統指令：立即暫停實盤交易，啟動 Retuning 與 DSR 檢定流程。**
        """)
        
        # 診斷資訊：如果品種顯示 N/A，顯示可用欄位供使用者參考
        if col_symbol not in break_trade_info:
            with st.expander("🛠️ 診斷資訊：找不到品種欄位？"):
                st.write("目前系統偵測到的欄位如下：")
                st.code(list(df_raw.columns))
                st.write(f"當前試圖使用的品種欄位標籤為：`{col_symbol}`")
    else:
        max_drift = max(s_minus_arr) if s_minus_arr else 0
        safety_pct = max_drift / H * 100 if H else 0
        st.success(f"""
**🟢 狀態：正常 (Healthy)**

CUSUM 累積漂移未突破警戒線，策略結構保持穩定。

| 項目 | 數值 |
|---|---|
| 歷史最大漂移量 S⁻_max | **{max_drift:.4f}** |
| 安全界限 H | **{H:.4f}** |
| 使用率 | **{safety_pct:.1f}%** |

**>>> 系統指令：維持現狀，嚴禁修改任何策略參數 (DO NOT TOUCH PARAMETERS)。**
        """)

    st.markdown("---")
    if oos_data.empty:
        st.warning("OOS 區間無資料，無法繪製 CUSUM 監控圖。")
    else:
        # CUSUM 圖（2個子圖：上=OOS損益 Bar，下=S- 曲線）
        fig_cu = make_subplots(
            rows=2, cols=1, row_heights=[0.35, 0.65],
            shared_xaxes=True, vertical_spacing=0.04,
            subplot_titles=("OOS 逐筆損益 (vs 基準 μ)", "CUSUM 累積漂移 S⁻"),
        )

        # OOS P&L Bar（與基準比較）
        bar_c2 = ["#26a69a" if v >= mu else "#ef5350" for v in oos_data["Trade_Account_PnL_Pct"]]
        fig_cu.add_trace(go.Bar(
            x=oos_data[col_date], y=oos_data["Trade_Account_PnL_Pct"],
            name="OOS Net P&L", marker_color=bar_c2,
            hovertemplate="%{x|%Y-%m-%d %H:%M}<br>P&L: %{y:.3f} R<extra></extra>",
        ), row=1, col=1)
        fig_cu.add_hline(y=mu, line_color="#2962ff", line_dash="dot",
                         annotation_text=f"μ = {mu:.3f} R", row=1, col=1)

        # S- 主曲線
        fig_cu.add_trace(go.Scatter(
            x=oos_data[col_date], y=oos_data["S_Minus"],
            mode="lines", name="S⁻ (CUSUM)",
            line=dict(color="#ff9800", width=2.5),
            fill="tozeroy", fillcolor="rgba(255,152,0,0.12)",
            hovertemplate="%{x|%Y-%m-%d %H:%M}<br>S⁻: %{y:.4f}<extra></extra>",
        ), row=2, col=1)

        # H 警戒線
        fig_cu.add_hline(
            y=H, line_dash="dash", line_color="#ef5350", line_width=1.5,
            annotation_text=f"H = {h_multiplier}σ = {H:.3f}",
            annotation_font=dict(color="#ef5350"), row=2, col=1,
        )

        # 斷裂垂線
        if break_detected:
            for r in [1, 2]:
                fig_cu.add_vline(x=break_date, line_dash="solid",
                                 line_color="rgba(239,83,80,0.6)", line_width=1.5, row=r, col=1)
            fig_cu.add_annotation(
                x=break_date, y=H * 1.05,
                text=f"⚠ 斷裂 {break_date.strftime('%Y-%m-%d')}",
                showarrow=True, arrowhead=2, arrowcolor="#ef5350",
                font=dict(color="#ef5350", size=11),
                bgcolor="rgba(239,83,80,0.15)", bordercolor="#ef5350",
                row=2, col=1,
            )

        # k 容忍帶（淺灰區）
        fig_cu.add_hrect(y0=0, y1=k, fillcolor="rgba(120,123,134,0.07)",
                         layer="below", line_width=0, row=2, col=1)

        layout_cu = dict(**TV_LAYOUT)
        layout_cu.update(height=600, showlegend=True)
        layout_cu["yaxis2"] = dict(gridcolor="#2a2e39", zerolinecolor="#363a45")
        fig_cu.update_layout(**layout_cu)
        st.plotly_chart(fig_cu, use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — 資料檢視 & 下載
# ══════════════════════════════════════════════════════════════════════════════
with tab_data:
    st.markdown("#### 📋 完整交易清單 (Exit Only)")

    display_cols = [c for c in [col_date, col_symbol, col_type, "Trade_Account_PnL_Pct", "Cum_PnL_Pct", "Drawdown_Pct"] if c in df_exits.columns]
    if col_mae in df_exits.columns:
        display_cols.append(col_mae)

    # 顯示 dataframe，損益上色
    fmt_dict = {"Trade_Account_PnL_Pct": "{:.3f}%", "Cum_PnL_Pct": "{:.3f}%", "Drawdown_Pct": "{:.3f}%"}
    if col_mae in df_exits.columns:
        fmt_dict[col_mae] = "{:.3f}%"
    st.dataframe(
        df_exits[display_cols].style.format(fmt_dict).map(
            lambda v: "color: #26a69a" if isinstance(v, (int, float)) and v > 0 else "color: #ef5350" if isinstance(v, (int, float)) and v < 0 else "",
            subset=["Trade_Account_PnL_Pct"],
        ),
        use_container_width=True,
        height=400,
    )

    st.markdown("---")
    st.markdown("#### 📥 報表下載")

    dl1, dl2, dl3 = st.columns(3)

    # 下載 1：完整交易清單
    csv_all = df_exits[display_cols].to_csv(index=False).encode("utf-8-sig")
    dl1.download_button(
        label="📥 完整交易清單 (CSV)",
        data=csv_all,
        file_name="Full_Trades_Exit.csv",
        mime="text/csv",
    )

    # 下載 2：CUSUM OOS 報表
    if not oos_data.empty:
        cusum_cols = [c for c in [col_date, "Trade_Account_PnL_Pct", "S_Minus"] if c in oos_data.columns]
        csv_cusum = oos_data[cusum_cols].to_csv(index=False).encode("utf-8-sig")
        dl2.download_button(
            label="📥 CUSUM OOS 監控報告 (CSV)",
            data=csv_cusum,
            file_name="CUSUM_OOS_Report.csv",
            mime="text/csv",
        )

    # 下載 3：月度績效摘要
    monthly_summary = df_exits.groupby(["Year", "Month"]).agg(
        Trades=("Trade_Account_PnL_Pct", "count"),
        Net_PnL_Pct=("Trade_Account_PnL_Pct", "sum"),
        Win_Rate=("Trade_Account_PnL_Pct", lambda x: (x > 0).mean() * 100),
    ).reset_index()
    monthly_summary["Month"] = monthly_summary["Month"].apply(
        lambda m: ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][int(m)]
    )
    csv_monthly = monthly_summary.to_csv(index=False).encode("utf-8-sig")
    dl3.download_button(
        label="📥 月度績效摘要 (CSV)",
        data=csv_monthly,
        file_name="Monthly_Performance.csv",
        mime="text/csv",
    )

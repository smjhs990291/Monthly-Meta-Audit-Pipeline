import argparse
import pandas as pd
import numpy as np
import os
import sys

def run_monthly_cusum_audit(csv_path: str, is_end_date: str = '2023-12-31', h_multiplier: float = 4.0):
    """
    Monthly Meta-Audit Pipeline: CUSUM Drift Detection
    """
    if not os.path.exists(csv_path):
        print(f"Error: 找不到指定的 CSV 檔案: {csv_path}")
        sys.exit(1)

    print(f"[*] 載入交易日誌: {csv_path}")
    
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"Error: 無法讀取 CSV 檔案: {e}")
        sys.exit(1)
    
    # 1. 資料清洗
    col_type = '類型' if '類型' in df.columns else 'Type'
    col_date = '日期/時間' if '日期/時間' in df.columns else 'Date and time'
    col_pnl  = '淨損益 %' if '淨損益 %' in df.columns else 'Net P&L %'
    col_mae  = '回撤 %' if '回撤 %' in df.columns else 'Adverse excursion %'
    
    required_cols = [col_type, col_date, col_pnl]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        print(f"Error: CSV 缺少必要欄位: {missing_cols}")
        print(f"可用欄位有: {df.columns.tolist()}")
        sys.exit(1)

    # 只取平倉紀錄
    df = df[df[col_type].str.contains('Exit', case=False, na=False)].copy()
    if df.empty:
        print("Error: CSV 中找不到任何平倉 (Exit) 紀錄。")
        sys.exit(1)

    df[col_date] = pd.to_datetime(df[col_date])
    df[col_pnl] = pd.to_numeric(df[col_pnl].astype(str).str.replace('%', ''), errors='coerce').fillna(0)
    
    df = df.sort_values(by=col_date).reset_index(drop=True)
    
    # 2. 定義基準線 (In-Sample Baseline)
    is_mask = df[col_date] <= pd.to_datetime(is_end_date)
    is_data = df[is_mask]
    oos_data = df[~is_mask].copy()
    
    if is_data.empty:
        print(f"Error: 找不到 {is_end_date} 之前的樣本內資料 (In-Sample)，無法計算基準線。")
        sys.exit(1)

    if oos_data.empty:
        print(f"Warning: 找不到 {is_end_date} 之後的實盤資料 (Out-of-Sample)。")
    
    mu = is_data[col_pnl].mean()
    sigma = is_data[col_pnl].std()
    
    if sigma == 0:
        print("Error: 樣本內資料的標準差為 0，無法計算 CUSUM (所有損益可能皆相同)。")
        sys.exit(1)
        
    print(f"[*] 樣本內基準 (至 {is_end_date}): 平均損益(mu) = {mu:.3f}%, 標準差(sigma) = {sigma:.3f}%")
    
    # 3. CUSUM 參數
    k = 0.5 * sigma
    H = h_multiplier * sigma
    
    # 4. 執行 CUSUM 監控 (針對 OOS 實盤區間)
    s_minus = 0.0
    break_detected = False
    break_date = None
    
    for index, row in oos_data.iterrows():
        xt = row[col_pnl]
        # 向下漂移計算：如果賺得比預期少(或虧損)，且超出容忍度 k，則累積罰分
        s_minus = max(0, s_minus - xt + mu - k)
        
        if s_minus >= H:
            break_detected = True
            break_date = row[col_date]
            break
            
    # 5. 審計裁定輸出
    print("\n==================================================")
    print("               MONTHLY AUDIT REPORT               ")
    print("==================================================")
    if break_detected:
        print(f"🔴 [DANGER] 結構性斷裂確認！")
        print(f"   觸發日期: {break_date}")
        print(f"   當前漂移量: {s_minus:.3f} (控制界限: {H:.3f})")
        print("   >>> 系統指令: 立即暫停實盤交易，啟動重新調參 (Retuning) 與 DSR 檢驗。")
    else:
        print(f"🟢 [PASS] 策略結構健康。")
        print(f"   當前最大漂移量: {s_minus:.3f} (安全界限: < {H:.3f})")
        print("   >>> 系統指令: CUSUM 未突破警戒線。策略結構穩定。禁止修改任何參數。 (DO NOT TOUCH PARAMETERS)")
    print("==================================================\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monthly Meta-Audit Pipeline: CUSUM Drift Detection")
    parser.add_argument("csv_path", help="TradingView 匯出的交易清單 CSV 檔案路徑")
    parser.add_argument("--is_end_date", default="2023-12-31", help="In-Sample 基準線的結束日期 (預設 2023-12-31)")
    parser.add_argument("--h_multiplier", type=float, default=4.0, help="控制界限的 Sigma 倍數 (預設 4.0)")
    args = parser.parse_args()

    run_monthly_cusum_audit(args.csv_path, args.is_end_date, args.h_multiplier)

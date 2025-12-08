import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import datetime
import sys

# ==========================================
# 設定エリア: app.py の監視銘柄を移植
# ==========================================
TICKERS = [
    "7453.T", "7203.T", "8306.T", "9984.T", "7011.T", 
    "8136.T", "6752.T", "6501.T", "6758.T", "7267.T"
]

def analyze_ticker(ticker):
    """1銘柄ごとのデータを取得し、簡易レポートを作成する"""
    try:
        # 過去6ヶ月分のデータを取得
        df = yf.download(ticker, period="6mo", interval="1d", progress=False)
        
        if df.empty:
            return None

        # 指標計算 (app.pyに準拠)
        # RSI (14)
        df.ta.rsi(length=14, append=True)
        # SMA (5, 25)
        df.ta.sma(length=5, append=True)
        df.ta.sma(length=25, append=True)
        
        # 最新データ取得
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 値の抽出
        # ※yfinanceのバージョン差異を吸収するため float変換
        close = float(latest['Close'])
        rsi = float(latest['RSI_14'])
        sma5 = float(latest['SMA_5'])
        sma25 = float(latest['SMA_25'])
        
        prev_sma5 = float(prev['SMA_5'])
        prev_sma25 = float(prev['SMA_25'])
        
        # --- シグナル判定 ---
        signals = []
        
        # RSI判定
        if rsi < 30:
            signals.append("🔵 売られすぎ (RSI < 30)")
        elif rsi > 70:
            signals.append("🔴 買われすぎ (RSI > 70)")
            
        # ゴールデンクロス/デッドクロス
        if prev_sma5 < prev_sma25 and sma5 > sma25:
            signals.append("📈 ゴールデンクロス (買い)")
        elif prev_sma5 > prev_sma25 and sma5 < sma25:
            signals.append("📉 デッドクロス (売り)")
            
        # --- レポート生成 ---
        # 銘柄名と現在値
        report = f"【{ticker}】 {int(close):,}円\n"
        # テクニカル指標
        report += f"📊 RSI: {rsi:.1f} | SMA5: {sma5:.0f} / SMA25: {sma25:.0f}\n"
        
        # シグナルがあれば表示
        if signals:
            report += "⚡ " + " / ".join(signals) + "\n"
        
        report += "-" * 15
        return report

    except Exception as e:
        return f"【{ticker}】 エラー: {e}"

def main():
    # タイトル
    print(f"📉 株価定期分析レポート ({datetime.now().strftime('%m/%d %H:%M')})\n")
    
    reports = []
    for ticker in TICKERS:
        report = analyze_ticker(ticker)
        if report:
            reports.append(report)
            
    if reports:
        # 結果を結合して出力 -> これが notify.py に渡されます
        print("\n".join(reports))
    else:
        print("データが取得できませんでした。")

if __name__ == "__main__":
    main()
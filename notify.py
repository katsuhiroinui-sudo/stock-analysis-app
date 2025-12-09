import requests
import os
import sys
import argparse
import json
from datetime import datetime
import yfinance as yf
import pandas_ta as ta

"""
notify.py (統合版)
株価データの取得・分析を行い、その結果をLINE Messaging APIで通知します。
"""

# ==========================================
# 設定エリア
# ==========================================

# 監視銘柄リスト (app.pyと同じもの)
TICKERS = [
    "7453.T", "7203.T", "8306.T", "9984.T", "7011.T", 
    "8136.T", "6752.T", "6501.T", "6758.T", "7267.T"
]

# API設定 (GitHub Secretsから読み込み)
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN', '') 
MY_USER_ID = os.getenv('MY_USER_ID', '')

# ==========================================

def analyze_ticker(ticker):
    """1銘柄のデータを取得して分析レポートを作成"""
    try:
        # データ取得
        df = yf.download(ticker, period="3mo", interval="1d", progress=False)
        if df.empty:
            return None

        # テクニカル指標計算
        df.ta.rsi(length=14, append=True)
        df.ta.sma(length=5, append=True)
        df.ta.sma(length=25, append=True)
        
        # 最新データ
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 値の抽出
        close = float(latest['Close'])
        rsi = float(latest['RSI_14'])
        sma5 = float(latest['SMA_5'])
        sma25 = float(latest['SMA_25'])
        prev_sma5 = float(prev['SMA_5'])
        prev_sma25 = float(prev['SMA_25'])
        
        # シグナル判定
        signals = []
        if rsi < 30: signals.append("🔵 売られすぎ")
        if rsi > 70: signals.append("🔴 買われすぎ")
        if prev_sma5 < prev_sma25 and sma5 > sma25: signals.append("📈 GC(買い)")
        if prev_sma5 > prev_sma25 and sma5 < sma25: signals.append("📉 DC(売り)")
        
        # レポートテキスト作成
        report = f"【{ticker}】 {int(close):,}円\n"
        report += f"RSI:{rsi:.0f} | 5MA:{int(sma5)}/25MA:{int(sma25)}\n"
        if signals:
            report += "⚡ " + ",".join(signals) + "\n"
            
        return report

    except Exception as e:
        return f"【{ticker}】 エラー: {e}\n"

def send_line_push(message):
    """LINE Messaging APIで送信"""
    if not CHANNEL_ACCESS_TOKEN or not MY_USER_ID:
        print("[ERROR] LINE設定(Secrets)が読み込めません")
        return False

    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {CHANNEL_ACCESS_TOKEN}'
    }
    payload = {
        'to': MY_USER_ID,
        'messages': [{'type': 'text', 'text': message}]
    }

    try:
        res = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
        res.raise_for_status()
        print("[INFO] LINE通知成功")
        return True
    except Exception as e:
        print(f"[ERROR] LINE通知失敗: {e}")
        return False

def main():
    print(f"--- 分析開始: {datetime.now()} ---")
    
    reports = []
    for t in TICKERS:
        rep = analyze_ticker(t)
        if rep:
            reports.append(rep)
            
    if not reports:
        print("[WARN] データが取得できませんでした")
        return

    # 全文結合
    full_message = f"📉 株価分析レポート ({datetime.now().strftime('%m/%d')})\n\n"
    full_message += "\n".join(reports)
    
    print(full_message)
    
    # LINE送信
    send_line_push(full_message)

if __name__ == "__main__":
    main()
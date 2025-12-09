import requests
import os
import sys
import argparse
import json
from datetime import datetime
import yfinance as yf
import pandas as pd
import pandas_ta as ta

"""
notify.py (統合版・修正済み)
データのMultiIndex問題に対応し、株価分析結果を通知します。
"""

# ==========================================
# 設定エリア
# ==========================================

# 監視銘柄リスト
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

        # 【修正ポイント】MultiIndex（2段カラム）になっていたら1段にする
        # Close, Openなどのカラム名だけに整理します
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # テクニカル指標計算
        df.ta.rsi(length=14, append=True)
        df.ta.sma(length=5, append=True)
        df.ta.sma(length=25, append=True)
        
        # 最新データ
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 値の抽出
        # 値が存在しない場合のハンドリングを追加
        close = float(latest['Close']) if not pd.isna(latest['Close']) else 0
        rsi = float(latest['RSI_14']) if 'RSI_14' in latest and not pd.isna(latest['RSI_14']) else 50
        sma5 = float(latest['SMA_5']) if 'SMA_5' in latest and not pd.isna(latest['SMA_5']) else 0
        sma25 = float(latest['SMA_25']) if 'SMA_25' in latest and not pd.isna(latest['SMA_25']) else 0
        
        prev_sma5 = float(prev['SMA_5']) if 'SMA_5' in prev and not pd.isna(prev['SMA_5']) else 0
        prev_sma25 = float(prev['SMA_25']) if 'SMA_25' in prev and not pd.isna(prev['SMA_25']) else 0
        
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
        # エラー詳細を少し分かりやすく
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
        # エラーでも通知して気づけるようにする
        send_line_push("【エラー報告】株価データの取得に失敗しました。ログを確認してください。")
        return

    # 全文結合
    full_message = f"📉 株価分析レポート ({datetime.now().strftime('%m/%d')})\n\n"
    full_message += "\n".join(reports)
    
    print(full_message)
    
    # LINE送信
    send_line_push(full_message)

if __name__ == "__main__":
    main()

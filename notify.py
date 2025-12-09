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
notify.py (詳細分析版)
企業名表示、前日比、売買アクション判定機能を追加
"""

# ==========================================
# 設定エリア
# ==========================================

# 監視銘柄と企業名のマッピング
# 必要に応じて追加・変更してください
TICKER_MAP = {
    "7453.T": "良品計画",
    "7203.T": "トヨタ自動車",
    "8306.T": "三菱UFJ",
    "9984.T": "ソフトバンクG",
    "7011.T": "三菱重工",
    "8136.T": "サンリオ",
    "6752.T": "パナソニックHD",
    "6501.T": "日立製作所",
    "6758.T": "ソニーG",
    "7267.T": "ホンダ"
}

# API設定 (GitHub Secretsから読み込み)
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN', '') 
MY_USER_ID = os.getenv('MY_USER_ID', '')

# ==========================================

def analyze_ticker(ticker):
    """1銘柄のデータを取得して詳細レポートを作成"""
    try:
        # 企業名の取得（リストになければコードそのまま）
        company_name = TICKER_MAP.get(ticker, ticker)

        # データ取得
        df = yf.download(ticker, period="3mo", interval="1d", progress=False)
        
        if df.empty:
            return None

        # MultiIndex対応
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # テクニカル指標計算
        df.ta.rsi(length=14, append=True)
        df.ta.sma(length=5, append=True)
        df.ta.sma(length=25, append=True)
        
        # データ抽出
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        close = float(latest['Close'])
        prev_close = float(prev['Close'])
        
        # 指標（NaNケア付き）
        rsi = float(latest['RSI_14']) if not pd.isna(latest['RSI_14']) else 50.0
        sma5 = float(latest['SMA_5']) if not pd.isna(latest['SMA_5']) else 0.0
        sma25 = float(latest['SMA_25']) if not pd.isna(latest['SMA_25']) else 0.0
        
        prev_sma5 = float(prev['SMA_5']) if not pd.isna(prev['SMA_5']) else 0.0
        prev_sma25 = float(prev['SMA_25']) if not pd.isna(prev['SMA_25']) else 0.0
        
        # --- 1. 前日比計算 ---
        price_diff = close - prev_close
        price_change_pct = (price_diff / prev_close) * 100
        sign = "+" if price_diff > 0 else ""
        price_str = f"{int(close):,}円 ({sign}{price_change_pct:.1f}%)"

        # --- 2. アクション判定 ---
        action = "ステイ" # デフォルト
        reasons = []

        # RSI判定
        if rsi < 30:
            action = "買い (逆張り)"
            reasons.append("RSI売られすぎ")
        elif rsi > 70:
            action = "売り (過熱感)"
            reasons.append("RSI買われすぎ")
            
        # GC/DC判定 (トレンドフォロー優先)
        if prev_sma5 < prev_sma25 and sma5 > sma25:
            action = "買い"
            reasons.append("ゴールデンクロス")
        elif prev_sma5 > prev_sma25 and sma5 < sma25:
            action = "売り"
            reasons.append("デッドクロス")
            
        # --- 3. レポートテキスト生成 ---
        # 見やすさ重視で整形
        report = f"【{company_name}】 ({ticker})\n"
        report += f"株価: {price_str}\n"
        
        # アクションを目立たせる
        icon = "🤔"
        if "買い" in action: icon = "🚀"
        elif "売り" in action: icon = "🔻"
        
        report += f"判定: {icon} {action}\n"
        
        # テクニカル詳細（少し小さく表示されるイメージで）
        report += f"指標: RSI:{rsi:.0f} | 5MA:{int(sma5)}/25MA:{int(sma25)}\n"
        
        if reasons:
            report += f"根拠: {', '.join(reasons)}\n"
            
        report += "-" * 15 # 区切り線
            
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
    # 定義したマップのキー（銘柄コード）を使ってループ
    for ticker in TICKER_MAP.keys():
        rep = analyze_ticker(ticker)
        if rep:
            reports.append(rep)
            
    if not reports:
        print("[WARN] データが取得できませんでした")
        return

    # 全文結合
    # タイトル
    full_message = f"📊 株価AI分析レポート\n📅 {datetime.now().strftime('%Y/%m/%d')}\n\n"
    full_message += "\n".join(reports)
    
    # ログ出力（デバッグ用）
    print(full_message)
    
    # LINE送信
    send_line_push(full_message)

if __name__ == "__main__":
    main()

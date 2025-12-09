import requests
import os
import sys
import json
import time
from datetime import datetime
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import gspread
from google.oauth2.service_account import Credentials # 推奨ライブラリに変更

"""
notify.py (認証強化・自動補完版)
Google Sheets APIへの接続方式を最新化し、デバッグ情報を強化しました。
"""

# ==========================================
# 設定エリア
# ==========================================
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN', '') 
MY_USER_ID = os.getenv('MY_USER_ID', '')
SHEET_URL = os.getenv('SHEET_URL', '')
GCP_KEY_JSON = os.getenv('GCP_SERVICE_ACCOUNT_KEY', '')

# ==========================================

def get_tickers_from_sheet():
    """スプレッドシートから保有株と監視株のリストを取得"""
    try:
        if not GCP_KEY_JSON:
            print("[ERROR] GCP_SERVICE_ACCOUNT_KEY が設定されていません。")
            return {}, {}

        # JSONキーを読み込み
        key_dict = json.loads(GCP_KEY_JSON)
        
        # スコープ設定
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        
        # 認証 (google-auth使用)
        creds = Credentials.from_service_account_info(key_dict, scopes=scopes)
        client = gspread.authorize(creds)

        # 【デバッグ用】 どのメールアドレスでアクセスしているか表示
        print(f"[INFO] Connecting as: {creds.service_account_email}")

        # スプレッドシートを開く
        if not SHEET_URL:
            print("[ERROR] SHEET_URL が設定されていません。")
            return {}, {}
            
        sheet = client.open_by_url(SHEET_URL)
        
        holdings_ws = sheet.worksheet('Holdings')
        watchlist_ws = sheet.worksheet('Watchlist')
        
        # データ取得
        holdings_data = holdings_ws.get_all_records()
        watchlist_data = watchlist_ws.get_all_records()
        
        # 辞書化
        holdings = {str(r['Ticker']).strip(): r['Name'] for r in holdings_data if r['Ticker']}
        watchlist = {str(r['Ticker']).strip(): r['Name'] for r in watchlist_data if r['Ticker']}
        
        return holdings, watchlist

    except gspread.exceptions.APIError as e:
        print(f"[ERROR] Google Sheets APIエラー: {e}")
        print("hint: スプレッドシートの「共有」設定に、上記のメールアドレスが含まれているか確認してください。")
        return {}, {}
    except Exception as e:
        print(f"[ERROR] スプレッドシート読み込み失敗: {e}")
        return {}, {}

def analyze_ticker(ticker, name, mode="holding"):
    """
    mode="holding": シグナル関係なくレポート作成
    mode="watching": シグナルがある場合のみレポート作成
    """
    try:
        # コードの正規化 (.Tの自動付与)
        yf_ticker = str(ticker).strip()
        if yf_ticker.isdigit():
            yf_ticker = f"{yf_ticker}.T"

        # データ取得
        time.sleep(1) 
        df = yf.download(yf_ticker, period="3mo", interval="1d", progress=False)
        
        if df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # テクニカル計算
        df.ta.rsi(length=14, append=True)
        df.ta.sma(length=5, append=True)
        df.ta.sma(length=25, append=True)
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 値抽出 (NaNケア)
        close = float(latest['Close'])
        prev_close = float(prev['Close'])
        rsi = float(latest['RSI_14']) if not pd.isna(latest['RSI_14']) else 50
        sma5 = float(latest['SMA_5']) if not pd.isna(latest['SMA_5']) else 0
        sma25 = float(latest['SMA_25']) if not pd.isna(latest['SMA_25']) else 0
        
        prev_sma5 = float(prev['SMA_5'])
        prev_sma25 = float(prev['SMA_25'])
        
        # 前日比
        price_diff = close - prev_close
        price_change_pct = (price_diff / prev_close) * 100
        sign = "+" if price_diff > 0 else ""
        price_str = f"{int(close):,}円 ({sign}{price_change_pct:.1f}%)"

        # アクション判定
        action = "ステイ"
        reasons = []
        is_signal = False

        if rsi < 30:
            action = "買い (逆張り)"
            reasons.append(f"RSI売られすぎ({rsi:.0f})")
            is_signal = True
        elif rsi > 70:
            action = "売り (過熱感)"
            reasons.append(f"RSI買われすぎ({rsi:.0f})")
            is_signal = True
            
        if prev_sma5 < prev_sma25 and sma5 > sma25:
            action = "買い"
            reasons.append("GC")
            is_signal = True
        elif prev_sma5 > prev_sma25 and sma5 < sma25:
            action = "売り"
            reasons.append("DC")
            is_signal = True
            
        if abs(price_change_pct) >= 3.0:
            reasons.append(f"急変動({price_change_pct:.1f}%)")
            is_signal = True

        if mode == "watching" and not is_signal:
            return None

        # レポート生成
        icon = "👀" if mode == "holding" else "🔔"
        if "買い" in action: icon = "🚀"
        elif "売り" in action: icon = "🔻"
        
        report = f"{icon} 【{name}】 ({ticker})\n"
        report += f"株価: {price_str}\n"
        
        if is_signal or mode == "holding":
            report += f"判定: {action}\n"
            report += f"指標: RSI:{rsi:.0f} | 5MA:{int(sma5)}/25MA:{int(sma25)}\n"
            if reasons:
                report += f"根拠: {', '.join(reasons)}\n"
        
        report += "-" * 10
        return report

    except Exception as e:
        return f"【{name}】 エラー: {e}\n"

def send_line_push(message):
    if not CHANNEL_ACCESS_TOKEN or not MY_USER_ID:
        print("[ERROR] LINE設定不足")
        return False
    
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {CHANNEL_ACCESS_TOKEN}'}
    payload = {'to': MY_USER_ID, 'messages': [{'type': 'text', 'text': message}]}
    
    try:
        requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
        return True
    except:
        return False

def main():
    print(f"--- 分析開始: {datetime.now()} ---")
    
    holdings, watchlist = get_tickers_from_sheet()
    
    reports = []
    
    if holdings:
        reports.append("【 💰 保有株ポートフォリオ 】")
        for code, name in holdings.items():
            rep = analyze_ticker(code, name, mode="holding")
            if rep: reports.append(rep)
            
    watch_reports = []
    if watchlist:
        for code, name in watchlist.items():
            rep = analyze_ticker(code, name, mode="watching")
            if rep: watch_reports.append(rep)
            
    if watch_reports:
        reports.append("\n【 🔍 監視株シグナル速報 】")
        reports.extend(watch_reports)
    
    if not reports:
        print("通知対象なし (エラーまたはシグナルなし)")
        return

    full_message = f"📊 株価AIレポート ({datetime.now().strftime('%m/%d')})\n\n"
    full_message += "\n".join(reports)
    
    if len(full_message) > 2000:
        send_line_push(full_message[:2000] + "\n...(省略)...")
    else:
        send_line_push(full_message)
    
    print("通知完了")

if __name__ == "__main__":
    main()

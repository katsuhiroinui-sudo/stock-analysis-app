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
from oauth2client.service_account import ServiceAccountCredentials

# バックテスト用ライブラリ
try:
    from backtesting import Backtest, Strategy
    from backtesting.lib import crossover
except ImportError:
    print("[ERROR] backtestingライブラリが見つかりません。pip install backtesting を確認してください。")
    sys.exit(1)

"""
notify.py (AI戦略コンシェルジュ統合版)
仕様書に基づき、全戦略をバックテスト検証した上で、
その銘柄に最適な戦略に基づいて売買判断を行います。
"""

# ==========================================
# 設定エリア
# ==========================================
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN', '') 
MY_USER_ID = os.getenv('MY_USER_ID', '')
SHEET_URL = os.getenv('SHEET_URL', '')
GCP_KEY_JSON = os.getenv('GCP_SERVICE_ACCOUNT_KEY', '')

# ==========================================
# 1. AI分析用 戦略クラス定義 (app.pyより移植)
# ==========================================

class SmaCross(Strategy):
    n1 = 5
    n2 = 25
    def init(self):
        close = pd.Series(self.data.Close)
        self.sma1 = self.I(ta.sma, close, self.n1)
        self.sma2 = self.I(ta.sma, close, self.n2)
    def next(self):
        if crossover(self.sma1, self.sma2): self.buy()
        elif crossover(self.sma2, self.sma1): self.position.close()

class RsiOscillator(Strategy):
    upper = 70
    lower = 30
    def init(self):
        close = pd.Series(self.data.Close)
        self.rsi = self.I(ta.rsi, close, 14)
    def next(self):
        if crossover(self.rsi, self.lower): self.buy()
        elif crossover(self.upper, self.rsi): self.position.close()

class MacdTrend(Strategy):
    def init(self):
        close = pd.Series(self.data.Close)
        macd = ta.macd(close, fast=12, slow=26, signal=9)
        self.macd = self.I(lambda: macd.iloc[:, 0])
        self.signal = self.I(lambda: macd.iloc[:, 1])
    def next(self):
        if crossover(self.macd, self.signal): self.buy()
        elif crossover(self.signal, self.macd): self.position.close()

class BollingerBands(Strategy):
    def init(self):
        close = pd.Series(self.data.Close)
        bb = ta.bbands(close, length=20, std=2)
        self.lower = self.I(lambda: bb.iloc[:, 0])
        self.upper = self.I(lambda: bb.iloc[:, 2])
    def next(self):
        if self.data.Close < self.lower: 
            if not self.position.is_long: self.buy()
        elif self.data.Close > self.upper: 
            self.position.close()

STRATEGIES = [
    {"name": "SMAクロス", "class": SmaCross},
    {"name": "RSI逆張り", "class": RsiOscillator},
    {"name": "MACD", "class": MacdTrend},
    {"name": "ボリンジャー", "class": BollingerBands}
]

# ==========================================
# 2. 判定ロジック
# ==========================================

def get_tickers_from_sheet():
    """スプレッドシートから保有株と監視株のリストを取得"""
    try:
        key_dict = json.loads(GCP_KEY_JSON)
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
        client = gspread.authorize(creds)

        sheet = client.open_by_url(SHEET_URL)
        
        holdings_ws = sheet.worksheet('Holdings')
        watchlist_ws = sheet.worksheet('Watchlist')
        
        holdings = {str(r['Ticker']).strip(): r['Name'] for r in holdings_ws.get_all_records() if r['Ticker']}
        watchlist = {str(r['Ticker']).strip(): r['Name'] for r in watchlist_ws.get_all_records() if r['Ticker']}
        
        return holdings, watchlist
    except Exception as e:
        print(f"[ERROR] スプレッドシート読み込み失敗: {e}")
        return {}, {}

def check_current_signal(strategy_name, df):
    """
    選ばれた最適戦略に基づいて、最新の売買シグナルを判定する
    """
    try:
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        close = float(latest['Close'])
        
        # 安全な値取得ヘルパー
        def g(row, k, d=0): return float(row[k]) if k in row and not pd.isna(row[k]) else d

        sma5, sma25 = g(latest,'SMA_5'), g(latest,'SMA_25')
        p_sma5, p_sma25 = g(prev,'SMA_5'), g(prev,'SMA_25')
        rsi = g(latest,'RSI_14', 50)
        macd, sig = g(latest,'MACD_12_26_9'), g(latest,'MACDs_12_26_9')
        p_macd, p_sig = g(prev,'MACD_12_26_9'), g(prev,'MACDs_12_26_9')
        bbl, bbu = g(latest,'BBL_20_2.0'), g(latest,'BBU_20_2.0')

        action = "ステイ"
        reason = "シグナルなし"

        if strategy_name == "SMAクロス":
            if p_sma5 < p_sma25 and sma5 > sma25: 
                action, reason = "買い 🚀", "ゴールデンクロス"
            elif p_sma5 > p_sma25 and sma5 < sma25: 
                action, reason = "売り 🔻", "デッドクロス"
                
        elif strategy_name == "RSI逆張り":
            if rsi < 30: 
                action, reason = "買い 🚀", f"売られすぎ(RSI{rsi:.0f})"
            elif rsi > 70: 
                action, reason = "売り 🔻", f"買われすぎ(RSI{rsi:.0f})"
                
        elif strategy_name == "MACD":
            if p_macd < p_sig and macd > sig: 
                action, reason = "買い 🚀", "MACD上抜け"
            elif p_macd > p_sig and macd < sig: 
                action, reason = "売り 🔻", "MACD下抜け"
                
        elif strategy_name == "ボリンジャー":
            if close < bbl: 
                action, reason = "買い 🚀", "バンド下限割れ"
            elif close > bbu: 
                action, reason = "売り 🔻", "バンド上限到達"
            
        return action, reason, rsi, close
    except Exception as e:
        return "判定不能", f"エラー: {e}", 0, 0

def analyze_ticker(ticker, name, mode="holding"):
    """
    AI分析実行関数
    1. 過去2年のデータを取得
    2. 全戦略をバックテスト (総当たり)
    3. 勝率が最も高い「最適戦略」を選出
    4. その戦略に基づき、今日の売買判断を行う
    """
    try:
        yf_ticker = str(ticker).strip()
        if yf_ticker.isdigit():
            yf_ticker = f"{yf_ticker}.T"

        # バックテスト用に長めの期間を取得 (2年)
        time.sleep(1) 
        df = yf.download(yf_ticker, period="2y", interval="1d", progress=False)
        
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

        # 判定用テクニカル指標を一括計算 (check_current_signalで使用)
        df.ta.sma(length=5, append=True)
        df.ta.sma(length=25, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        df.ta.bbands(length=20, std=2, append=True)

        # --- AI総当たりバックテスト開始 ---
        best_strat = None
        best_win_rate = -1
        
        # 簡易化のため現金100万固定でテスト
        cash = 1000000
        
        for strat in STRATEGIES:
            try:
                # バックテスト実行
                bt = Backtest(df, strat["class"], cash=cash, commission=.002)
                stats = bt.run()
                win_rate = stats['Win Rate [%]']
                
                # 勝率でベスト戦略を更新 (NaNの場合は0扱い)
                if pd.isna(win_rate): win_rate = 0
                
                if win_rate > best_win_rate:
                    best_win_rate = win_rate
                    best_strat = strat["name"]
            except:
                continue
        
        if not best_strat:
            best_strat = "SMAクロス" # デフォルト

        # --- 今日のシグナル判定 ---
        action, reason, rsi_val, close_val = check_current_signal(best_strat, df)
        
        # 前日比計算
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        diff = latest['Close'] - prev['Close']
        pct = (diff / prev['Close']) * 100
        sign = "+" if diff > 0 else ""
        price_str = f"{int(close_val):,}円 ({sign}{pct:.1f}%)"

        is_signal = "🚀" in action or "🔻" in action

        # 監視モードでシグナルなしならスキップ
        if mode == "watching" and not is_signal:
            return None

        # レポート作成
        icon = "👀" if mode == "holding" else "🔔"
        if "買い" in action: icon = "🔥" # AI推奨買い
        
        report = f"{icon} 【{name}】\n"
        report += f"価格: {price_str}\n"
        report += f"採用AI: {best_strat} (勝率{best_win_rate:.0f}%)\n"
        report += f"判断: {action}\n"
        
        if is_signal or mode == "holding":
            report += f"根拠: {reason}\n"
            # 補足情報
            if best_strat == "RSI逆張り":
                report += f"参考: RSI {rsi_val:.0f}\n"
        
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
    print(f"--- AI分析開始: {datetime.now()} ---")
    
    if not GCP_KEY_JSON or not SHEET_URL:
        print("[ERROR] Google Sheets設定(Secrets)がありません")
        return

    holdings, watchlist = get_tickers_from_sheet()
    
    reports = []
    
    if holdings:
        reports.append("【 💰 保有株 AI診断 】")
        for code, name in holdings.items():
            rep = analyze_ticker(code, name, mode="holding")
            if rep: reports.append(rep)
            
    watch_reports = []
    if watchlist:
        for code, name in watchlist.items():
            rep = analyze_ticker(code, name, mode="watching")
            if rep: watch_reports.append(rep)
            
    if watch_reports:
        reports.append("\n【 🔍 監視株 AI推奨 】")
        reports.extend(watch_reports)
    
    if not reports:
        print("通知対象なし")
        return

    full_message = f"🧠 AI投資アシスタント ({datetime.now().strftime('%m/%d')})\n"
    full_message += "過去2年の検証に基づく最適戦略で判断します。\n\n"
    full_message += "\n".join(reports)
    
    if len(full_message) > 2000:
        send_line_push(full_message[:2000] + "\n...(省略)...")
    else:
        send_line_push(full_message)
    
    print("通知完了")

if __name__ == "__main__":
    main()

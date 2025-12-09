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
from backtesting import Backtest, Strategy
from backtesting.lib import crossover

"""
notify.py (自律型AI・安定版)
認証方式を実績のあるoauth2clientに戻し、AI分析機能を統合しました。
"""

# ==========================================
# 設定エリア
# ==========================================
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN', '') 
MY_USER_ID = os.getenv('MY_USER_ID', '')
SHEET_URL = os.getenv('SHEET_URL', '')
GCP_KEY_JSON = os.getenv('GCP_SERVICE_ACCOUNT_KEY', '')

# バックテスト設定
BT_PERIOD = "2y"   # 過去何年分で検証するか
CASH = 1000000     # 検証用資金

# ==========================================
# 1. バックテスト用 戦略クラス定義
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
        # pandas_taのmacdはDataFrameを返す
        macd = ta.macd(close, fast=12, slow=26, signal=9)
        # 列名: MACD_12_26_9, MACDs_12_26_9
        self.macd = self.I(lambda: macd.iloc[:, 0])
        self.signal = self.I(lambda: macd.iloc[:, 1])
    def next(self):
        if crossover(self.macd, self.signal): self.buy()
        elif crossover(self.signal, self.macd): self.position.close()

class BollingerBands(Strategy):
    def init(self):
        close = pd.Series(self.data.Close)
        bb = ta.bbands(close, length=20, std=2)
        # 列名: BBL_20_2.0 (下), BBM... (中), BBU... (上)
        self.lower = self.I(lambda: bb.iloc[:, 0])
        self.upper = self.I(lambda: bb.iloc[:, 2])
    def next(self):
        # 逆張り: 下バンド割れで買い
        if self.data.Close < self.lower: 
            if not self.position.is_long: self.buy()
        # 上バンド超えで手仕舞い
        elif self.data.Close > self.upper: 
            self.position.close()

# 戦略リスト
STRATEGIES = [
    {"name": "SMAクロス", "class": SmaCross},
    {"name": "RSI逆張り", "class": RsiOscillator},
    {"name": "MACD", "class": MacdTrend},
    {"name": "ボリンジャー", "class": BollingerBands}
]

# ==========================================
# 2. 実判定ロジック (現在のデータで判定)
# ==========================================
def check_signal(strategy_name, df):
    """
    選ばれた戦略名に基づいて、直近のデータで売買シグナルが出ているか判定する
    """
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    close = float(latest['Close'])
    
    # 指標値の取得（計算済み前提）
    # SMA
    sma5 = float(latest['SMA_5']) if 'SMA_5' in latest else 0
    sma25 = float(latest['SMA_25']) if 'SMA_25' in latest else 0
    prev_sma5 = float(prev['SMA_5']) if 'SMA_5' in prev else 0
    prev_sma25 = float(prev['SMA_25']) if 'SMA_25' in prev else 0
    
    # RSI
    rsi = float(latest['RSI_14']) if 'RSI_14' in latest else 50
    
    # MACD
    macd = float(latest['MACD_12_26_9']) if 'MACD_12_26_9' in latest else 0
    signal = float(latest['MACDs_12_26_9']) if 'MACDs_12_26_9' in latest else 0
    prev_macd = float(prev['MACD_12_26_9']) if 'MACD_12_26_9' in prev else 0
    prev_signal = float(prev['MACDs_12_26_9']) if 'MACDs_12_26_9' in prev else 0
    
    # BB
    bbl = float(latest['BBL_20_2.0']) if 'BBL_20_2.0' in latest else 0
    bbu = float(latest['BBU_20_2.0']) if 'BBU_20_2.0' in latest else 0

    # --- 判定ロジック ---
    if strategy_name == "SMAクロス":
        if prev_sma5 < prev_sma25 and sma5 > sma25:
            return "買い", "GC発生", True
        elif prev_sma5 > prev_sma25 and sma5 < sma25:
            return "売り", "DC発生", True
            
    elif strategy_name == "RSI逆張り":
        if rsi < 30: return "買い", f"売られすぎ(RSI{rsi:.0f})", True
        elif rsi > 70: return "売り", f"買われすぎ(RSI{rsi:.0f})", True
        
    elif strategy_name == "MACD":
        if prev_macd < prev_signal and macd > signal:
            return "買い", "MACD上抜け", True
        elif prev_macd > prev_signal and macd < signal:
            return "売り", "MACD下抜け", True
            
    elif strategy_name == "ボリンジャー":
        if close < bbl: return "買い", "バンド下限割れ", True
        elif close > bbu: return "売り", "バンド上限到達", True

    return "ステイ", "シグナルなし", False

# ==========================================
# 3. メイン処理
# ==========================================

def get_tickers_from_sheet():
    """スプレッドシートからリスト取得 (安定版ロジック)"""
    try:
        if not GCP_KEY_JSON or not SHEET_URL:
            print("[ERROR] 設定不足: GCP_KEY_JSON または SHEET_URL がありません")
            return {}, {}

        # 以前動作していた oauth2client を使用
        key_dict = json.loads(GCP_KEY_JSON)
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
        client = gspread.authorize(creds)

        sheet = client.open_by_url(SHEET_URL)
        
        holdings_ws = sheet.worksheet('Holdings')
        watchlist_ws = sheet.worksheet('Watchlist')
        
        # データ取得と辞書化 (数値コード対応)
        holdings = {str(r['Ticker']).strip(): r['Name'] for r in holdings_ws.get_all_records() if r['Ticker']}
        watchlist = {str(r['Ticker']).strip(): r['Name'] for r in watchlist_ws.get_all_records() if r['Ticker']}
        
        return holdings, watchlist
    except Exception as e:
        print(f"[ERROR] スプレッドシート読込エラー: {e}")
        return {}, {}

def analyze_and_optimize(ticker, name, mode="holding"):
    """
    各戦略でバックテストを行い、最適なものを採用して判定する
    """
    try:
        # コードの正規化
        yf_ticker = str(ticker).strip()
        if yf_ticker.isdigit():
            yf_ticker = f"{yf_ticker}.T"

        # 1. データ取得
        time.sleep(1)
        df = yf.download(yf_ticker, period=BT_PERIOD, interval="1d", progress=False)
        
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

        # 2. 全指標計算 (判定用にまとめて計算)
        df.ta.sma(length=5, append=True)
        df.ta.sma(length=25, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        df.ta.bbands(length=20, std=2, append=True)

        # 3. 戦略総当たりバックテスト
        best_strat_name = "SMAクロス"
        best_win_rate = 0
        
        for strat in STRATEGIES:
            try:
                # バックテスト実行
                bt = Backtest(df, strat["class"], cash=CASH, commission=.002)
                stats = bt.run()
                win_rate = stats['Win Rate [%]']
                
                # 勝率が高いものを採用
                if win_rate > best_win_rate:
                    best_win_rate = win_rate
                    best_strat_name = strat["name"]
            except Exception:
                continue # エラーが出た戦略はスキップ

        # 4. 最適戦略に基づいて現状判定
        action, reason, is_signal = check_signal(best_strat_name, df)
        
        # 5. 前日比
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        close = float(latest['Close'])
        price_diff = close - float(prev['Close'])
        pct = (price_diff / float(prev['Close'])) * 100
        price_str = f"{int(close):,}円 ({'+' if price_diff>0 else ''}{pct:.1f}%)"

        # --- 通知フィルタ ---
        if mode == "watching" and not is_signal:
            return None

        # 6. レポート作成
        icon = "👀" if mode == "holding" else "🔔"
        if "買い" in action: icon = "🚀"
        elif "売り" in action: icon = "🔻"
        
        report = f"{icon} 【{name}】 ({ticker})\n"
        report += f"株価: {price_str}\n"
        report += f"判定: {action}\n"
        report += f"採用AI: {best_strat_name} (勝率{best_win_rate:.0f}%)\n"
        if is_signal or mode == "holding":
            report += f"根拠: {reason}\n"
        
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
    print(f"--- AI自動分析開始: {datetime.now()} ---")
    
    # シート取得
    holdings, watchlist = get_tickers_from_sheet()
    
    reports = []
    
    # 保有株
    if holdings:
        reports.append("【 💰 保有株 AI診断 】")
        for c, n in holdings.items():
            r = analyze_and_optimize(c, n, mode="holding")
            if r: reports.append(r)
            
    # 監視株
    watch_reports = []
    if watchlist:
        for c, n in watchlist.items():
            r = analyze_and_optimize(c, n, mode="watching")
            if r: watch_reports.append(r)
            
    if watch_reports:
        reports.append("\n【 🔍 チャンス到来銘柄 】")
        reports.extend(watch_reports)
    
    if not reports:
        print("通知対象なし")
        return

    full_message = f"🤖 AI株価最適化レポート\n📅 {datetime.now().strftime('%m/%d')}\n\n"
    full_message += "\n".join(reports)
    
    print(full_message) # ログ用
    
    if len(full_message) > 2000:
        send_line_push(full_message[:2000] + "\n...(省略)...")
    else:
        send_line_push(full_message)
    
    print("通知完了")

if __name__ == "__main__":
    main()

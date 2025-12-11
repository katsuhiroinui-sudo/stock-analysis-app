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
    print("[ERROR] backtestingライブラリが見つかりません。requirements.txtを確認してください。")
    sys.exit(1)

"""
notify.py (AI搭載・自動バックテスト版)
・過去2年間のデータを元に、4つの戦略から「最も勝率が高い戦略」を自動選定します。
・選定された戦略に基づいて、当日の売買判断（買い/売り/ステイ）を行います。
"""

# ==========================================
# 設定エリア
# ==========================================
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN', '') 
MY_USER_ID = os.getenv('MY_USER_ID', '')
SHEET_URL = os.getenv('SHEET_URL', '')
GCP_KEY_JSON = os.getenv('GCP_SERVICE_ACCOUNT_KEY', '')

# ==========================================
# 1. AI分析用 戦略クラス定義 (app.pyと共通)
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
def check_current_signal(strategy_name, df):
    """最新データに基づいて売買シグナルを判定"""
    try:
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        close = float(latest['Close'])
        
        # 安全に値を取得するヘルパー関数
        def g(row, k, d=0): return float(row[k]) if k in row and not pd.isna(row[k]) else d

        sma5, sma25 = g(latest,'SMA_5'), g(latest,'SMA_25')
        p_sma5, p_sma25 = g(prev,'SMA_5'), g(prev,'SMA_25')
        rsi = g(latest,'RSI_14', 50)
        macd, sig = g(latest,'MACD_12_26_9'), g(latest,'MACDs_12_26_9')
        p_macd, p_sig = g(prev,'MACD_12_26_9'), g(prev,'MACDs_12_26_9')
        bbl, bbu = g(latest,'BBL_20_2.0'), g(latest,'BBU_20_2.0')

        if strategy_name == "SMAクロス":
            if p_sma5 < p_sma25 and sma5 > sma25: return "買い 🚀", "GC発生"
            elif p_sma5 > p_sma25 and sma5 < sma25: return "売り 🔻", "DC発生"
        elif strategy_name == "RSI逆張り":
            if rsi < 30: return "買い 🚀", f"RSI売られすぎ({rsi:.0f})"
            elif rsi > 70: return "売り 🔻", f"RSI買われすぎ({rsi:.0f})"
        elif strategy_name == "MACD":
            if p_macd < p_sig and macd > sig: return "買い 🚀", "MACD上抜け"
            elif p_macd > p_sig and macd < sig: return "売り 🔻", "MACD下抜け"
        elif strategy_name == "ボリンジャー":
            if close < bbl: return "買い 🚀", "バンド下限割れ"
            elif close > bbu: return "売り 🔻", "バンド上限到達"
            
        return "ステイ 🤔", "シグナルなし"
    except Exception as e:
        return "判定不能", f"エラー: {e}"

# ==========================================
# 3. メイン処理・通知連携
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

def analyze_ticker_ai(ticker, name, mode="holding"):
    """
    AI分析実行関数
    1. 過去2年のデータを取得
    2. 全戦略をバックテスト
    3. 勝率No.1の戦略を採用し、今日の売買判断を行う
    """
    try:
        # コードの正規化
        yf_ticker = str(ticker).strip()
        if yf_ticker.isdigit():
            yf_ticker = f"{yf_ticker}.T"

        # データ取得 (バックテスト用に2年分)
        time.sleep(1) 
        df = yf.download(yf_ticker, period="2y", interval="1d", progress=False)
        
        if df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 現在の指標計算（判定用）
        df.ta.sma(length=5, append=True)
        df.ta.sma(length=25, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        df.ta.bbands(length=20, std=2, append=True)

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        close = float(latest['Close'])
        prev_close = float(prev['Close'])
        
        # 前日比計算
        price_diff = close - prev_close
        price_change_pct = (price_diff / prev_close) * 100
        sign = "+" if price_diff > 0 else ""
        price_str = f"{int(close):,}円 ({sign}{price_change_pct:.1f}%)"

        # --- AIバックテスト実行 ---
        best_strat_name = "SMAクロス" # デフォルト
        best_win_rate = -1
        
        # 全戦略をテストしてベストを探す
        for strat in STRATEGIES:
            try:
                bt = Backtest(df, strat["class"], cash=1000000, commission=.002)
                stats = bt.run()
                win_rate = stats['Win Rate [%]']
                
                # 勝率が高いものを採用 (同率なら後勝ち)
                if win_rate >= best_win_rate:
                    best_win_rate = win_rate
                    best_strat_name = strat["name"]
            except:
                continue

        # ベスト戦略で現在の判定を行う
        action_text, reason_text = check_current_signal(best_strat_name, df)
        
        # シグナル有無フラグ
        is_signal = "買い" in action_text or "売り" in action_text
        
        # 監視株モードでシグナルなしならスキップ
        if mode == "watching" and not is_signal:
            return None

        # レポート生成
        icon = "👀" if mode == "holding" else "🔔"
        if "買い" in action_text: icon = "🚀"
        elif "売り" in action_text: icon = "🔻"
        
        report = f"{icon} 【{name}】 ({ticker})\n"
        report += f"株価: {price_str}\n"
        
        # AI分析結果の追記
        report += f"推奨戦略: {best_strat_name} (勝率{best_win_rate:.0f}%)\n"
        report += f"AI判定: {action_text}\n"
        
        if is_signal or mode == "holding":
            report += f"根拠: {reason_text}\n"
        
        report += "-" * 10
        return report

    except Exception as e:
        print(f"Error analyzing {ticker}: {e}")
        return None

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
    
    # 保有株の分析
    if holdings:
        reports.append("【 💰 保有株 AI診断 】")
        for code, name in holdings.items():
            rep = analyze_ticker_ai(code, name, mode="holding")
            if rep: reports.append(rep)
            
    # 監視株の分析
    watch_reports = []
    if watchlist:
        for code, name in watchlist.items():
            rep = analyze_ticker_ai(code, name, mode="watching")
            if rep: watch_reports.append(rep)
            
    if watch_reports:
        reports.append("\n【 🔍 監視株 AIシグナル 】")
        reports.extend(watch_reports)
    
    if not reports:
        print("通知対象なし")
        return

    full_message = f"📊 株価AI分析レポート ({datetime.now().strftime('%m/%d')})\n"
    full_message += "過去2年のデータを全戦略で検証し、最適解を導出しました。\n\n"
    full_message += "\n".join(reports)
    
    if len(full_message) > 2000:
        send_line_push(full_message[:2000] + "\n...(省略)...")
    else:
        send_line_push(full_message)
    
    print("通知完了")

if __name__ == "__main__":
    main()

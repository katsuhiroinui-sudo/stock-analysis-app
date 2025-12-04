import yfinance as yf
import pandas as pd
import pandas_ta as ta
import requests
import json
import os
from backtesting import Backtest, Strategy
from backtesting.lib import crossover
from backtesting.test import SMA

# ---------------------------------------------------------
# 設定エリア
# ---------------------------------------------------------
# 監視する銘柄リスト (ここに監視したい銘柄をすべて書いてください)
TICKERS = ["7453.T", "7203.T", "8306.T", "9984.T", "7011.T", "8136.T", "7974.T", "6758.T"]

# GitHubの設定(Secrets)から読み込む
GAS_URL = os.environ.get("GAS_URL")
LINE_USER_ID = os.environ.get("LINE_USER_ID") # ない場合はGAS側のバックアップが使われます

# ---------------------------------------------------------
# ロジック定義 (HybridStrategy) - app.pyと同じもの
# ---------------------------------------------------------
class HybridStrategy(Strategy):
    n1 = 10; n2 = 30; rsi_period = 14; rsi_upper = 70; rsi_lower = 30; adx_period = 14; adx_threshold = 25
    def init(self):
        self.sma1 = self.I(SMA, self.data.Close, self.n1)
        self.sma2 = self.I(SMA, self.data.Close, self.n2)
        self.rsi = self.I(ta.rsi, pd.Series(self.data.Close), length=self.rsi_period)
        self.adx = self.I(lambda x, y, z: ta.adx(x, y, z, length=self.adx_period)['ADX_14'],
                          pd.Series(self.data.High), pd.Series(self.data.Low), pd.Series(self.data.Close))
    def next(self):
        if self.adx[-1] > self.adx_threshold:
            if crossover(self.sma1, self.sma2): self.buy()
            elif crossover(self.sma2, self.sma1): self.position.close()
        else:
            if self.rsi[-1] < self.rsi_lower and not self.position: self.buy()
            elif self.rsi[-1] > self.rsi_upper: self.position.close()

# Flex Message作成関数
def create_flex_message(ticker, price, signal, profit_factor, return_rate):
    color = "#E63946" if "買い" in signal else "#1D3557"
    return {
      "type": "bubble",
      "body": {
        "type": "box", "layout": "vertical",
        "contents": [
          {"type": "text", "text": "🔔 自動定期チェック", "color": "#1DB446", "size": "xs", "weight": "bold"},
          {"type": "text", "text": ticker, "size": "xl", "weight": "bold"},
          {"type": "text", "text": f"¥{price:,.0f}", "size": "xxl", "weight": "bold", "color": "#333333"},
          {"type": "separator", "margin": "md"},
          {"type": "box", "layout": "vertical", "margin": "md", "contents": [
              {"type": "text", "text": f"判定: {signal}", "color": color, "weight": "bold", "size": "md"},
              {"type": "text", "text": f"収益率: {return_rate}% / PF: {profit_factor}", "color": "#666666", "size": "xs"}
          ]}
        ]
      },
      "footer": {
        "type": "box", "layout": "vertical", "contents": [
          {"type": "button", "action": {"type": "uri", "label": "詳細を確認する", "uri": f"https://finance.yahoo.co.jp/quote/{ticker}"}}
        ]
      }
    }

# ---------------------------------------------------------
# メイン処理
# ---------------------------------------------------------
def main():
    if not GAS_URL:
        print("エラー: GAS_URLが設定されていません。")
        return

    print(f"🔍 {len(TICKERS)} 銘柄の自動分析を開始します...")
    
    for ticker in TICKERS:
        try:
            # データ取得
            df = yf.download(ticker, period="730d", interval="1h", auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df = df.dropna()
            
            if len(df) > 100:
                # バックテスト
                bt = Backtest(df, HybridStrategy, cash=1000000, commission=0.001)
                stats = bt.run()
                
                # シグナル判定
                trades = stats['_trades']
                # 「現在ポジションを持っている」場合のみ通知対象
                if len(trades) > 0 and pd.isna(trades.iloc[-1]['ExitTime']):
                    last_signal = "🟢 買い保有中"
                    current_price = df['Close'].iloc[-1]
                    
                    print(f"送信中: {ticker} はチャンス銘柄です")
                    
                    # LINE送信
                    flex = create_flex_message(
                        ticker, 
                        current_price, 
                        last_signal, 
                        f"{stats['Profit Factor']:.2f}", 
                        f"{stats['Return [%]']:.1f}"
                    )
                    
                    payload = {
                        "mode": "push",
                        "userId": LINE_USER_ID, # 設定がなければNoneになりGAS側バックアップが動作
                        "flexContents": flex
                    }
                    
                    requests.post(GAS_URL, json=payload)
                else:
                    print(f"対象外: {ticker}")

        except Exception as e:
            print(f"エラー ({ticker}): {e}")

if __name__ == "__main__":
    main()
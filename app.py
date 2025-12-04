import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import mplfinance as mpf
import japanize_matplotlib
import requests
import json
from backtesting import Backtest, Strategy
from backtesting.lib import crossover
from backtesting.test import SMA

# ==========================================
# 1. アプリのUI設定 (サイドバーなど)
# ==========================================
st.set_page_config(page_title="AI株価分析", layout="wide")
st.title("📈 AI株価分析アプリ (LINE連携版)")

st.sidebar.header("📊 分析設定")
# 銘柄コード入力 (デフォルトは良品計画)
ticker_input = st.sidebar.text_input("銘柄コード (例: 7453.T)", "7453.T")
# 期間選択
period_days = st.sidebar.slider("分析期間 (過去何日分?)", 365, 3650, 730)

st.sidebar.markdown("---")
st.sidebar.header("📱 LINE通知設定")
# GASのURL入力欄
gas_url = st.sidebar.text_input("GASウェブアプリURL", placeholder="https://script.google.com/macros/s/...")
# ユーザーID入力欄
line_user_id = st.sidebar.text_input("LINE User ID (任意)", placeholder="Uxxxxxxxxxxxx... (空欄ならGAS設定値を使用)")

# 実行ボタン
run_button = st.sidebar.button("分析実行 & 通知確認", type="primary")

# ==========================================
# 2. ロジック定義 (ハイブリッド戦略)
# ==========================================
class HybridStrategy(Strategy):
    # パラメータ設定
    n1 = 10         # SMA短期
    n2 = 30         # SMA長期
    rsi_period = 14 # RSI期間
    rsi_upper = 70  # RSI売りライン
    rsi_lower = 30  # RSI買いライン
    adx_period = 14 # ADX期間
    adx_threshold = 25 # トレンド判定閾値

    def init(self):
        # 移動平均線
        self.sma1 = self.I(SMA, self.data.Close, self.n1)
        self.sma2 = self.I(SMA, self.data.Close, self.n2)
        # RSI
        self.rsi = self.I(ta.rsi, pd.Series(self.data.Close), length=self.rsi_period)
        # ADX (トレンドの強さ)
        self.adx = self.I(lambda x, y, z: ta.adx(x, y, z, length=self.adx_period)['ADX_14'],
                          pd.Series(self.data.High), pd.Series(self.data.Low), pd.Series(self.data.Close))

    def next(self):
        current_adx = self.adx[-1]
        
        # トレンド相場 (ADX > 25) → 移動平均線順張り
        if current_adx > self.adx_threshold:
            if crossover(self.sma1, self.sma2):
                self.buy()
            elif crossover(self.sma2, self.sma1):
                self.position.close()
        
        # レンジ相場 (ADX <= 25) → RSI逆張り
        else:
            if self.rsi[-1] < self.rsi_lower and not self.position:
                self.buy()
            elif self.rsi[-1] > self.rsi_upper:
                self.position.close()

# ==========================================
# 3. Flex Message 生成関数 (デザイン定義)
# ==========================================
def create_flex_message(ticker, price, signal, profit_factor, return_rate):
    # シグナルに応じた色設定
    color = "#E63946" if "買い" in signal else "#1D3557" # 赤か紺
    if "様子見" in signal: color = "#AAAAAA" # グレー
    
    # Flex MessageのJSONデータ
    flex_json = {
      "type": "bubble",
      "body": {
        "type": "box",
        "layout": "vertical",
        "contents": [
          {"type": "text", "text": "AI株価分析通知", "weight": "bold", "color": "#1DB446", "size": "sm"},
          {"type": "text", "text": ticker, "weight": "bold", "size": "xl", "margin": "md"},
          {"type": "text", "text": f"¥{price:,.0f}", "size": "3xl", "weight": "bold", "color": "#333333"},
          {"type": "separator", "margin": "lg"},
          {
            "type": "box",
            "layout": "vertical",
            "margin": "lg",
            "spacing": "sm",
            "contents": [
              {
                "type": "box", "layout": "baseline", "spacing": "sm",
                "contents": [
                  {"type": "text", "text": "判定", "color": "#aaaaaa", "size": "sm", "flex": 1},
                  {"type": "text", "text": signal, "wrap": True, "color": color, "size": "lg", "weight": "bold", "flex": 4}
                ]
              },
              {
                "type": "box", "layout": "baseline", "spacing": "sm",
                "contents": [
                  {"type": "text", "text": "収益率", "color": "#aaaaaa", "size": "sm", "flex": 1},
                  {"type": "text", "text": f"{return_rate}%", "wrap": True, "color": "#666666", "size": "sm", "flex": 4}
                ]
              },
               {
                "type": "box", "layout": "baseline", "spacing": "sm",
                "contents": [
                  {"type": "text", "text": "PF", "color": "#aaaaaa", "size": "sm", "flex": 1},
                  {"type": "text", "text": str(profit_factor), "wrap": True, "color": "#666666", "size": "sm", "flex": 4}
                ]
              }
            ]
          }
        ]
      },
      "footer": {
        "type": "box",
        "layout": "vertical",
        "contents": [
          {"type": "button", "action": {"type": "uri", "label": "Yahoo!ファイナンスで見る", "uri": "https://finance.yahoo.co.jp/quote/" + ticker}}
        ]
      }
    }
    return flex_json

# ==========================================
# 4. メイン処理 (実行ボタン押下時)
# ==========================================
if run_button:
    st.write(f"🔍 {ticker_input} のデータを分析しています...")
    
    try:
        # --- データ取得 ---
        df = yf.download(ticker_input, period=f"{period_days}d", interval="1h", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()

        if len(df) < 100:
            st.error(f"データが不足しています（{len(df)}件）。期間を延ばすか、銘柄コードを確認してください。")
        else:
            # --- バックテスト実行 ---
            bt = Backtest(df, HybridStrategy, cash=1_000_000, commission=0.001, exclusive_orders=True)
            stats = bt.run()
            
            # --- 最新のシグナル判定 ---
            last_close = df['Close'].iloc[-1]
            last_signal = "様子見"
            
            # トレード履歴から現在の状態を確認
            trades = stats['_trades']
            if len(trades) > 0:
                last_trade = trades.iloc[-1]
                # ExitTimeがNaT(空白)なら、まだ保有中ということ
                if pd.isna(last_trade['ExitTime']):
                     last_signal = "買い保有中 (上昇トレンド)"
                else:
                     # ポジションはないが、直近の動向から判断
                     last_signal = "様子見 (シグナル待ち)"
            
            # --- 画面表示 ---
            # 指標カラム
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("現在価格", f"¥{last_close:,.0f}")
            col2.metric("AI判定", last_signal)
            col3.metric("過去の収益率", f"{stats['Return [%]']:.1f}%")
            col4.metric("プロフィットファクター", f"{stats['Profit Factor']:.2f}")

            # チャート作成・表示
            # 見やすいように直近300本に絞る
            plot_length = 300
            df_plot = df.copy()
            df_plot['SMA10'] = ta.sma(df_plot['Close'], length=10)
            df_plot['SMA30'] = ta.sma(df_plot['Close'], length=30)
            df_plot['RSI']   = ta.rsi(df_plot['Close'], length=14)

            # 売買サインのプロット準備
            buy_signals = [float('nan')] * len(df_plot)
            sell_signals = [float('nan')] * len(df_plot)
            for index, trade in trades.iterrows():
                if trade['EntryTime'] in df_plot.index:
                    idx = df_plot.index.get_loc(trade['EntryTime'])
                    buy_signals[idx] = df_plot.loc[trade['EntryTime'], 'Low'] * 0.98
                if trade['ExitTime'] in df_plot.index:
                    idx = df_plot.index.get_loc(trade['ExitTime'])
                    sell_signals[idx] = df_plot.loc[trade['ExitTime'], 'High'] * 1.02
            
            # データの切り出し
            df_subset = df_plot.tail(plot_length)
            buy_subset = buy_signals[-plot_length:]
            sell_subset = sell_signals[-plot_length:]
            
            # チャート設定
            plots = [
                mpf.make_addplot(df_subset['SMA10'], color='orange', width=1.5, panel=0),
                mpf.make_addplot(df_subset['SMA30'], color='skyblue', width=1.5, panel=0),
                mpf.make_addplot(buy_subset, type='scatter', markersize=100, marker='^', color='red', panel=0, label='買い'),
                mpf.make_addplot(sell_subset, type='scatter', markersize=100, marker='v', color='blue', panel=0, label='売り'),
                mpf.make_addplot(df_subset['RSI'], color='purple', panel=2, ylabel='RSI'),
            ]
            my_style = mpf.make_mpf_style(base_mpf_style='yahoo', rc={'font.family': 'IPAexGothic'})

            # 図形として取得してStreamlitで表示
            fig, axlist = mpf.plot(df_subset, type='candle', style=my_style, addplot=plots,
                     title=f"{ticker_input} 分析チャート", volume=True, figsize=(10, 8), 
                     panel_ratios=(6, 2, 2), returnfig=True)
            st.pyplot(fig)

            # --- LINE送信処理 ---
            if gas_url:
                st.info("LINE通知を送信しています...")
                
                # Flex Message作成
                flex_data = create_flex_message(
                    ticker_input, 
                    last_close, 
                    last_signal, 
                    round(stats['Profit Factor'], 2), 
                    round(stats['Return [%]'], 2)
                )

                # GASへの送信データ
                payload = {
                    "mode": "push",
                    "userId": line_user_id, # 空欄でもOK（GAS側でバックアップ使用）
                    "flexContents": flex_data
                }
                
                try:
                    response = requests.post(gas_url, json=payload)
                    
                    if response.status_code == 200:
                        st.success(f"✅ LINE通知成功！ (ステータス: {response.status_code})")
                    else:
                        st.error(f"❌ 送信失敗: {response.text}")
                except Exception as e:
                    st.error(f"通信エラー: {e}")
            else:
                st.warning("⚠️ LINE通知を行うには、サイドバーでGASのURLを入力してください。")

    except Exception as e:
        st.error(f"システムエラーが発生しました: {e}")

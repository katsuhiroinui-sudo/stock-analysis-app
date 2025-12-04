import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import mplfinance as mpf
import requests
import json
import matplotlib.font_manager as fm # フォント管理用
from backtesting import Backtest, Strategy
from backtesting.lib import crossover
from backtesting.test import SMA

# ==========================================
# 0. 日本語フォントの設定 (ここが修正ポイント)
# ==========================================
# 同じフォルダにある 'ipaexg.ttf' を登録する
font_path = 'ipaexg.ttf'
try:
    fm.fontManager.addfont(font_path)
    font_prop = fm.FontProperties(fname=font_path)
    font_name = font_prop.get_name()
    # matplotlibのデフォルトフォントに設定
    pd.options.plotting.backend = 'matplotlib'
    import matplotlib.pyplot as plt
    plt.rc('font', family=font_name)
except Exception as e:
    st.warning(f"フォント読み込みエラー: {e}")
    font_name = "sans-serif" # 失敗時は標準フォント

# ==========================================
# 1. アプリのUI設定
# ==========================================
st.set_page_config(page_title="AI株価分析", layout="wide")
st.title("📈 AI株価分析アプリ (LINE連携版)")

st.sidebar.header("📊 分析設定")
ticker_input = st.sidebar.text_input("銘柄コード (例: 7453.T)", "7453.T")
period_days = st.sidebar.slider("分析期間 (過去何日分?)", 365, 3650, 730)

st.sidebar.markdown("---")
st.sidebar.header("📱 LINE通知設定")
gas_url = st.sidebar.text_input("GASウェブアプリURL", placeholder="https://script.google.com/macros/s/...")
line_user_id = st.sidebar.text_input("LINE User ID (任意)", placeholder="Uxxxxxxxxxxxx... (空欄ならGAS設定値を使用)")

run_button = st.sidebar.button("分析実行 & 通知確認", type="primary")

# ==========================================
# 2. ロジック定義 (ハイブリッド戦略)
# ==========================================
class HybridStrategy(Strategy):
    n1 = 10; n2 = 30; rsi_period = 14; rsi_upper = 70; rsi_lower = 30; adx_period = 14; adx_threshold = 25
    def init(self):
        self.sma1 = self.I(SMA, self.data.Close, self.n1)
        self.sma2 = self.I(SMA, self.data.Close, self.n2)
        self.rsi = self.I(ta.rsi, pd.Series(self.data.Close), length=self.rsi_period)
        self.adx = self.I(lambda x, y, z: ta.adx(x, y, z, length=self.adx_period)['ADX_14'],
                          pd.Series(self.data.High), pd.Series(self.data.Low), pd.Series(self.data.Close))
    def next(self):
        current_adx = self.adx[-1]
        if current_adx > self.adx_threshold:
            if crossover(self.sma1, self.sma2): self.buy()
            elif crossover(self.sma2, self.sma1): self.position.close()
        else:
            if self.rsi[-1] < self.rsi_lower and not self.position: self.buy()
            elif self.rsi[-1] > self.rsi_upper: self.position.close()

# ==========================================
# 3. Flex Message 生成関数
# ==========================================
def create_flex_message(ticker, price, signal, profit_factor, return_rate):
    color = "#E63946" if "買い" in signal else "#1D3557"
    if "様子見" in signal: color = "#AAAAAA"
    
    flex_json = {
      "type": "bubble",
      "body": {
        "type": "box", "layout": "vertical",
        "contents": [
          {"type": "text", "text": "AI株価分析通知", "weight": "bold", "color": "#1DB446", "size": "sm"},
          {"type": "text", "text": ticker, "weight": "bold", "size": "xl", "margin": "md"},
          {"type": "text", "text": f"¥{price:,.0f}", "size": "3xl", "weight": "bold", "color": "#333333"},
          {"type": "separator", "margin": "lg"},
          {
            "type": "box", "layout": "vertical", "margin": "lg", "spacing": "sm",
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
        "type": "box", "layout": "vertical",
        "contents": [
          {"type": "button", "action": {"type": "uri", "label": "Yahoo!ファイナンスで見る", "uri": "https://finance.yahoo.co.jp/quote/" + ticker}}
        ]
      }
    }
    return flex_json

# ==========================================
# 4. メイン処理
# ==========================================
if run_button:
    st.write(f"🔍 {ticker_input} のデータを分析しています...")
    try:
        df = yf.download(ticker_input, period=f"{period_days}d", interval="1h", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df.dropna()

        if len(df) < 100:
            st.error(f"データが不足しています（{len(df)}件）。")
        else:
            bt = Backtest(df, HybridStrategy, cash=1_000_000, commission=0.001, exclusive_orders=True)
            stats = bt.run()
            
            last_close = df['Close'].iloc[-1]
            last_signal = "様子見"
            trades = stats['_trades']
            if len(trades) > 0:
                last_trade = trades.iloc[-1]
                if pd.isna(last_trade['ExitTime']): last_signal = "買い保有中 (上昇トレンド)"
                else: last_signal = "様子見 (シグナル待ち)"
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("現在価格", f"¥{last_close:,.0f}")
            col2.metric("AI判定", last_signal)
            col3.metric("過去の収益率", f"{stats['Return [%]']:.1f}%")
            col4.metric("プロフィットファクター", f"{stats['Profit Factor']:.2f}")

            plot_length = 300
            df_plot = df.copy()
            df_plot['SMA10'] = ta.sma(df_plot['Close'], length=10)
            df_plot['SMA30'] = ta.sma(df_plot['Close'], length=30)
            df_plot['RSI']   = ta.rsi(df_plot['Close'], length=14)

            buy_signals = [float('nan')] * len(df_plot)
            sell_signals = [float('nan')] * len(df_plot)
            for index, trade in trades.iterrows():
                if trade['EntryTime'] in df_plot.index:
                    idx = df_plot.index.get_loc(trade['EntryTime'])
                    buy_signals[idx] = df_plot.loc[trade['EntryTime'], 'Low'] * 0.98
                if trade['ExitTime'] in df_plot.index:
                    idx = df_plot.index.get_loc(trade['ExitTime'])
                    sell_signals[idx] = df_plot.loc[trade['ExitTime'], 'High'] * 1.02
            
            df_subset = df_plot.tail(plot_length)
            buy_subset = buy_signals[-plot_length:]
            sell_subset = sell_signals[-plot_length:]
            
            plots = [
                mpf.make_addplot(df_subset['SMA10'], color='orange', width=1.5, panel=0),
                mpf.make_addplot(df_subset['SMA30'], color='skyblue', width=1.5, panel=0),
                mpf.make_addplot(buy_subset, type='scatter', markersize=100, marker='^', color='red', panel=0, label='買い'),
                mpf.make_addplot(sell_subset, type='scatter', markersize=100, marker='v', color='blue', panel=0, label='売り'),
                mpf.make_addplot(df_subset['RSI'], color='purple', panel=2, ylabel='RSI'),
            ]
            
            # 修正: フォントファイルを指定したスタイルを作成
            my_style = mpf.make_mpf_style(base_mpf_style='yahoo', rc={'font.family': font_name})

            fig, axlist = mpf.plot(df_subset, type='candle', style=my_style, addplot=plots,
                     title=f"{ticker_input} 分析チャート", volume=True, figsize=(10, 8), 
                     panel_ratios=(6, 2, 2), returnfig=True)
            st.pyplot(fig)

            if gas_url:
                st.info("LINE通知を送信しています...")
                flex_data = create_flex_message(
                    ticker_input, last_close, last_signal, 
                    round(stats['Profit Factor'], 2), round(stats['Return [%]'], 2)
                )
                payload = { "mode": "push", "userId": line_user_id, "flexContents": flex_data }
                try:
                    response = requests.post(gas_url, json=payload)
                    if response.status_code == 200: st.success(f"✅ LINE通知成功！")
                    else: st.error(f"❌ 送信失敗: {response.text}")
                except Exception as e: st.error(f"通信エラー: {e}")
            else:
                st.warning("⚠️ LINE通知を行うには、サイドバーでGASのURLを入力してください。")
    except Exception as e:
        st.error(f"システムエラー: {e}")
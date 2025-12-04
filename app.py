import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import mplfinance as mpf
import requests
import json
import matplotlib.font_manager as fm
from backtesting import Backtest, Strategy
from backtesting.lib import crossover
from backtesting.test import SMA

# ==========================================
# 0. 日本語フォントの設定
# ==========================================
# GitHubにアップロードした 'ipaexg.ttf' を読み込む
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
    # フォントがない場合は警告を出さずにデフォルトへ（動作優先）
    font_name = "sans-serif"

# ==========================================
# 1. UI設定 (サイドバー)
# ==========================================
st.set_page_config(page_title="AI株価監視盤", layout="wide")
st.title("📈 AI株価一括スキャン & 分析アプリ")

st.sidebar.header("📊 監視設定")
# デフォルトの監視リスト
default_tickers = "7453.T, 7203.T, 8306.T, 9984.T, 7011.T, 8136.T, 7974.T, 6758.T"
tickers_input = st.sidebar.text_area("監視銘柄リスト (カンマ区切り)", default_tickers, height=100)
# リストをリスト形式に変換
ticker_list = [t.strip() for t in tickers_input.split(",") if t.strip()]

period_days = st.sidebar.slider("分析期間 (日)", 365, 3650, 730)

st.sidebar.markdown("---")
st.sidebar.header("📱 LINE通知設定")
gas_url = st.sidebar.text_input("GASウェブアプリURL", placeholder="https://script.google.com/macros/s/...")
line_user_id = st.sidebar.text_input("LINE User ID (任意)", placeholder="Uxxxxxxxxxxxx... (空欄ならGAS設定値)")

st.sidebar.markdown("---")
# モード選択
analysis_mode = st.sidebar.radio("モード選択", ["一括スキャン (ランキング)", "詳細チャート分析"])

# ==========================================
# 2. ロジック定義 (HybridStrategy)
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
        # トレンド相場 (ADX > 25)
        if self.adx[-1] > self.adx_threshold:
            if crossover(self.sma1, self.sma2): self.buy()
            elif crossover(self.sma2, self.sma1): self.position.close()
        # レンジ相場 (ADX <= 25)
        else:
            if self.rsi[-1] < self.rsi_lower and not self.position: self.buy()
            elif self.rsi[-1] > self.rsi_upper: self.position.close()

# Flex Message作成関数
def create_flex_message(ticker, price, signal, profit_factor, return_rate):
    color = "#E63946" if "買い" in signal else "#1D3557"
    if "様子見" in signal: color = "#AAAAAA"
    
    return {
      "type": "bubble",
      "body": {
        "type": "box", "layout": "vertical",
        "contents": [
          {"type": "text", "text": "AI株価通知", "color": "#1DB446", "size": "xs", "weight": "bold"},
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
          {"type": "button", "action": {"type": "uri", "label": "Yahoo!ファイナンス", "uri": f"https://finance.yahoo.co.jp/quote/{ticker}"}}
        ]
      }
    }

# ==========================================
# 3. メイン処理
# ==========================================

# --- モードA: 一括スキャン ---
if analysis_mode == "一括スキャン (ランキング)":
    st.header("📊 監視銘柄 一括スキャン")
    
    if st.button("スキャン実行", type="primary"):
        st.write(f"🔍 リストにある {len(ticker_list)} 銘柄を分析しています...")
        progress_bar = st.progress(0)
        results = []
        
        for i, ticker in enumerate(ticker_list):
            try:
                # データ取得
                df = yf.download(ticker, period=f"{period_days}d", interval="1h", auto_adjust=True, progress=False)
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                df = df.dropna()
                
                if len(df) > 100:
                    # バックテスト実行
                    bt = Backtest(df, HybridStrategy, cash=1000000, commission=0.001)
                    stats = bt.run()
                    
                    # 最新シグナル判定
                    last_signal = "様子見"
                    trades = stats['_trades']
                    # ポジション保有中かチェック
                    if len(trades) > 0 and pd.isna(trades.iloc[-1]['ExitTime']):
                        last_signal = "🟢 買い保有中"
                    
                    results.append({
                        "銘柄": ticker,
                        "現在値": f"¥{df['Close'].iloc[-1]:,.0f}",
                        "AI判定": last_signal,
                        "収益率": f"{stats['Return [%]']:.1f}%",
                        "PF": f"{stats['Profit Factor']:.2f}",
                        "勝率": f"{stats['Win Rate [%]']:.1f}%",
                        "_raw_return": stats['Return [%]'] # ソート用
                    })
            except Exception as e:
                pass # エラーの銘柄はスキップ
            
            # 進捗バー更新
            progress_bar.progress((i + 1) / len(ticker_list))
            
        # 結果表示
        if results:
            res_df = pd.DataFrame(results)
            # 収益率が高い順にソート
            res_df = res_df.sort_values("_raw_return", ascending=False).drop("_raw_return", axis=1)
            
            st.success("分析完了！収益率が高い順に表示します。")
            st.dataframe(res_df, use_container_width=True)
            
            # 「保有中」の銘柄があればLINE通知ボタンを表示
            holding_stocks = [r for r in results if "保有中" in r["AI判定"]]
            
            if holding_stocks:
                st.markdown("### 🔔 チャンス銘柄が見つかりました")
                if gas_url:
                    if st.button(f"チャンス銘柄 ({len(holding_stocks)}件) をLINEに通知"):
                        for item in holding_stocks:
                            flex = create_flex_message(
                                item["銘柄"], 
                                int(item["現在値"].replace("¥","").replace(",","")), 
                                item["AI判定"], 
                                item["PF"], 
                                item["収益率"].replace("%","")
                            )
                            requests.post(gas_url, json={"mode":"push", "userId":line_user_id, "flexContents":flex})
                        st.success("LINE通知を送信しました！")
                else:
                    st.warning("LINE通知を送るにはGAS URLを設定してください。")
            else:
                st.info("現在、AIが推奨する「買い保有中」の銘柄はありません。")
        else:
            st.error("データが取得できませんでした。銘柄コードを確認してください。")

# --- モードB: 詳細チャート分析 ---
else:
    st.header("📈 詳細チャート分析")
    
    # 銘柄選択ボックス (リストから選べる)
    selected_ticker = st.selectbox("分析する銘柄を選択してください", ticker_list)
    
    if st.button("詳細分析実行", type="primary"):
        st.write(f"🔍 {selected_ticker} の詳細チャートを生成中...")
        
        try:
            # データ取得
            df = yf.download(selected_ticker, period=f"{period_days}d", interval="1h", auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df = df.dropna()

            if len(df) < 100:
                st.error("データ不足です。")
            else:
                # バックテスト
                bt = Backtest(df, HybridStrategy, cash=1000000, commission=0.001, exclusive_orders=True)
                stats = bt.run()
                
                # シグナル判定
                last_close = df['Close'].iloc[-1]
                last_signal = "様子見"
                trades = stats['_trades']
                if len(trades) > 0 and pd.isna(trades.iloc[-1]['ExitTime']):
                    last_signal = "🟢 買い保有中"

                # メトリクス表示
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("現在価格", f"¥{last_close:,.0f}")
                c2.metric("AI判定", last_signal)
                c3.metric("収益率", f"{stats['Return [%]']:.1f}%")
                c4.metric("PF", f"{stats['Profit Factor']:.2f}")
                
                # チャート描画準備
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
                
                # 日本語フォント適用
                my_style = mpf.make_mpf_style(base_mpf_style='yahoo', rc={'font.family': font_name})

                fig, axlist = mpf.plot(df_subset, type='candle', style=my_style, addplot=plots,
                         title=f"{selected_ticker} 詳細チャート", volume=True, figsize=(10, 8), 
                         panel_ratios=(6, 2, 2), returnfig=True)
                st.pyplot(fig)
                
                # 個別通知ボタン
                if gas_url:
                    if st.button("この結果をLINEに送る"):
                        flex = create_flex_message(
                            selected_ticker, last_close, last_signal, 
                            round(stats['Profit Factor'], 2), round(stats['Return [%]'], 2)
                        )
                        requests.post(gas_url, json={"mode":"push", "userId":line_user_id, "flexContents":flex})
                        st.success("送信しました！")

        except Exception as e:
            st.error(f"エラーが発生しました: {e}")
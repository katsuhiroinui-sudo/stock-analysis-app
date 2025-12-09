import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import mplfinance as mpf
import matplotlib.font_manager as fm
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import json
import os
import time
import streamlit.components.v1 as components

# バックテスト用ライブラリ
from backtesting import Backtest, Strategy
from backtesting.lib import crossover

# ==========================================
# 設定エリア
# ==========================================
SHEET_URL = os.getenv('SHEET_URL', '')
GCP_KEY_JSON = os.getenv('GCP_SERVICE_ACCOUNT_KEY', '')

# 日本語フォント設定
font_path = 'ipaexg.ttf'
try:
    fm.fontManager.addfont(font_path)
    font_prop = fm.FontProperties(fname=font_path)
    font_name = font_prop.get_name()
    pd.options.plotting.backend = 'matplotlib'
    import matplotlib.pyplot as plt
    plt.rc('font', family=font_name)
except Exception as e:
    font_name = "sans-serif"

# ==========================================
# 戦略クラスの定義 (Backtesting.py)
# ==========================================

# 1. SMAクロス戦略
class SmaCross(Strategy):
    n1 = 5
    n2 = 25
    
    def init(self):
        close = pd.Series(self.data.Close)
        self.sma1 = self.I(ta.sma, close, self.n1)
        self.sma2 = self.I(ta.sma, close, self.n2)
    
    def next(self):
        if crossover(self.sma1, self.sma2):
            self.buy()
        elif crossover(self.sma2, self.sma1):
            self.position.close()

# 2. RSI逆張り戦略
class RsiOscillator(Strategy):
    upper_bound = 70
    lower_bound = 30
    rsi_window = 14
    
    def init(self):
        close = pd.Series(self.data.Close)
        self.rsi = self.I(ta.rsi, close, self.rsi_window)
        
    def next(self):
        if crossover(self.rsi, self.lower_bound):
            self.buy()
        elif crossover(self.upper_bound, self.rsi):
            self.position.close()

# 3. MACDトレンド戦略
class MacdStrategy(Strategy):
    fast = 12
    slow = 26
    signal = 9
    
    def init(self):
        close = pd.Series(self.data.Close)
        # pandas_taのmacdはDataFrameを返すため、少し工夫が必要
        # ここでは簡易的にMACDラインとシグナルラインを計算して保持
        macd_df = ta.macd(close, fast=self.fast, slow=self.slow, signal=self.signal)
        # 列名: MACD_12_26_9, MACDs_12_26_9, MACDh_12_26_9
        self.macd = self.I(lambda x: macd_df.iloc[:, 0], close)   # MACD Line
        self.signal_line = self.I(lambda x: macd_df.iloc[:, 1], close) # Signal Line
        
    def next(self):
        if crossover(self.macd, self.signal_line):
            self.buy()
        elif crossover(self.signal_line, self.macd):
            self.position.close()

# 4. ボリンジャーバンド逆張り戦略
class BollingerBandsStrategy(Strategy):
    n = 20
    std = 2
    
    def init(self):
        close = pd.Series(self.data.Close)
        bb = ta.bbands(close, length=self.n, std=self.std)
        # BBL(下), BBM(中), BBU(上)
        self.lower = self.I(lambda x: bb.iloc[:, 0], close)
        self.upper = self.I(lambda x: bb.iloc[:, 2], close)
        
    def next(self):
        # 下バンドを下回ったら買い（逆張り）
        if self.data.Close < self.lower:
            if not self.position.is_long:
                self.buy()
        # 上バンドを超えたら手仕舞い
        elif self.data.Close > self.upper:
            self.position.close()

# 戦略マッピング
STRATEGIES = {
    "SMAクロス (トレンド)": SmaCross,
    "RSI (逆張り)": RsiOscillator,
    "MACD (トレンド)": MacdStrategy,
    "ボリンジャーバンド (逆張り)": BollingerBandsStrategy
}

# ==========================================
# スプレッドシート接続関数
# ==========================================
def get_sheet_client():
    if not GCP_KEY_JSON or not SHEET_URL:
        return None
    try:
        key_dict = json.loads(GCP_KEY_JSON)
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
        client = gspread.authorize(creds)
        return client.open_by_url(SHEET_URL)
    except Exception as e:
        st.error(f"スプレッドシート接続エラー: {e}")
        return None

# ==========================================
# UI & Main Logic
# ==========================================
st.set_page_config(page_title="AI株価監視盤", layout="wide")
st.title("📈 AI株価一括スキャン & 分析アプリ")

# --- サイドバー: 銘柄リスト管理 ---
st.sidebar.header("📝 銘柄リスト管理")
sheet = get_sheet_client()
df_sheet = pd.DataFrame()

if sheet:
    mode = st.sidebar.radio("編集モード", ["保有株 (Holdings)", "監視株 (Watchlist)"])
    ws_name = "Holdings" if "保有" in mode else "Watchlist"
    try:
        ws = sheet.worksheet(ws_name)
        data = ws.get_all_records()
        df_sheet = pd.DataFrame(data)
        if not df_sheet.empty:
            df_sheet = df_sheet.astype(str)
        st.sidebar.write(f"登録数: {len(df_sheet)}銘柄")
        
        with st.sidebar.expander("➕ 銘柄を追加", expanded=False):
            with st.form("add_form"):
                new_code = st.text_input("銘柄コード (数字4桁)")
                new_name = st.text_input("企業名")
                submitted = st.form_submit_button("追加する")
                if submitted and new_code and new_name:
                    clean_code = new_code.replace('.T', '').replace('.t', '').strip()
                    if not df_sheet.empty and clean_code in df_sheet['Ticker'].values:
                        st.sidebar.warning(f"{clean_code} は既に登録されています")
                    else:
                        ws.append_row([clean_code, new_name])
                        st.sidebar.success(f"{new_name} を追加しました！")
                        time.sleep(1)
                        st.rerun()
        
        with st.sidebar.expander("🗑️ 銘柄を削除", expanded=False):
            if not df_sheet.empty:
                st.sidebar.dataframe(df_sheet, use_container_width=True, hide_index=True)
                del_ticker = st.sidebar.selectbox("削除する銘柄を選択", df_sheet['Ticker'].tolist())
                if st.sidebar.button("削除実行"):
                    try:
                        cell = ws.find(del_ticker)
                        ws.delete_rows(cell.row)
                        st.sidebar.success("削除しました")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.sidebar.error(f"エラー: {e}")
            else:
                st.sidebar.info("登録なし")
    except Exception as e:
        st.sidebar.error(f"シート読み込みエラー: {e}")
else:
    st.sidebar.warning("⚠️ API設定なし")

# --- メインエリア: タブ切り替え ---
tab1, tab2 = st.tabs(["📊 チャート分析", "🧪 バックテスト研究所"])

# 銘柄選択（共通）
target_tickers = []
target_dict = {}
if not df_sheet.empty and 'Ticker' in df_sheet.columns:
    target_tickers = df_sheet['Ticker'].tolist()
    target_dict = dict(zip(df_sheet['Ticker'], df_sheet['Name']))
else:
    target_tickers = ["7203", "9984", "8306"]
    target_dict = {t: t for t in target_tickers}

# ==========================================
# Tab 1: 通常チャート分析
# ==========================================
with tab1:
    st.subheader("リアルタイム チャート分析")
    col1, col2 = st.columns([1, 1])
    with col1:
        selected_ticker = st.selectbox(
            "分析する銘柄", target_tickers, 
            format_func=lambda x: f"{x} : {target_dict.get(x, '')}", key="t1"
        )
    with col2:
        period = st.radio("期間", ["3mo", "6mo", "1y"], horizontal=True, index=1, key="p1")

    if st.button("チャート表示 🚀", key="btn1"):
        yf_code = str(selected_ticker).strip()
        if yf_code.isdigit(): yf_code = f"{yf_code}.T"

        with st.spinner('データ取得中...'):
            try:
                df = yf.download(yf_code, period=period, interval='1d', progress=False)
                if df.empty:
                    st.error("データなし")
                else:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)

                    df.ta.rsi(length=14, append=True)
                    df.ta.sma(length=5, append=True)
                    df.ta.sma(length=25, append=True)
                    df.ta.sma(length=75, append=True)
                    
                    latest = df.iloc[-1]
                    prev = df.iloc[-2]
                    
                    st.metric(
                        label=f"現在値 ({latest.name.strftime('%Y-%m-%d')})",
                        value=f"{int(latest['Close']):,} 円",
                        delta=f"{latest['Close'] - prev['Close']:.1f} 円"
                    )
                    
                    plots = [
                        mpf.make_addplot(df['SMA_5'], color='orange', width=1.0),
                        mpf.make_addplot(df['SMA_25'], color='skyblue', width=1.0),
                        mpf.make_addplot(df['SMA_75'], color='green', width=1.0),
                        mpf.make_addplot(df['RSI_14'], color='purple', panel=2, ylabel='RSI')
                    ]
                    my_style = mpf.make_mpf_style(base_mpf_style='yahoo', rc={'font.family': font_name})
                    fig, ax = mpf.plot(
                        df, type='candle', style=my_style, addplot=plots,
                        title=f"{selected_ticker} - {target_dict.get(selected_ticker, '')}",
                        volume=True, figsize=(10, 8), panel_ratios=(6, 2, 2), returnfig=True
                    )
                    st.pyplot(fig)
                    
                    rsi_val = latest['RSI_14']
                    if rsi_val < 30: st.success(f"🔵 RSI {rsi_val:.1f} (売られすぎ)")
                    elif rsi_val > 70: st.warning(f"🔴 RSI {rsi_val:.1f} (買われすぎ)")
                    else: st.info(f"RSI {rsi_val:.1f} (中立)")

            except Exception as e:
                st.error(f"エラー: {e}")

# ==========================================
# Tab 2: バックテスト研究所
# ==========================================
with tab2:
    st.subheader("🧪 戦略シミュレーション")
    st.info("過去のデータを使って、「もしそのルールで売買していたらどうなっていたか？」を検証します。")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        bt_ticker = st.selectbox(
            "検証する銘柄", target_tickers, 
            format_func=lambda x: f"{x} : {target_dict.get(x, '')}", key="t2"
        )
    with col2:
        strategy_name = st.selectbox("戦略を選択", list(STRATEGIES.keys()))
    with col3:
        cash = st.number_input("初期資金 (円)", value=1000000, step=100000)

    if st.button("バックテスト実行 ⚔️", key="btn2"):
        yf_code = str(bt_ticker).strip()
        if yf_code.isdigit(): yf_code = f"{yf_code}.T"
        
        with st.spinner('シミュレーション中...'):
            try:
                # バックテストは長期間で検証したほうが信頼性が高いので2年分取得
                df_bt = yf.download(yf_code, period="2y", interval='1d', progress=False)
                
                if isinstance(df_bt.columns, pd.MultiIndex):
                    df_bt.columns = df_bt.columns.get_level_values(0)
                
                # backtestingライブラリ用のカラム名チェック
                # Open, High, Low, Close, Volume が必要
                
                # 実行
                bt = Backtest(df_bt, STRATEGIES[strategy_name], cash=cash, commission=.002)
                stats = bt.run()
                
                # --- 結果表示 ---
                st.markdown("### 🏆 検証結果")
                
                # メトリクス表示
                m1, m2, m3, m4 = st.columns(4)
                win_rate = stats['Win Rate [%]']
                ret = stats['Return [%]']
                trades = stats['# Trades']
                pf = stats['Profit Factor']
                
                m1.metric("勝率", f"{win_rate:.1f}%")
                m2.metric("総収益率", f"{ret:.1f}%", delta_color="normal" if ret > 0 else "inverse")
                m3.metric("取引回数", f"{trades}回")
                m4.metric("プロフィットファクター", f"{pf:.2f}")
                
                st.markdown("---")
                
                # 詳細データ
                with st.expander("詳細データを見る"):
                    st.dataframe(stats.to_frame().T)
                
                # チャート表示 (HTML)
                st.markdown("### 📉 売買ポイントの確認")
                st.caption("▲: 買いエントリー / ▼: 売り/決済")
                
                # プロットをHTMLファイルとして保存し、読み込んで表示
                try:
                    bt.plot(filename='plot.html', open_browser=False)
                    with open('plot.html', 'r', encoding='utf-8') as f:
                        html_string = f.read()
                    components.html(html_string, height=600, scrolling=True)
                except Exception as plot_e:
                    st.warning(f"チャート描画エラー: {plot_e}")
                    st.write("※ 環境によってはインタラクティブチャートが表示できない場合があります。")

            except Exception as e:
                st.error(f"バックテストエラー: {e}")

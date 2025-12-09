import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import mplfinance as mpf
import matplotlib.font_manager as fm
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import os
import time
import streamlit.components.v1 as components

# バックテスト用ライブラリ (エラー回避)
try:
    from backtesting import Backtest, Strategy
    from backtesting.lib import crossover
except ImportError:
    st.error("ライブラリ 'backtesting' が見つかりません。")

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
except:
    font_name = "sans-serif"

# ==========================================
# 1. AI分析用 戦略クラス定義
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
STRATEGY_MAP = {s["name"]: s["class"] for s in STRATEGIES}

# ==========================================
# 2. 判定ロジック
# ==========================================
def check_current_signal(strategy_name, df):
    """最新データに基づいて売買シグナルを判定"""
    try:
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        close = float(latest['Close'])
        
        # 値取得ヘルパー
        def g(row, k, d=0): return float(row[k]) if k in row and not pd.isna(row[k]) else d

        # 指標値
        sma5, sma25 = g(latest,'SMA_5'), g(latest,'SMA_25')
        p_sma5, p_sma25 = g(prev,'SMA_5'), g(prev,'SMA_25')
        rsi = g(latest,'RSI_14', 50)
        macd, sig = g(latest,'MACD_12_26_9'), g(latest,'MACDs_12_26_9')
        p_macd, p_sig = g(prev,'MACD_12_26_9'), g(prev,'MACDs_12_26_9')
        bbl, bbu = g(latest,'BBL_20_2.0'), g(latest,'BBU_20_2.0')

        if strategy_name == "SMAクロス":
            if p_sma5 < p_sma25 and sma5 > sma25: return "買い 🚀", "ゴールデンクロス"
            elif p_sma5 > p_sma25 and sma5 < sma25: return "売り 🔻", "デッドクロス"
        elif strategy_name == "RSI逆張り":
            if rsi < 30: return "買い 🚀", f"売られすぎ(RSI{rsi:.0f})"
            elif rsi > 70: return "売り 🔻", f"買われすぎ(RSI{rsi:.0f})"
        elif strategy_name == "MACD":
            if p_macd < p_sig and macd > sig: return "買い 🚀", "MACD上抜け"
            elif p_macd > p_sig and macd < sig: return "売り 🔻", "MACD下抜け"
        elif strategy_name == "ボリンジャー":
            if close < bbl: return "買い 🚀", "バンド下限割れ"
            elif close > bbu: return "売り 🔻", "バンド上限到達"
            
        return "ステイ 🤔", "シグナルなし"
    except:
        return "判定不能", "データ不足"

# ==========================================
# 3. UI & メイン処理
# ==========================================
st.set_page_config(page_title="AI株価監視盤", layout="wide")
st.title("📈 AI株価一括スキャン & 分析アプリ")

# スプシ接続
def get_sheet_client():
    if not GCP_KEY_JSON or not SHEET_URL: return None
    try:
        key_dict = json.loads(GCP_KEY_JSON)
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
        client = gspread.authorize(creds)
        return client.open_by_url(SHEET_URL)
    except: return None

sheet = get_sheet_client()
df_sheet = pd.DataFrame()

# --- サイドバー ---
st.sidebar.header("📝 銘柄リスト管理")
if sheet:
    mode = st.sidebar.radio("編集モード", ["保有株 (Holdings)", "監視株 (Watchlist)"])
    ws_name = "Holdings" if "保有" in mode else "Watchlist"
    try:
        ws = sheet.worksheet(ws_name)
        data = ws.get_all_records()
        df_sheet = pd.DataFrame(data)
        if not df_sheet.empty: df_sheet = df_sheet.astype(str)
        st.sidebar.write(f"登録数: {len(df_sheet)}銘柄")
        
        with st.sidebar.expander("➕ 銘柄を追加"):
            with st.form("add"):
                c = st.text_input("コード(数字4桁)")
                n = st.text_input("企業名")
                if st.form_submit_button("追加"):
                    if c and n:
                        clean = c.replace('.T','').strip()
                        ws.append_row([clean, n])
                        st.success("追加しました")
                        time.sleep(1)
                        st.rerun()
        
        with st.sidebar.expander("🗑️ 削除"):
            if not df_sheet.empty:
                d = st.selectbox("削除銘柄", df_sheet['Ticker'].tolist())
                if st.button("削除"):
                    cell = ws.find(d)
                    ws.delete_rows(cell.row)
                    st.success("削除しました")
                    time.sleep(1)
                    st.rerun()
    except Exception as e:
        st.sidebar.error(f"読み込みエラー: {e}")
else:
    st.sidebar.warning("API設定なし (GitHub Secretsを確認してください)")

# --- メインエリア ---
tab1, tab2, tab3 = st.tabs(["📊 チャート分析", "🧪 バックテスト研究所", "🤖 AI戦略コンシェルジュ"])

# 銘柄リスト準備
target_tickers = []
target_dict = {}
if not df_sheet.empty and 'Ticker' in df_sheet.columns:
    target_tickers = df_sheet['Ticker'].tolist()
    target_dict = dict(zip(df_sheet['Ticker'], df_sheet['Name']))
else:
    # デフォルト (APIなし用)
    target_tickers = ["7203", "9984", "8306"]
    target_dict = {t: t for t in target_tickers}

# ----------------------------------------------------
# Tab 1: チャート分析
# ----------------------------------------------------
with tab1:
    st.subheader("リアルタイム チャート")
    c1, c2 = st.columns(2)
    t1 = c1.selectbox("銘柄", target_tickers, format_func=lambda x: f"{x} : {target_dict.get(x,'')}", key="t1")
    p1 = c2.radio("期間", ["3mo", "6mo", "1y"], index=1, horizontal=True, key="p1")
    
    if st.button("チャート表示 🚀", key="b1"):
        yf_code = f"{t1}.T" if str(t1).isdigit() else t1
        with st.spinner('取得中...'):
            try:
                df = yf.download(yf_code, period=p1, interval='1d', progress=False)
                if df.empty:
                    st.error("データなし")
                else:
                    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                    
                    # 指標計算
                    df.ta.sma(length=5, append=True)
                    df.ta.sma(length=25, append=True)
                    df.ta.sma(length=75, append=True)
                    df.ta.rsi(length=14, append=True)
                    
                    latest = df.iloc[-1]
                    st.metric("現在値", f"{int(latest['Close']):,} 円", f"{latest['Close']-df.iloc[-2]['Close']:.1f}")
                    
                    plots = [
                        mpf.make_addplot(df['SMA_5'], color='orange', width=1),
                        mpf.make_addplot(df['SMA_25'], color='skyblue', width=1),
                        mpf.make_addplot(df['SMA_75'], color='green', width=1),
                        mpf.make_addplot(df['RSI_14'], color='purple', panel=2, ylabel='RSI')
                    ]
                    my_style = mpf.make_mpf_style(base_mpf_style='yahoo', rc={'font.family': font_name})
                    fig, ax = mpf.plot(df, type='candle', style=my_style, addplot=plots, volume=True, returnfig=True,
                                   title=f"{t1} - {target_dict.get(t1,'')}", figsize=(10,8))
                    st.pyplot(fig)
            except Exception as e:
                st.error(f"エラー: {e}")

# ----------------------------------------------------
# Tab 2: バックテスト研究所
# ----------------------------------------------------
with tab2:
    st.subheader("戦略シミュレーション")
    st.info("過去2年間のデータで売買ルールを検証します。")
    
    c1, c2, c3 = st.columns(3)
    t2 = c1.selectbox("銘柄", target_tickers, format_func=lambda x: f"{x} : {target_dict.get(x,'')}", key="t2")
    s2 = c2.selectbox("戦略", list(STRATEGY_MAP.keys()), key="s2")
    cash = c3.number_input("初期資金(円)", value=1000000, step=100000)
    
    if st.button("検証実行 ⚔️", key="b2"):
        yf_code = f"{t2}.T" if str(t2).isdigit() else t2
        with st.spinner('シミュレーション中...'):
            try:
                df = yf.download(yf_code, period="2y", interval='1d', progress=False)
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                
                bt = Backtest(df, STRATEGY_MAP[s2], cash=cash, commission=.002)
                stats = bt.run()
                
                # --- 結果表示 (アップデート部分) ---
                final_equity = stats['Equity Final [$]']
                profit = final_equity - cash
                buy_hold = stats['Buy & Hold Return [%]']
                
                st.markdown(f"### 💰 最終資産: **{int(final_equity):,}円**")
                
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("収支", f"{int(profit):,}円", delta="プラス" if profit > 0 else "マイナス")
                c2.metric("総収益率", f"{stats['Return [%]']:.1f}%")
                c3.metric("勝率", f"{stats['Win Rate [%]']:.1f}%")
                c4.metric("ガチホ収益率", f"{buy_hold:.1f}%", help="何もせず持ち続けた場合の収益率")
                
                st.write("##### 📈 資産の推移")
                # 資産曲線の表示
                equity_curve = stats['_equity_curve']
                st.line_chart(equity_curve['Equity'])
                
                with st.expander("詳細データ"): st.dataframe(stats.to_frame().T)
                
                try:
                    bt.plot(filename='plot.html', open_browser=False)
                    with open('plot.html', 'r', encoding='utf-8') as f:
                        components.html(f.read(), height=600, scrolling=True)
                except Exception as pe:
                    st.warning(f"チャート描画エラー: {pe}")
                    
            except Exception as e:
                st.error(f"検証エラー: {e}")

# ----------------------------------------------------
# Tab 3: AI戦略コンシェルジュ
# ----------------------------------------------------
with tab3:
    st.subheader("🤖 AI戦略コンシェルジュ")
    st.info("過去2年間のデータを元に、最も勝率の高い戦略で現在の売買判断を行います。")
    
    t3 = st.selectbox("診断する銘柄", target_tickers, format_func=lambda x: f"{x} : {target_dict.get(x,'')}", key="t3")
    
    if st.button("AI診断を開始 🧠", key="b3"):
        yf_code = f"{t3}.T" if str(t3).isdigit() else t3
        
        with st.spinner("AIが思考中... 全戦略のバックテストを実行しています..."):
            try:
                df = yf.download(yf_code, period="2y", interval='1d', progress=False)
                if df.empty:
                    st.error("データなし")
                    st.stop()
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                
                # 指標一括計算
                df.ta.sma(length=5, append=True)
                df.ta.sma(length=25, append=True)
                df.ta.rsi(length=14, append=True)
                df.ta.macd(fast=12, slow=26, signal=9, append=True)
                df.ta.bbands(length=20, std=2, append=True)
                
                results = []
                progress = st.progress(0)
                
                for i, strat in enumerate(STRATEGIES):
                    try:
                        bt = Backtest(df, strat["class"], cash=1000000, commission=.002)
                        stats = bt.run()
                        action, reason = check_current_signal(strat["name"], df)
                        
                        results.append({
                            "戦略名": strat["name"],
                            "勝率": stats['Win Rate [%]'],
                            "収益率": stats['Return [%]'],
                            "PF": stats['Profit Factor'],
                            "現在の判定": action,
                            "根拠": reason
                        })
                    except:
                        pass
                    progress.progress((i + 1) / len(STRATEGIES))
                
                if not results:
                    st.error("有効な戦略が見つかりませんでした。")
                else:
                    res_df = pd.DataFrame(results)
                    res_df = res_df.sort_values("勝率", ascending=False).reset_index(drop=True)
                    best = res_df.iloc[0]
                    
                    st.success("診断完了！")
                    st.markdown(f"### 👑 AIの結論: 【{best['現在の判定']}】")
                    st.write(f"推奨戦略: **{best['戦略名']}** (勝率 {best['勝率']:.1f}%)")
                    st.write(f"根拠: {best['根拠']}")
                    
                    st.markdown("#### 📊 戦略パフォーマンス比較")
                    st.dataframe(res_df.style.format({"勝率": "{:.1f}%", "収益率": "{:.1f}%", "PF": "{:.2f}"}))
                
            except Exception as e:
                st.error(f"診断エラー: {e}")

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

# ==========================================
# 設定エリア
# ==========================================
# GitHub Secrets等で設定された環境変数を読み込みます
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
# スプレッドシート接続関数
# ==========================================
def get_sheet_client():
    """Google Sheets APIに接続してクライアントを返す"""
    if not GCP_KEY_JSON or not SHEET_URL:
        return None
    try:
        # JSON文字列を辞書に変換
        key_dict = json.loads(GCP_KEY_JSON)
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
        client = gspread.authorize(creds)
        # スプレッドシートを開く
        return client.open_by_url(SHEET_URL)
    except Exception as e:
        st.error(f"スプレッドシート接続エラー: {e}")
        return None

# ==========================================
# メインアプリ
# ==========================================
st.set_page_config(page_title="AI株価監視盤", layout="wide")
st.title("📈 AI株価一括スキャン & 管理アプリ")

# ------------------------------------------
# 1. サイドバー: 銘柄リスト管理機能
# ------------------------------------------
st.sidebar.header("📝 銘柄リスト管理")

sheet = get_sheet_client()
df_sheet = pd.DataFrame()

if sheet:
    # 編集対象のシートを選択
    mode = st.sidebar.radio("編集モード", ["保有株 (Holdings)", "監視株 (Watchlist)"])
    ws_name = "Holdings" if "保有" in mode else "Watchlist"
    
    try:
        ws = sheet.worksheet(ws_name)
        # 全データを取得してDataFrame化
        data = ws.get_all_records()
        df_sheet = pd.DataFrame(data)
        
        # 文字列型に統一（エラー回避）
        if not df_sheet.empty:
            df_sheet = df_sheet.astype(str)
        
        st.sidebar.write(f"登録数: {len(df_sheet)}銘柄")
        
        # --- 新規追加フォーム ---
        with st.sidebar.expander("➕ 銘柄を追加", expanded=False):
            with st.form("add_form"):
                new_code = st.text_input("銘柄コード (数字4桁)")
                new_name = st.text_input("企業名")
                submitted = st.form_submit_button("追加する")
                
                if submitted:
                    if new_code and new_name:
                        # 【修正】 .T があれば削除して保存
                        clean_code = new_code.replace('.T', '').replace('.t', '').strip()
                        
                        # 重複チェック（現在表示中のリストに対して）
                        if not df_sheet.empty and clean_code in df_sheet['Ticker'].values:
                            st.sidebar.warning(f"{clean_code} は既に登録されています")
                        else:
                            ws.append_row([clean_code, new_name])
                            st.sidebar.success(f"{new_name} ({clean_code}) を追加しました！")
                            time.sleep(1) # 反映待ち
                            st.rerun()
                    else:
                        st.sidebar.error("コードと企業名を入力してください")
        
        # --- 削除機能 ---
        with st.sidebar.expander("🗑️ 銘柄を削除", expanded=False):
            if not df_sheet.empty:
                # リスト表示
                st.sidebar.dataframe(df_sheet, use_container_width=True, hide_index=True)
                
                # 削除選択
                del_ticker = st.sidebar.selectbox("削除する銘柄を選択", df_sheet['Ticker'].tolist())
                
                if st.sidebar.button("削除実行"):
                    try:
                        cell = ws.find(del_ticker)
                        ws.delete_rows(cell.row)
                        st.sidebar.success(f"{del_ticker} を削除しました")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.sidebar.error(f"削除エラー: {e}")
            else:
                st.sidebar.info("登録されている銘柄はありません")
                
    except Exception as e:
        st.sidebar.error(f"シート読み込みエラー: {e}")
        st.sidebar.info("※ スプレッドシートに 'Holdings' と 'Watchlist' という名前のシートがあるか確認してください。")

else:
    # API設定がない場合のダミー表示（エラーにはしない）
    st.sidebar.warning("⚠️ Google Sheets API設定が見つかりません")
    st.sidebar.info("ローカル実行の場合、.envファイルなどで環境変数を設定してください。")

# ------------------------------------------
# 2. メイン画面: チャート分析機能
# ------------------------------------------
st.header("📊 即時チャート分析")

# 分析対象の選択（スプシのデータがあればそれを使う）
target_tickers = []
target_dict = {}

if not df_sheet.empty and 'Ticker' in df_sheet.columns:
    target_tickers = df_sheet['Ticker'].tolist()
    # コード: 名称 の辞書作成
    target_dict = dict(zip(df_sheet['Ticker'], df_sheet['Name']))
else:
    # データがない場合はデフォルトリスト（数字のみ）
    target_tickers = ["7203", "9984", "8306"]
    target_dict = {t: t for t in target_tickers}

# セレクトボックス（企業名も表示）
selected_ticker = st.selectbox(
    "分析する銘柄を選択してください", 
    target_tickers,
    format_func=lambda x: f"{x} : {target_dict.get(x, '')}"
)

# 期間選択
period = st.radio("期間", ["3mo", "6mo", "1y"], horizontal=True, index=1)

if st.button("分析開始 🚀"):
    # 【修正】 .T を自動付与してデータ取得
    yf_code = str(selected_ticker).strip()
    if yf_code.isdigit():
        yf_code = f"{yf_code}.T"

    with st.spinner(f'{yf_code} のデータを取得中...'):
        try:
            # データ取得
            df = yf.download(yf_code, period=period, interval='1d', progress=False)
            
            if df.empty:
                st.error("データが取得できませんでした。コードが正しいか確認してください。")
            else:
                # MultiIndex対応
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                # テクニカル指標追加
                df.ta.rsi(length=14, append=True)
                df.ta.sma(length=5, append=True)
                df.ta.sma(length=25, append=True)
                df.ta.sma(length=75, append=True)
                
                # 直近データ表示
                latest = df.iloc[-1]
                prev = df.iloc[-2]
                
                st.metric(
                    label=f"現在値 ({latest.name.strftime('%Y-%m-%d')})",
                    value=f"{int(latest['Close']):,} 円",
                    delta=f"{latest['Close'] - prev['Close']:.1f} 円"
                )
                
                # チャート描画 (mplfinance)
                # グラフ設定
                plots = [
                    mpf.make_addplot(df['SMA_5'], color='orange', width=1.0, panel=0),
                    mpf.make_addplot(df['SMA_25'], color='skyblue', width=1.0, panel=0),
                    mpf.make_addplot(df['SMA_75'], color='green', width=1.0, panel=0),
                    mpf.make_addplot(df['RSI_14'], color='purple', panel=2, ylabel='RSI')
                ]
                
                # スタイル設定
                my_style = mpf.make_mpf_style(
                    base_mpf_style='yahoo', 
                    rc={'font.family': font_name}
                )
                
                fig, axlist = mpf.plot(
                    df, 
                    type='candle', 
                    style=my_style, 
                    addplot=plots,
                    title=f"{selected_ticker} - {target_dict.get(selected_ticker, '')}",
                    volume=True, 
                    figsize=(10, 8), 
                    panel_ratios=(6, 2, 2), 
                    returnfig=True
                )
                st.pyplot(fig)
                
                # 簡易シグナル表示
                rsi_val = latest['RSI_14']
                if rsi_val < 30:
                    st.success(f"🔵 RSIが {rsi_val:.1f} です。売られすぎ水準です。")
                elif rsi_val > 70:
                    st.warning(f"🔴 RSIが {rsi_val:.1f} です。買われすぎ水準です。")
                else:
                    st.info(f"RSIは {rsi_val:.1f} (中立) です。")

        except Exception as e:
            st.error(f"エラーが発生しました: {e}")

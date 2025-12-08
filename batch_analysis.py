import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import datetime
import json
import sys
import math

# ==========================================
# 監視銘柄リスト
# ==========================================
TICKERS = [
    "7453.T", "7203.T", "8306.T", "9984.T", "7011.T", 
    "8136.T", "6752.T", "6501.T", "6758.T", "7267.T"
]

def clean_value(val):
    """NaNをNoneに変換してJSON準拠にする"""
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val

def get_ticker_data(ticker):
    """銘柄データを取得し、辞書形式で返す"""
    try:
        # 過去6ヶ月分のデータを取得
        df = yf.download(ticker, period="6mo", interval="1d", progress=False)
        
        if df.empty:
            return None

        # 指標計算
        df.ta.rsi(length=14, append=True)
        df.ta.sma(length=5, append=True)
        df.ta.sma(length=25, append=True)
        
        # 最新・前日データ
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 値の抽出（float変換 + NaN対策）
        close = clean_value(float(latest['Close']))
        rsi = clean_value(float(latest['RSI_14']))
        sma5 = clean_value(float(latest['SMA_5']))
        sma25 = clean_value(float(latest['SMA_25']))
        
        prev_sma5 = clean_value(float(prev['SMA_5']))
        prev_sma25 = clean_value(float(prev['SMA_25']))
        
        # データがNoneなら計算できないのでスキップ等の処理も可能だが
        # ここでは安全に比較できるよう 0 扱いにしてシグナル判定を行うか、
        # 判定自体をスキップする実装にする。
        # (簡易的に値がある場合のみ判定へ進む)
        
        signals = []
        signal_color = "#555555" # デフォルト文字色(グレー)

        # 全ての指標が揃っている場合のみ判定
        if all(v is not None for v in [rsi, sma5, sma25, prev_sma5, prev_sma25]):
            # RSI判定
            if rsi < 30:
                signals.append("🔵 売られすぎ")
                signal_color = "#0000ff" # 青
            elif rsi > 70:
                signals.append("🔴 買われすぎ")
                signal_color = "#ff0000" # 赤
                
            # ゴールデンクロス/デッドクロス
            if prev_sma5 < prev_sma25 and sma5 > sma25:
                signals.append("📈 Gクロス(買)")
                signal_color = "#ff0000" # 赤(強調)
            elif prev_sma5 > prev_sma25 and sma5 < sma25:
                signals.append("📉 Dクロス(売)")
                signal_color = "#0000ff" # 青
        
        return {
            "ticker": ticker,
            "close": close if close is not None else 0,
            "rsi": rsi if rsi is not None else 0,
            "sma5": sma5 if sma5 is not None else 0,
            "sma25": sma25 if sma25 is not None else 0,
            "signals": signals,
            "signal_color": signal_color
        }

    except Exception as e:
        # エラー時は標準エラー出力に出し、データはNoneを返す
        print(f"[ERROR] {ticker}: {e}", file=sys.stderr)
        return None

def create_flex_message(results):
    """分析結果リストからLINE Flex Message(Bubble)を生成する"""
    
    # ヘッダー部分
    current_date = datetime.now().strftime('%m/%d')
    contents = [
        {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "株価分析レポート",
                    "weight": "bold",
                    "color": "#1DB446",
                    "size": "sm"
                },
                {
                    "type": "text",
                    "text": f"{current_date} 定期実行",
                    "weight": "bold",
                    "size": "xl",
                    "margin": "md"
                },
                {
                    "type": "separator",
                    "margin": "xxl"
                }
            ]
        }
    ]

    # 各銘柄の行を追加
    for data in results:
        # 銘柄名と価格
        row_ticker = {
            "type": "box",
            "layout": "baseline",
            "margin": "md",
            "contents": [
                {
                    "type": "text",
                    "text": data['ticker'],
                    "weight": "bold",
                    "size": "md",
                    "flex": 1
                },
                {
                    "type": "text",
                    "text": f"{data['close']:,.0f}円", 
                    "weight": "bold",
                    "size": "md",
                    "align": "end",
                    "flex": 0
                }
            ]
        }
        
        # 指標データ (RSI, SMA)
        row_indicators = {
            "type": "box",
            "layout": "baseline",
            "margin": "xs",
            "contents": [
                {
                    "type": "text",
                    "text": f"RSI:{data['rsi']:.1f} | S5:{data['sma5']:.0f}/S25:{data['sma25']:.0f}",
                    "size": "xs",
                    "color": "#aaaaaa",
                    "flex": 1
                }
            ]
        }
        
        contents.append(row_ticker)
        contents.append(row_indicators)

        # シグナルがあれば表示
        if data['signals']:
            signal_text = " / ".join(data['signals'])
            row_signal = {
                "type": "text",
                "text": f"⚡ {signal_text}",
                "size": "xs",
                "color": data['signal_color'],
                "margin": "xs",
                "wrap": True
            }
            contents.append(row_signal)

        # 区切り線
        contents.append({"type": "separator", "margin": "md"})

    # フッター
    contents.append({
        "type": "box",
        "layout": "vertical",
        "margin": "md",
        "contents": [
            {
                "type": "text",
                "text": "GitHub Actions Auto Analysis",
                "size": "xxs",
                "color": "#cccccc",
                "align": "center"
            }
        ]
    })

    # Flex Messageのコンテナ
    flex_bubble = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": contents
        }
    }
    
    return flex_bubble

def main():
    results = []
    for ticker in TICKERS:
        data = get_ticker_data(ticker)
        if data:
            results.append(data)
            
    if results:
        # Flex MessageのJSON構造を作成
        flex_payload = create_flex_message(results)
        # JSONとして標準出力する（これをnotify.pyが受け取る）
        print(json.dumps(flex_payload, ensure_ascii=False))
    else:
        # データが取れなかった場合はエラーログへ
        print("データ取得に失敗しました。", file=sys.stderr)

if __name__ == "__main__":
    main()
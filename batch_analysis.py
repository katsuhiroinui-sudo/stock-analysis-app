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

def safe_float(val):
    """
    あらゆる型(numpy, series, str等)から安全にPythonのfloatを取り出す
    失敗した場合は None を返す
    """
    try:
        # Pandas SeriesやNumpy配列の場合、単一の値を取り出す
        if hasattr(val, 'item'):
            val = val.item()
        
        # float変換
        f_val = float(val)
        
        # NaNや無限大のチェック
        if math.isnan(f_val) or math.isinf(f_val):
            return None
            
        return f_val
    except Exception:
        return None

def get_ticker_data(ticker):
    """銘柄データを取得し、辞書形式で返す"""
    try:
        # データの取得（進行状況非表示）
        df = yf.download(ticker, period="6mo", interval="1d", progress=False)
        
        if df.empty or len(df) < 25: # SMA25計算のために最低限の行数が必要
            return None

        # 指標計算
        df.ta.rsi(length=14, append=True)
        df.ta.sma(length=5, append=True)
        df.ta.sma(length=25, append=True)
        
        # 最新・前日データ（ilocで確実に行を取得）
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 値の抽出（safe_floatで厳密に変換）
        # ※yfinanceのバージョンによってはカラムがMultiIndexになる場合があるため
        # カラム名指定ではなく、位置や属性でのアクセスを試みるのが安全だが、
        # ここではライブラリの標準的な挙動に合わせて値を取得する。
        
        # 終値の取得トライ
        try:
            close_val = latest['Close']
        except KeyError:
            # カラム構造が異なる場合のフォールバック（最初のカラムをCloseと仮定など）
            close_val = latest.iloc[0] 

        close = safe_float(close_val)
        rsi = safe_float(latest.get('RSI_14'))
        sma5 = safe_float(latest.get('SMA_5'))
        sma25 = safe_float(latest.get('SMA_25'))
        
        prev_sma5 = safe_float(prev.get('SMA_5'))
        prev_sma25 = safe_float(prev.get('SMA_25'))
        
        # 必須データ（終値）がない場合はスキップ
        if close is None:
            return None

        # --- シグナル判定 ---
        signals = []
        signal_color = "#555555"

        # 指標が揃っている場合のみ判定
        if all(v is not None for v in [rsi, sma5, sma25, prev_sma5, prev_sma25]):
            if rsi < 30:
                signals.append("🔵 売られすぎ")
                signal_color = "#0000ff"
            elif rsi > 70:
                signals.append("🔴 買われすぎ")
                signal_color = "#ff0000"
                
            if prev_sma5 < prev_sma25 and sma5 > sma25:
                signals.append("📈 Gクロス(買)")
                signal_color = "#ff0000"
            elif prev_sma5 > prev_sma25 and sma5 < sma25:
                signals.append("📉 Dクロス(売)")
                signal_color = "#0000ff"
        
        return {
            "ticker": ticker,
            "close": close,
            "rsi": rsi if rsi is not None else 0,
            "sma5": sma5 if sma5 is not None else 0,
            "sma25": sma25 if sma25 is not None else 0,
            "signals": signals,
            "signal_color": signal_color
        }

    except Exception as e:
        print(f"[ERROR] {ticker}: {e}", file=sys.stderr)
        return None

def create_flex_message(results):
    """分析結果リストからLINE Flex Message(Bubble)を生成する"""
    
    current_date = datetime.now().strftime('%m/%d')
    
    # ベースのコンテナ
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

    for data in results:
        # 株価表示テキストの生成
        try:
            price_text = f"{data['close']:,.0f}円"
        except Exception:
            price_text = "---円"

        # 銘柄行
        row_ticker = {
            "type": "box",
            "layout": "baseline",
            "margin": "md",
            "contents": [
                {
                    "type": "text",
                    "text": str(data['ticker']),
                    "weight": "bold",
                    "size": "md",
                    "flex": 1
                },
                {
                    "type": "text",
                    "text": price_text,
                    "weight": "bold",
                    "size": "md",
                    "align": "end",
                    "flex": 0
                }
            ]
        }
        
        # 指標行
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

        # シグナル行
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

    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": contents
        }
    }

def main():
    results = []
    for ticker in TICKERS:
        data = get_ticker_data(ticker)
        if data:
            results.append(data)
            
    if results:
        flex_payload = create_flex_message(results)
        
        # 【重要】デバッグ用に生成したJSONを標準エラー出力に吐き出す
        # これで通知失敗時もログで送信内容を確認できる
        print(f"[DEBUG] Generated JSON Payload:", file=sys.stderr)
        print(json.dumps(flex_payload, ensure_ascii=False, indent=2), file=sys.stderr)
        
        # notify.py への渡し
        print(json.dumps(flex_payload, ensure_ascii=False))
    else:
        print("データ取得に失敗、または有効なデータがありませんでした。", file=sys.stderr)

if __name__ == "__main__":
    main()
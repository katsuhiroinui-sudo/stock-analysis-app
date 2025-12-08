import requests
import os
import sys
import argparse
import json
from datetime import datetime

# ==========================================
# 設定エリア
# ==========================================
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN', '') 
MY_USER_ID = os.getenv('MY_USER_ID', '')
# 予備・他ツール設定
LINE_NOTIFY_TOKEN = os.getenv('LINE_NOTIFY_TOKEN', '') 
SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL', '')
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '')

def send_line_messaging_api(content, token, user_id):
    """
    LINE Messaging APIを使用して送信
    contentが辞書型ならFlex Message、文字列ならText Messageとして送信
    """
    if not token or not user_id:
        return False

    api_url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}'
    }
    
    # メッセージペイロードの構築
    messages = []
    
    if isinstance(content, dict) and content.get("type") == "bubble":
        # Flex Message (Bubble) の場合
        messages.append({
            "type": "flex",
            "altText": "株価分析レポートが届きました",
            "contents": content
        })
        print("[INFO] 送信モード: Flex Message")
    else:
        # 通常のテキストメッセージの場合
        text_content = str(content)
        messages.append({
            'type': 'text',
            'text': text_content
        })
        print("[INFO] 送信モード: Text Message")

    payload = {
        'to': user_id,
        'messages': messages
    }

    try:
        response = requests.post(api_url, headers=headers, data=json.dumps(payload), timeout=10)
        response.raise_for_status()
        print(f"[INFO] LINE Messaging API送信成功: {response.status_code}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] LINE Messaging API送信失敗: {e}")
        if e.response is not None:
             print(f"       Response: {e.response.text}")
        return False

def send_fallback_notify(message, title="通知"):
    """LINE Notify / Slack / Discord へのフォールバック送信（テキストのみ）"""
    # Flex MessageのJSONが渡された場合、中身をダンプして文字列にする
    if isinstance(message, dict):
        text_msg = "【Flex Message用のデータが生成されましたが、このツールでは表示できません】"
    else:
        text_msg = str(message)
        
    full_message = f"[{datetime.now().strftime('%H:%M')}] {title}\n{text_msg}"

    # LINE Notify
    if LINE_NOTIFY_TOKEN:
        try:
            requests.post(
                'https://notify-api.line.me/api/notify',
                headers={'Authorization': f'Bearer {LINE_NOTIFY_TOKEN}'},
                data={'message': full_message}
            )
            print("[INFO] LINE Notify送信成功")
        except Exception:
            pass

    # Slack (簡易実装)
    if SLACK_WEBHOOK_URL:
        try:
            requests.post(
                SLACK_WEBHOOK_URL,
                json={"text": full_message}
            )
            print("[INFO] Slack送信成功")
        except Exception:
            pass

def main():
    parser = argparse.ArgumentParser(description='通知送信スクリプト')
    parser.add_argument('message', type=str, nargs='?', help='送信メッセージ')
    parser.add_argument('--title', type=str, default='Notify', help='タイトル')
    args = parser.parse_args()
    
    # 入力データの取得
    input_data = args.message
    
    # パイプ入力の確認
    if not input_data and not sys.stdin.isatty():
        try:
            raw_input = sys.stdin.read().strip()
            if raw_input:
                # JSONとしてパースを試みる (Flex Message判定)
                try:
                    input_data = json.loads(raw_input)
                except json.JSONDecodeError:
                    # JSONでなければそのままテキストとして扱う
                    input_data = raw_input
        except Exception as e:
            print(f"[WARN] 入力読み込みエラー: {e}")

    if not input_data:
        print("[WARN] 送信データがありません")
        return

    # メイン送信処理 (LINE Messaging API優先)
    if CHANNEL_ACCESS_TOKEN and MY_USER_ID:
        send_line_messaging_api(input_data, CHANNEL_ACCESS_TOKEN, MY_USER_ID)
    else:
        # トークンがない場合は他の手段へ
        send_fallback_notify(input_data, title=args.title)

if __name__ == "__main__":
    main()
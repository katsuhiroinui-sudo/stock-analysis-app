import requests
import os
import sys
import argparse
import json
from datetime import datetime

"""
notify.py - 通知送信ユーティリティ

修正内容:
    - GASのスクリプトプロパティに合わせて、LINE Messaging API (CHANNEL_ACCESS_TOKEN, MY_USER_ID) に対応しました。
    - 従来の LINE Notify も引き続き利用可能です。

使用方法:
    環境変数に以下のいずれかを設定して実行してください。
    
    [パターンA: LINE Messaging API (GASと同じ設定)]
      - CHANNEL_ACCESS_TOKEN
      - MY_USER_ID
    
    [パターンB: LINE Notify]
      - LINE_NOTIFY_TOKEN
"""

# ==========================================
# 【設定エリア】
# 環境変数から設定を読み込みます
# ==========================================

# 1. LINE Messaging API設定 (GAS互換)
#    Messaging APIのチャネルアクセストークンと送信先ユーザーID
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN', '')
MY_USER_ID = os.getenv('MY_USER_ID', '')

# 2. LINE Notify設定 (予備)
LINE_NOTIFY_TOKEN = os.getenv('LINE_NOTIFY_TOKEN', '') 

# 3. Slack / Discord設定
SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL', '')
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '')

# ==========================================

def send_line_messaging_api(message, token, user_id):
    """LINE Messaging API (Push Message) を使用して送信"""
    if not token or not user_id:
        return

    api_url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}'
    }
    payload = {
        'to': user_id,
        'messages': [
            {
                'type': 'text',
                'text': message
            }
        ]
    }

    try:
        response = requests.post(api_url, headers=headers, data=json.dumps(payload), timeout=10)
        response.raise_for_status()
        print(f"[INFO] LINE Messaging API送信成功: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] LINE Messaging API送信失敗: {e}")
        if e.response is not None:
             print(f"       Status: {e.response.status_code}, Response: {e.response.text}")

def send_line_notify(message, token):
    """LINE Notify APIを使用して送信"""
    if not token:
        return
    
    api_url = 'https://notify-api.line.me/api/notify'
    headers = {'Authorization': f'Bearer {token}'}
    data = {'message': f'\n{message}'}
    
    try:
        response = requests.post(api_url, headers=headers, data=data, timeout=10)
        response.raise_for_status()
        print(f"[INFO] LINE Notify送信成功: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] LINE Notify送信失敗: {e}")

def send_slack_notify(message, webhook_url, title=None):
    """Slack Webhookを使用して送信"""
    if not webhook_url:
        return

    payload = {"text": message}
    if title:
        payload["blocks"] = [
            {"type": "header", "text": {"type": "plain_text", "text": title}},
            {"type": "section", "text": {"type": "mrkdwn", "text": message}}
        ]

    try:
        response = requests.post(
            webhook_url, 
            data=json.dumps(payload),
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        response.raise_for_status()
        print(f"[INFO] Slack送信成功: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Slack送信失敗: {e}")

def send_discord_notify(message, webhook_url, title=None):
    """Discord Webhookを使用して送信"""
    if not webhook_url:
        return

    content = message
    if title:
        content = f"**{title}**\n{message}"

    payload = {"content": content}

    try:
        response = requests.post(
            webhook_url,
            data=json.dumps(payload),
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        response.raise_for_status()
        print(f"[INFO] Discord送信成功: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Discord送信失敗: {e}")

def send_notification(message, title="通知"):
    """設定されている全ての通知手段でメッセージを送信する"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    full_message = f"[{timestamp}] {message}"
    
    print("-" * 30)
    print(f"通知処理開始: {title}")
    
    notify_sent = False

    # 1. LINE Messaging API (優先)
    if CHANNEL_ACCESS_TOKEN and MY_USER_ID:
        send_line_messaging_api(full_message, CHANNEL_ACCESS_TOKEN, MY_USER_ID)
        notify_sent = True
    
    # 2. LINE Notify (予備)
    if LINE_NOTIFY_TOKEN:
        send_line_notify(full_message, LINE_NOTIFY_TOKEN)
        notify_sent = True
    
    # 3. Slack
    if SLACK_WEBHOOK_URL:
        send_slack_notify(full_message, SLACK_WEBHOOK_URL, title)
        notify_sent = True

    # 4. Discord
    if DISCORD_WEBHOOK_URL:
        send_discord_notify(full_message, DISCORD_WEBHOOK_URL, title)
        notify_sent = True
        
    if not notify_sent:
        print("[WARN] 通知設定が見つかりません。")
        print("       以下のいずれかの環境変数を設定してください:")
        print("       - CHANNEL_ACCESS_TOKEN と MY_USER_ID (LINE Messaging API)")
        print("       - LINE_NOTIFY_TOKEN (LINE Notify)")
        print("       - SLACK_WEBHOOK_URL")
        print("       - DISCORD_WEBHOOK_URL")
        print(f"       メッセージ内容: {full_message}")
        
    print("-" * 30)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='各チャットツールへ通知を送信します')
    parser.add_argument('message', type=str, nargs='?', default='(メッセージなし)', help='送信するメッセージ内容')
    parser.add_argument('--title', type=str, default='Notify Script', help='通知のタイトル')
    
    args = parser.parse_args()
    
    send_notification(args.message, args.title)
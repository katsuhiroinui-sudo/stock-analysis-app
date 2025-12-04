import requests
import os
import sys
import argparse
import json
from datetime import datetime

"""
notify.py - 通知送信ユーティリティ

使用方法:
    1. 必要なライブラリをインストール: pip install requests
    2. トークン/Webhook URLを設定 (環境変数 または コード内の定数を書き換え)
    3. 実行: 
       python notify.py "こんにちは" --title "テスト通知"
       
       # 引数なしでも実行可能になりました（デフォルトメッセージが送信されます）
       python notify.py 
       
       または、他のスクリプトから import して使用:
       from notify import send_notification
       send_notification("処理が完了しました")
"""

# ==========================================
# 設定エリア (ここに直接書き込むか、環境変数を設定してください)
# ==========================================

# LINE Notify設定
# 取得方法: https://notify-bot.line.me/my/
LINE_NOTIFY_TOKEN = os.getenv('LINE_NOTIFY_TOKEN', '')  # 例: 'YOUR_LINE_TOKEN'

# Slack Webhook設定
# 取得方法: https://api.slack.com/messaging/webhooks
SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL', '')  # 例: 'https://hooks.slack.com/services/...'

# Discord Webhook設定
# 取得方法: チャンネル設定 -> 連携サービス -> Webhook
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '') # 例: 'https://discord.com/api/webhooks/...'

# ==========================================

def send_line_notify(message, token):
    """LINE Notify APIを使用してメッセージを送信する"""
    if not token:
        return
    
    api_url = 'https://notify-api.line.me/api/notify'
    headers = {'Authorization': f'Bearer {token}'}
    data = {'message': f'\n{message}'}
    
    try:
        response = requests.post(api_url, headers=headers, data=data, timeout=10)
        response.raise_for_status()
        print(f"[INFO] LINE送信成功: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] LINE送信失敗: {e}")

def send_slack_notify(message, webhook_url, title=None):
    """Slack Webhookを使用してメッセージを送信する"""
    if not webhook_url:
        return

    payload = {
        "text": message
    }
    if title:
        payload["blocks"] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": title
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": message
                }
            }
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
    """Discord Webhookを使用してメッセージを送信する"""
    if not webhook_url:
        return

    content = message
    if title:
        content = f"**{title}**\n{message}"

    payload = {
        "content": content
    }

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
    """
    設定されている全ての通知手段でメッセージを送信する
    """
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    full_message = f"[{timestamp}] {message}"
    
    print("-" * 30)
    print(f"通知処理開始: {title}")
    
    # 各サービスへの送信試行
    if LINE_NOTIFY_TOKEN:
        send_line_notify(full_message, LINE_NOTIFY_TOKEN)
    
    if SLACK_WEBHOOK_URL:
        send_slack_notify(full_message, SLACK_WEBHOOK_URL, title)

    if DISCORD_WEBHOOK_URL:
        send_discord_notify(full_message, DISCORD_WEBHOOK_URL, title)
        
    if not any([LINE_NOTIFY_TOKEN, SLACK_WEBHOOK_URL, DISCORD_WEBHOOK_URL]):
        print("[WARN] 通知先トークン/URLが設定されていません。コンソール出力のみ行います。")
        print(f"Message: {full_message}")
        
    print("-" * 30)

if __name__ == "__main__":
    # コマンドライン引数の処理
    parser = argparse.ArgumentParser(description='各チャットツールへ通知を送信します')
    # nargs='?' と default を指定することで、引数なしでもエラーにならないように修正
    parser.add_argument('message', type=str, nargs='?', default='(メッセージなし)', help='送信するメッセージ内容')
    parser.add_argument('--title', type=str, default='Notify Script', help='通知のタイトル (Slack/Discord用)')
    
    args = parser.parse_args()
    
    send_notification(args.message, args.title)
import requests
import os
import sys
import argparse
import json
from datetime import datetime

"""
notify.py - 通知送信ユーティリティ

【重要: 設定について】
GASのスクリプトプロパティはGitHub Actionsには共有されません。
以下のいずれかの方法で値を設定してください。

方法A (推奨): GitHub Secretsに設定し、ワークフロー(YAML)から環境変数として渡す。
方法B (テスト用): 下記の変数に直接文字列としてトークンを書き込む。
"""

# ==========================================
# 【設定エリア】
# 環境変数があればそれを使い、なければ直接書かれた値(テスト用)を使います
# ==========================================

# 1. LINE Messaging API設定
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN', '') 
MY_USER_ID = os.getenv('MY_USER_ID', '')

# 2. LINE Notify設定 (予備: 2025/3末まで)
LINE_NOTIFY_TOKEN = os.getenv('LINE_NOTIFY_TOKEN', '') 

# 3. Slack / Discord設定
SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL', '')
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '')

# ==========================================

def send_line_messaging_api(message, token, user_id):
    """
    LINE Messaging API (Push Message) を使用して送信
    DOCS: https://developers.line.biz/ja/reference/messaging-api/#send-push-message
    """
    if not token or not user_id:
        return False

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
        return True
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] LINE Messaging API送信失敗: {e}")
        if e.response is not None:
             print(f"       Status: {e.response.status_code}")
             print(f"       Response: {e.response.text}")
        return False

def send_line_notify(message, token):
    """LINE Notify APIを使用して送信"""
    if not token:
        return False
    
    api_url = 'https://notify-api.line.me/api/notify'
    headers = {'Authorization': f'Bearer {token}'}
    data = {'message': f'\n{message}'}
    
    try:
        response = requests.post(api_url, headers=headers, data=data, timeout=10)
        response.raise_for_status()
        print(f"[INFO] LINE Notify送信成功: {response.status_code}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] LINE Notify送信失敗: {e}")
        return False

def send_slack_notify(message, webhook_url, title=None):
    """Slack Webhookを使用して送信"""
    if not webhook_url:
        return False

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
        return True
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Slack送信失敗: {e}")
        return False

def send_discord_notify(message, webhook_url, title=None):
    """Discord Webhookを使用して送信"""
    if not webhook_url:
        return False

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
        return True
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Discord送信失敗: {e}")
        return False

def check_settings():
    """設定状況を診断してログに出力する"""
    print("[DEBUG] 設定値の確認:")
    print(f"  - CHANNEL_ACCESS_TOKEN: {'設定あり' if CHANNEL_ACCESS_TOKEN else '【未設定】'}")
    print(f"  - MY_USER_ID: {'設定あり' if MY_USER_ID else '【未設定】'}")
    print(f"  - LINE_NOTIFY_TOKEN: {'設定あり' if LINE_NOTIFY_TOKEN else '未設定'}")
    print(f"  - SLACK_WEBHOOK_URL: {'設定あり' if SLACK_WEBHOOK_URL else '未設定'}")
    print(f"  - DISCORD_WEBHOOK_URL: {'設定あり' if DISCORD_WEBHOOK_URL else '未設定'}")

def send_notification(message, title="通知"):
    """設定されている全ての通知手段でメッセージを送信する"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    full_message = f"[{timestamp}] {message}"
    
    print("-" * 30)
    print(f"通知処理開始: {title}")
    
    check_settings()
    
    notify_sent = False
    
    # 送信先が一つも設定されていない場合はエラーにする
    if not any([CHANNEL_ACCESS_TOKEN and MY_USER_ID, LINE_NOTIFY_TOKEN, SLACK_WEBHOOK_URL, DISCORD_WEBHOOK_URL]):
        print("[ERROR] 通知先の設定が一つも見つかりません。環境変数を確認してください。")
        sys.exit(1)

    # 1. LINE Messaging API (優先)
    if CHANNEL_ACCESS_TOKEN and MY_USER_ID:
        if send_line_messaging_api(full_message, CHANNEL_ACCESS_TOKEN, MY_USER_ID):
            notify_sent = True
    
    # 2. LINE Notify (予備)
    if LINE_NOTIFY_TOKEN:
        if send_line_notify(full_message, LINE_NOTIFY_TOKEN):
            notify_sent = True
    
    # 3. Slack
    if SLACK_WEBHOOK_URL:
        if send_slack_notify(full_message, SLACK_WEBHOOK_URL, title):
            notify_sent = True

    # 4. Discord
    if DISCORD_WEBHOOK_URL:
        if send_discord_notify(full_message, DISCORD_WEBHOOK_URL, title):
            notify_sent = True
        
    if not notify_sent:
        print("\n[WARN] 通知送信処理が失敗しました。")
        print("Secretsの設定値や有効期限を確認してください。")
        # GitHub Actionsで失敗(赤色)として扱うために終了コード1を返す
        sys.exit(1)
        
    print("-" * 30)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='各チャットツールへ通知を送信します')
    parser.add_argument('message', type=str, nargs='?', default='(メッセージなし)', help='送信するメッセージ内容')
    parser.add_argument('--title', type=str, default='Notify Script', help='通知のタイトル')
    
    args = parser.parse_args()
    
    send_notification(args.message, args.title)
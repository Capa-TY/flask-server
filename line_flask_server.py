import os
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import requests  # 用於呼叫 OpenRouter API
import json
from datetime import datetime, timedelta

# 初始化 Firebase
cred = credentials.Certificate("stockgpt-150d0-firebase-adminsdk-fbsvc-9ea0d3c5ec.json")  # 替換為你的密鑰
firebase_admin.initialize_app(cred)
db = firestore.client()

# 初始化 Flask
app = Flask(__name__)

# 添加根路徑路由
@app.route("/")
def home():
    return "Welcome to my Flask app on Render!"

# LINE Bot 設定
LINE_ACCESS_TOKEN = "u0JN7NJkL2RuZ3N9zxys5CvUJjsb8ScXfpKkoClrl2CjHFIBGGicZ7MYf5/N1to+5CUl+zYwCMHvjTTtrl+sc1+r2uV1LKEwE+EqISi1bkOpw6l5xvEVsQZiz/7PG/vrqSUKXMQNufLxpGoSP+6AiAdB04t89/1O/w1cDnyilFU="
LINE_CHANNEL_SECRET = "751e2fb4f0320a37836474ce86d89eb9"

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# OpenRouter API 設定
OPENROUTER_API_KEY = "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"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

def get_openrouter_response(user_message):
    """向 OpenRouter 發送請求，獲取 AI 產生的回應"""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "google/gemma-3-27b-it:free",  # 可以更換其他模型
        "messages": [
        {"role": "system", "content": "你是一位專業的財經顧問，擅長股市分析與技術分析，能夠簡潔有力的分析與回答問題。"},
        {"role": "user", "content": user_message}
        ],
        "temperature": 0.7    #代表AI回應的隨機性，值越高他越有創意
    }
    response = requests.post(OPENROUTER_URL, json=data, headers=headers)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        return "抱歉，我無法處理您的請求。"

# 設定 Webhook 端點
@app.route("/callback", methods=["POST"])
def callback():
    if not request.is_json:
        abort(400)

    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK", 200

today = datetime.now()
today_str = today.strftime("%Y年%m月%d日")
tomorrow_str = (today + timedelta(days=1)).strftime("%m月%d日")
# 處理來自 LINE 的訊息
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text.strip()

    # 存入 Firebase Firestore
    doc_ref = db.collection("users").document(user_id)
    doc_ref.set({
        "message": user_message
    }, merge=True)
    
    stock_mapping={
        "台積電":"2330.TW",
        "鴻海":"2317.TW",
        "聯電":"2303.TW"
    }
    matched_stock=None
    for company,stock_code in stock_mapping.items():
        if company in user_message and "預測" in user_message:
            matched_stock=stock_code
            break
    #如果有匹配的公司，就去 Firebase 讀取股價預測
    if matched_stock:
        doc_ref=db.collection("stock_predictions").document(matched_stock)
        doc=doc_ref.get()

        if doc.exists:
            prediction=doc.to_dict().get("predicted_price", "無法獲取預測數據")
            date=doc.to_dict().get("last_updated", "無法獲取預測數據")
            reply_text = f"今天是{date}\n{company} 預測的股價為：\n{prediction} 元"
        else:
            reply_text = f"⚠️ 目前沒有{company}的預測數據，請稍後再試。"

    # 如沒有出現關鍵字，就取得 AI 生成的回覆
    else:
        print("請稍候，正在分析問題中......\n")
        reply_text = get_openrouter_response(user_message)
    # 回應使用者
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
print(today_str)
# 啟動 Flask 伺服器
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)

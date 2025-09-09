import os
import firebase_admin
from firebase_admin import credentials, firestore,storage
from flask import Flask, request, abort,jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage ,ImageSendMessage
import requests  # 用於呼叫 OpenRouter API
import json
from datetime import datetime, timedelta,timezone
import urllib.parse

    

# 初始化 Firebase
firebase_creds=json.loads(os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON"))
cred = credentials.Certificate(firebase_creds)  # 替換為你的密鑰
firebase_admin.initialize_app(cred)
db = firestore.client()
bucket = storage.bucket('stockgpt-150d0.firebasestorage.app')

# 初始化 Flask
app =  Flask(__name__)

# 啟動時讀入 JSON
#with open("static/data/image_urls.json", "r") as f:
    #image_urls = json.load(f)

# 添加根路徑路由
@app.route("/")
def home():
    return "Welcome  to my Flask app on Render!"
def index():
    return "Hello! 用 /get_image/<stock_id> 來查圖網址"

# LINE Bot 設定
LINE_ACCESS_TOKEN =  os.getenv("LINE_ACCESS_TOKEN")
LINE_CHANNEL_SECRET =  os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# OpenRouter API 設定
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = os.getenv("OPENROUTER_URL")

def get_today_str():#抓最新日期
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

def get_image_url_from_storage(stock_id):
    """從 Firebase Storage 獲取圖片 URL"""
    try:
        blob = bucket.blob(f"{stock_id}_predict_vs_close.png")
        if blob.exists():
            blob.make_public()
            return blob.public_url
        return None
    except Exception as e:
        print(f"Error getting image URL: {e}")
        return None

def get_volume_url_from_storage():
    """從 Firebase Storage 獲取圖片 URL"""
    try:
        blob = bucket.blob(f"volume_comparison.png")
        if blob.exists():
            blob.make_public()
            return blob.public_url
        return None
    except Exception as e:
        print(f"Error getting image URL: {e}")
        return None



def get_openrouter_response(user_message):
    """向 OpenRouter 發送請求，獲取 AI 產生的回應 """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "deepseek/deepseek-chat-v3.1:free",   # 可以更換其他模型
        "messages": [
        {"role": "system", "content": "你是一位親切專業的財經顧問， 擁有豐富的投資經驗和市場洞察力。你的特點是用幽默詼諧、淺顯易懂的語言，將複雜的股市分析轉化為一般投資人能快速理解的觀點，並且回覆長度盡量控制在100字以內，能搭配笑話、表情符號、表格統整更好，重點是提供有價值的洞見並以搞笑輕鬆的回應讓使用者從問題中成長"},
        {"role": "user", "content": user_message}
        ],
        "temperature": 0.7    #代表AI回應的隨機性，值越高他越有創意
    }
    response = requests.post(OPENROUTER_URL, json=data, headers=headers,timeout=10)
    try:
        res_json = response.json()
    except Exception as e:
        print(f"無法解析 JSON：{e}")
        print(response.text)
        return "⚠️ 抱歉，API 回傳格式異常，請稍後再試。"

    if response.status_code == 200 and "choices" in res_json:
        return res_json["choices"][0]["message"]["content"]
    else:
        print("OpenRouter 錯誤：", res_json)
        return "⚠️ 抱歉，目前無法獲得回應，可能是伺服器忙碌或金鑰問題。"


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

# 處理來自 LINE 的訊息
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text.strip()
    today_str = get_today_str()  # 每次查詢時重新計算今天的日期

    # userid存入 Firebase Firestore
    doc_ref = db.collection("users").document(user_id)
    doc_ref.set({
        "message": user_message
    }, merge=True)
    
    stock_mapping={
        "台積電":"2330.TW",
        "鴻海":"2317.TW",
        "聯電":"2303.TW"
    }
    company_name=None
    matched_stock=None
    for company,stock_code in stock_mapping.items():
        if  company in user_message and "查詢中" in user_message:#設定關鍵字回覆
            matched_stock=stock_code
            company_name=company
            break


            
    #如果有匹配的公司，就去 Firebase 讀取股價預測
    image_url = None
    volume_url=None
    

    if matched_stock:
        print(f"📌 LINE Bot 查詢的日期：{today_str}")#測試日期
        doc_ref=db.collection("stock_predictions").document(matched_stock).collection("daily_prediction").document(today_str)
        doc=doc_ref.get()
        
        if doc.exists:
            prediction=doc.to_dict().get("predicted_price", "無法獲取預測數據")#抓predicted_price欄位

            #date=doc.to_dict().get("last_updated", "無法獲取預測數據")#如果成功獲取到值，則將其賦值給變數 date。果文件中不存在 "last_updated" 欄位，則將 date 設定為預設值 "無法獲取預測數據"。
            sentiment_ref=db.collection("news").document(company_name)
            sentiment=sentiment_ref.get()
            if sentiment.exists:
                sentiment_score=sentiment.to_dict().get("daily_averages",{}).get(today_str, 0)
            else:
                print(f"⚠️沒有找到新聞情緒數據！")
                sentiment_score=0
            if  sentiment_score<0:
                result="經整合分析，今日新聞較消極、負面📉😭😭"
            elif sentiment_score==0:
                result = "經整合分析，今日新聞情緒中立⚖️"
            elif 0<sentiment_score:
                result="經整合分析，今日新聞較積極、正面📈😄😄"
            
            reply_text = f"🗓️今天是{today_str}\n今天{company_name}的情緒分數為{sentiment_score}\n📊{result}\n{company_name}預測的股價為：\n{prediction} 元\n附圖為近兩週交易日的真實vs預測股價比對圖"
        else:
            reply_text = f"⚠️ 目前沒有{company_name}的預測數據，需等待晚間美股🇺🇸收盤進行數據整合，請於早上八點🕗後再嘗試💬。"
    
        #json_url = "https://raw.githubusercontent.com/Capa-TY/flask-server/main/static/data/image_urls.json"
        image_url = get_image_url_from_storage(matched_stock)
    
    
    # 如沒有出現關鍵字，就取得 AI 生成的回覆
    else:
        reply_text = get_openrouter_response(user_message)


    if  "成交量比較查詢" in user_message:
        volume_url=get_volume_url_from_storage()
    # 回應使用者
    #line_bot_api.reply_  message(event.reply_token, TextSendMessage(text=reply_text))
    
    if image_url: #if 有圖
        #print(f"Sending image: {image_url}")
        line_bot_api.reply_message(
            event.reply_token,
            [
                TextSendMessage(text=reply_text),
                ImageSendMessage(
                    original_content_url=image_url,
                    preview_image_url=image_url
            )
        ]
    )
    elif volume_url:
        line_bot_api.reply_message(
            event.reply_token,
            [
                ImageSendMessage(
                    original_content_url=volume_url,
                    preview_image_url=volume_url
            )
        ]
    )
    else:
        print("No image URL  found.") 
        print("⚠️ Ai回覆...")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))



# 啟動 Flask 伺服器
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)

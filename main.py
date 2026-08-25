import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request
import telebot
from google import genai

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)
client = genai.Client(api_key=GEMINI_API_KEY)
app = FastAPI()

@app.post(f"/{TELEGRAM_TOKEN}")
def process_webhook(update: dict):
    """Этот эндпоинт автоматически принимает сообщения от Telegram"""
    if "message" in update or "text" in update.get("message", {}):
        message = telebot.types.Update.de_json(update).message
        user_text = message.text
        
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=user_text,
            )
            bot.reply_to(message, response.text)
        except Exception as e:
            bot.reply_to(message, f"Ошибка при обращении к ИИ: {e}")
            
    return {"status": "ok"}

@app.get("/")
def index():
    return {"status": "Bot is running!"}

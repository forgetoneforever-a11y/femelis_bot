import os
from dotenv import load_dotenv
from fastapi import FastAPI
import telebot
from telebot import types
from google import genai

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)
client = genai.Client(api_key=GEMINI_API_KEY)
app = FastAPI()

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_start = types.KeyboardButton("🚀 Начать")
    btn_support = types.KeyboardButton("⚠️ Жалоба / Поддержка")
    markup.add(btn_start, btn_support)
    return markup

@app.post(f"/{TELEGRAM_TOKEN}")
def process_webhook(update: dict):
    """Эндпоинт для обработки входящих сообщений от Telegram"""
    if "message" in update:
        message = telebot.types.Update.de_json(update).message
        user_text = message.text

        if user_text and (user_text == "🚀 Начать" or user_text.startswith("/start")):
            welcome_text = (
                "👋 **Привет!** Я твой персональный ИИ-ассистент на базе Gemini.\n\n"
                "Задай мне любой вопрос, и я с радостью на него отвечу!"
            )
            bot.reply_to(message, welcome_text, parse_mode="Markdown", reply_markup=get_main_keyboard())
            return {"status": "ok"}

        if user_text == "⚠️ Жалоба / Поддержка":
            support_text = (
                "💬 **Служба поддержки**\n\n"
                "Если у вас возникли вопросы, проблемы или вы хотите оставить жалобу, "
                "пожалуйста, обратитесь в наш сервис обратной связи."
            )
            bot.reply_to(message, support_text, parse_mode="Markdown", reply_markup=get_main_keyboard())
            return {"status": "ok"}

        if user_text:
            try:
                response = client.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=user_text,
                )
                bot.reply_to(message, response.text, reply_markup=get_main_keyboard())
            except Exception as e:
                bot.reply_to(message, f"Ошибка при обращении к ИИ: {e}", reply_markup=get_main_keyboard())

    return {"status": "ok"}

@app.get("/")
def index():
    return {"status": "Bot is running!"}

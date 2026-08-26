import os
from dotenv import load_dotenv
from fastapi import FastAPI
import telebot
from telebot import types
from google import genai

load_dotenv()

# Загружаем ключи из переменных окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Указываем ваш Telegram ID напрямую для получения жалоб
ADMIN_CHAT_ID = 8870678654 

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)
client = genai.Client(api_key=GEMINI_API_KEY)
app = FastAPI()

# Простой словарь в памяти для отслеживания режима "Отправка жалобы"
# (Для продакшена лучше использовать БД, но для начала этого достаточно)
user_states = {}

def get_main_keyboard():
    """Функция для создания клавиатуры с основными кнопками"""
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
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name

        # 1. Ответ администратора на жалобу (когда вы пишете /reply ID ТЕКСТ)
        if user_id == ADMIN_CHAT_ID and user_text and user_text.startswith("/reply "):
            try:
                # Парсим команду: /reply 12345 Ответ на жалобу
                parts = user_text.split(" ", 2)
                target_user_id = parts[1]
                reply_text = parts[2]
                
                bot.send_message(
                    target_user_id, 
                    f"💬 **Ответ от администратора:**\n\n{reply_text}", 
                    parse_mode="Markdown"
                )
                bot.reply_to(message, f"✅ Ответ успешно отправлен пользователю {target_user_id}!")
                return {"status": "ok"}
            except Exception as e:
                bot.reply_to(message, f"❌ Ошибка при отправке ответа. Формат: `/reply ID ТЕКСТ`\nОшибка: {e}")
                return {"status": "ok"}

        # 2. Обработка команды /start или кнопки "Начать"
        if user_text and (user_text == "🚀 Начать" or user_text.startswith("/start")):
            user_states[user_id] = "normal" # Сбрасываем статус
            welcome_text = (
                "👋 **Привет!** Я твой персональный ИИ-ассистент на базе Gemini.\n\n"
                "Задай мне любой вопрос, и я с радостью на него отвечу!"
            )
            bot.reply_to(message, welcome_text, parse_mode="Markdown", reply_markup=get_main_keyboard())
            return {"status": "ok"}

        # 3. Нажатие на кнопку "Жалоба / Поддержка"
        if user_text == "⚠️ Жалоба / Поддержка":
            user_states[user_id] = "waiting_for_ticket" # Переводим пользователя в режим жалобы
            support_text = (
                "💬 **Служба поддержки**\n\n"
                "Пожалуйста, опишите вашу проблему или оставьте жалобу **одним сообщением**, "
                "и я передам её администратору."
            )
            bot.reply_to(message, support_text, parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())
            return {"status": "ok"}

        # 4. Если пользователь находится в режиме отправки жалобы (вводит текст жалобы)
        if user_states.get(user_id) == "waiting_for_ticket" and user_text:
            user_states[user_id] = "normal" # Сбрасываем статус после отправки
            
            # Формируем сообщение для администратора
            admin_message = (
                f"🚨 **Новое обращение!**\n\n"
                f"👤 От: @{username}\n"
                f"🆔 ID: `{user_id}`\n"
                f"💬 Текст: {user_text}\n\n"
                f"_(Чтобы ответить, скопируйте команду ниже и добавьте текст ответа)_:\n"
                f"`/reply {user_id} Ваш текст`"
            )
            
            try:
                # Отправляем сообщение вам (админу)
                bot.send_message(ADMIN_CHAT_ID, admin_message, parse_mode="Markdown")
                bot.reply_to(message, "✅ Ваше сообщение успешно отправлено администратору. Ожидайте ответа!", reply_markup=get_main_keyboard())
            except Exception as e:
                bot.reply_to(message, f"❌ Произошла ошибка при отправке сообщения. Попробуйте позже.", reply_markup=get_main_keyboard())
                
            return {"status": "ok"}

        # 5. Обычные текстовые сообщения (если это не команда и не жалоба) отправляем в Gemini
        if user_text:
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash", 
                    contents=user_text,
                )
                bot.reply_to(message, response.text, reply_markup=get_main_keyboard())
            except Exception as e:
                bot.reply_to(message, f"Ошибка при обращении к ИИ: {e}", reply_markup=get_main_keyboard())

    return {"status": "ok"}

@app.get("/")
def index():
    return {"status": "Bot is running!"}

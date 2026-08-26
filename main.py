import os
from dotenv import load_dotenv
from fastapi import FastAPI
import telebot
from telebot import types
from google import genai
import httpx

load_dotenv()

# Загружаем ключи из переменных окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Ваш Telegram ID для получения обращений в поддержку
ADMIN_CHAT_ID = 8870678654 

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)
client = genai.Client(api_key=GEMINI_API_KEY)
app = FastAPI()

# Хранилища в памяти
user_states = {}        # Режимы работы пользователей (например, отправка жалобы)
user_models = {}        # Выбранная модель: "gemini" или "groq" (по умолчанию gemini)

def get_main_keyboard():
    """Главная клавиатура бота"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_start = types.KeyboardButton("🚀 Начать")
    btn_settings = types.KeyboardButton("⚙️ Настройки")
    btn_support = types.KeyboardButton("⚠️ Жалоба / Поддержка")
    markup.add(btn_start, btn_settings)
    markup.add(btn_support)
    return markup

def get_models_inline_keyboard():
    """Инлайн-кнопки для выбора между Gemini и Groq (Llama 3)"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✨ Gemini", callback_data="model_gemini"))
    markup.add(types.InlineKeyboardButton("⚡ Groq (Llama 3)", callback_data="model_groq"))
    return markup

@app.post(f"/{TELEGRAM_TOKEN}")
def process_webhook(update: dict):
    """Эндпоинт для обработки входящих обновлений от Telegram"""
    
    # 1. Обработка нажатий на инлайн-кнопки (переключение моделей)
    if "callback_query" in update:
        callback = telebot.types.Update.de_json(update).callback_query
        user_id = callback.from_user.id
        data = callback.data

        if data.startswith("model_"):
            chosen_model = data.split("_")[1]
            user_models[user_id] = chosen_model
            
            model_names = {
                "gemini": "Gemini ✨",
                "groq": "Groq (Llama 3) ⚡"
            }
            
            bot.answer_callback_query(callback.id, text=f"Модель изменена на {model_names.get(chosen_model)}")
            bot.edit_message_text(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                text=f"✅ Активная модель успешно изменена!\n\nТекущая нейросеть: **{model_names.get(chosen_model)}**",
                parse_mode="Markdown"
            )
        return {"status": "ok"}

    # 2. Обработка текстовых сообщений
    if "message" in update:
        message = telebot.types.Update.de_json(update).message
        user_text = message.text
        user_id = message.from_user.id
        
        first_name = message.from_user.first_name or ""
        last_name = message.from_user.last_name or ""
        username = message.from_user.username
        
        full_name = f"{first_name} {last_name}".strip()
        user_tag = f"@{username}" if username else "нет юзернейма"

        # Ответ администратора на жалобу через /reply
        if user_id == ADMIN_CHAT_ID and user_text and user_text.startswith("/reply "):
            try:
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
                bot.reply_to(message, f"❌ Ошибка отправки: {e}")
                return {"status": "ok"}

        # Команда /start или кнопка "Начать"
        if user_text and (user_text == "🚀 Начать" or user_text.startswith("/start")):
            user_states[user_id] = "normal"
            welcome_text = (
                "👋 **Привет!** Я твой ИИ-ассистент.\n\n"
                "Ты можешь переключаться между **Gemini** и **Groq (Llama 3)** через меню «Настройки»!"
            )
            bot.reply_to(message, welcome_text, parse_mode="Markdown", reply_markup=get_main_keyboard())
            return {"status": "ok"}

        # Кнопка "Настройки"
        if user_text == "⚙️ Настройки":
            bot.reply_to(
                message, 
                "⚙️ **Настройки бота**\n\nВыберите языковую модель для общения:", 
                parse_mode="Markdown", 
                reply_markup=get_models_inline_keyboard()
            )
            return {"status": "ok"}

        # Кнопка "Жалоба / Поддержка"
        if user_text == "⚠️ Жалоба / Поддержка":
            user_states[user_id] = "waiting_for_ticket"
            support_text = (
                "💬 **Служба поддержки**\n\n"
                "Опишите вашу проблему или оставьте жалобу **одним сообщением**, и я передам её администратору."
            )
            bot.reply_to(message, support_text, parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())
            return {"status": "ok"}

        # Обработка отправки жалобы администратору
        if user_states.get(user_id) == "waiting_for_ticket" and user_text:
            user_states[user_id] = "normal"
            
            admin_message = (
                f"🚨 **Новое обращение в поддержку!**\n\n"
                f"👤 **Имя:** {full_name}\n"
                f"🔗 **Юзернейм:** {user_tag}\n"
                f"🆔 **ID:** `{user_id}`\n"
                f"💬 **Текст:** {user_text}\n\n"
                f"`/reply {user_id} Текст ответа`"
            )
            try:
                bot.send_message(ADMIN_CHAT_ID, admin_message, parse_mode="Markdown")
                bot.reply_to(message, "✅ Сообщение успешно отправлено администратору!", reply_markup=get_main_keyboard())
            except Exception:
                bot.reply_to(message, "❌ Ошибка при отправке сообщения.", reply_markup=get_main_keyboard())
            return {"status": "ok"}

        # Генерация ответа через выбранную модель (Gemini или Groq)
        if user_text:
            active_model = user_models.get(user_id, "gemini")
            ai_response = "Ошибка генерации ответа."

            try:
                if active_model == "gemini":
                    response = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=user_text,
                    )
                    ai_response = response.text

                elif active_model == "groq":
                    if not GROQ_API_KEY:
                        ai_response = "⚠️ API-ключ для Groq (`GROQ_API_KEY`) не настроен в переменных окружения на Render."
                    else:
                        headers = {
                            "Authorization": f"Bearer {GROQ_API_KEY}",
                            "Content-Type": "application/json"
                        }
                        json_data = {
                            "model": "llama3-8b-8192",
                            "messages": [{"role": "user", "content": user_text}]
                        }
                        with httpx.Client() as httpx_client:
                            res = httpx_client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=json_data, timeout=30)
                            
                            if res.status_code == 200:
                                res_json = res.json()
                                ai_response = res_json["choices"][0]["message"]["content"]
                            else:
                                ai_response = f"⚠️ Ошибка API Groq (код {res.status_code}):\n{res.text}"

                bot.reply_to(message, ai_response, reply_markup=get_main_keyboard())

            except Exception as e:
                bot.reply_to(message, f"❌ Ошибка при запросе к нейросети: {e}", reply_markup=get_main_keyboard())

    return {"status": "ok"}

@app.get("/")
def index():
    return {"status": "Bot is running!"}

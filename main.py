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

# Ваш Telegram ID для получения обращений в поддержку
ADMIN_CHAT_ID = 8870678654 

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)
client = genai.Client(api_key=GEMINI_API_KEY)
app = FastAPI()

# Хранилище состояний пользователей
user_states = {}

def get_main_keyboard():
    """Главная клавиатура бота"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_start = types.KeyboardButton("🚀 Начать")
    btn_support = types.KeyboardButton("⚠️ Жалоба / Поддержка")
    markup.add(btn_start)
    markup.add(btn_support)
    return markup

@app.post(f"/{TELEGRAM_TOKEN}")
def process_webhook(update: dict):
    """Эндпоинт для обработки входящих обновлений от Telegram"""
    
    # 1. Обработка текстовых сообщений
    if "message" in update and "text" in update["message"]:
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
                "👋 **Привет!** Я твой ИИ-ассистент на базе Gemini.\n\n"
                "💬 Задавай текстовые вопросы или **отправляй картинки/скриншоты** — я могу распознавать на них текст и отвечать по их содержимому!"
            )
            bot.reply_to(message, welcome_text, parse_mode="Markdown", reply_markup=get_main_keyboard())
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

        # Генерация ответа через текст
        if user_text:
            try:
                response = client.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=user_text,
                )
                ai_response = response.text
                bot.reply_to(message, ai_response, reply_markup=get_main_keyboard())

            except Exception as e:
                bot.reply_to(message, f"❌ Ошибка при запросе к нейросети: {e}", reply_markup=get_main_keyboard())

    # 2. Обработка фотографий (распознавание текста и анализ изображения)
    if "message" in update and "photo" in update["message"]:
        message = telebot.types.Update.de_json(update).message
        try:
            # Скачиваем фото в наилучшем качестве
            photo = message.photo[-1]
            file_info = bot.get_file(photo.file_id)
            downloaded_file = bot.download_file(file_info.file_path)

            temp_filename = "temp_image.jpg"
            with open(temp_filename, "wb") as f:
                f.write(downloaded_file)

            # Если пользователь написал текст вместе с картинкой — используем его,
            # иначе даем инструкцию по умолчанию: распознать весь текст на фото.
            user_prompt = message.caption or "Распознай и выпиши весь текст, который изображен на этой фотографии, и ответь на вопросы, если они там есть."

            # Загружаем файл в Gemini для анализа
            image_file = client.files.upload(file=temp_filename)
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=[image_file, user_prompt]
            )

            bot.reply_to(message, response.text, reply_markup=get_main_keyboard())

            # Удаляем временный файл после отправки ответа
            if os.path.exists(temp_filename):
                os.remove(temp_filename)

        except Exception as e:
            bot.reply_to(message, f"❌ Не удалось обработать изображение: {e}", reply_markup=get_main_keyboard())

    return {"status": "ok"}

@app.get("/")
def index():
    return {"status": "Bot is running!"}

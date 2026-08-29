import os
import urllib.parse
import re
from dotenv import load_dotenv
from fastapi import FastAPI
import telebot
from telebot import types
from google import genai
from google.genai import types as genai_types

load_dotenv()

# Загружаем ключи из переменных окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Ваш Telegram ID для получения обращений в поддержку
ADMIN_CHAT_ID = 8870678654

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)
client = genai.Client(api_key=GEMINI_API_KEY)
app = FastAPI()

# Хранилище состояний, активных сессий чата, ролей и баланса
user_states = {}
user_chats = {}
user_roles = {}
user_image_limits = {}

# Используем MarkdownV2 для жирных заголовков
PARSE_MODE = "MarkdownV2"

ROLES = {
    "default": "Ты полезный, дружелюбный и эрудированный ИИ-ассистент.",
    "programmer": "Ты строгий, профессиональный Senior-программист. Отвечай кратко, пиши чистый код, указывай на ошибки в архитектуре и логике без лишней «воды».",
    "sarcastic": "Ты саркастичный и ироничный собеседник. Отвечай с черным юмором и легким пренебрежением к человеческой лени, но по делу.",
    "teacher": "Ты терпеливый и мудрый преподаватель. Объясняй сложные вещи простыми словами, приводи жизненные аналогии и задавай наводящие вопросы."
}

def get_user_chat(user_id):
    if user_id not in user_chats:
        role_key = user_roles.get(user_id, "default")
        system_instruction = ROLES.get(role_key, ROLES["default"])

        user_chats[user_id] = client.chats.create(
            model="gemini-3.6-flash",
            config=genai_types.GenerateContentConfig(
                system_instruction=system_instruction
            )
        )
    return user_chats[user_id]

def reset_user_chat(user_id):
    if user_id in user_chats:
        del user_chats[user_id]
    return get_user_chat(user_id)

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_start = types.KeyboardButton("🚀 Начать")
    btn_profile = types.KeyboardButton("👤 О себе")
    btn_roles = types.KeyboardButton("🎭 Выбрать роль")
    btn_premium = types.KeyboardButton("⭐ Premium (5 генераций)")
    btn_support = types.KeyboardButton("⚠️ Жалоба / Поддержка")
    markup.add(btn_start, btn_profile)
    markup.add(btn_roles, btn_premium)
    markup.add(btn_support)
    return markup

def escape_markdown_v2(text):
    """
    Экранирует символы для Telegram MarkdownV2.
    Символы, требующие экранирования: _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    # Список символов, которые нужно экранировать в Telegram MarkdownV2
    # Их нужно экранировать везде, кроме блоков кода
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    # Создаем регулярное выражение для поиска любого из этих символов
    regex = re.compile(f'([{re.escape(escape_chars)}])')
    # Заменяем каждый найденный символ на экранированный
    return regex.sub(r'\\\1', text)

@app.post(f"/{TELEGRAM_TOKEN}")
def process_webhook(update: dict):
    update_obj = telebot.types.Update.de_json(update)

    if update_obj.pre_checkout_query:
        bot.answer_pre_checkout_query(update_obj.pre_checkout_query.id, ok=True)
        return {"status": "ok"}

    if update_obj.message and update_obj.message.successful_payment:
        message = update_obj.message
        user_id = message.from_user.id
        payment = message.successful_payment

        if payment.invoice_payload == "buy_5_images":
            current_balance = user_image_limits.get(user_id, 0)
            user_image_limits[user_id] = current_balance + 5

            response_text = (
                f"🎉 **Оплата прошла успешно\!**\n\n"
                f"Вам зачислено **5 дополнительных генераций** изображений\.\n"
                f"Баланс платных генераций: `{user_image_limits[user_id]}`"
            )
            bot.reply_to(
                message,
                response_text,
                parse_mode=PARSE_MODE,
                reply_markup=get_main_keyboard()
            )
        return {"status": "ok"}

    if update_obj.callback_query:
        call = update_obj.callback_query
        user_id = call.from_user.id
        data = call.data

        if data.startswith("role_"):
            role_key = data.replace("role_", "")
            if role_key in ROLES:
                user_roles[user_id] = role_key
                reset_user_chat(user_id)

                role_names = {
                    "default": "🤖 Обычный ассистент",
                    "programmer": "💻 Строгий программист",
                    "sarcastic": "😏 Саркастичный собеседник",
                    "teacher": "🎓 Мудрый преподаватель"
                }

                bot.answer_callback_query(call.id, f"Роль изменена!")
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.id,
                    text=f"✅ Успешно установлена роль: **{role_names.get(role_key, 'Ассистент')}**.\n\nМожете продолжать общение!",
                    parse_mode=PARSE_MODE
                )
        return {"status": "ok"}

    if update_obj.message and update_obj.message.text:
        message = update_obj.message
        user_text = message.text
        user_id = message.from_user.id

        first_name = escape_markdown_v2(message.from_user.first_name or "")
        last_name = escape_markdown_v2(message.from_user.last_name or "")
        username = message.from_user.username
        language_code = message.from_user.language_code or "не указан"

        full_name = f"{first_name} {last_name}".strip()
        user_tag = f"@{username}" if username else "нет юзернейма"

        if user_id == ADMIN_CHAT_ID and user_text and user_text.startswith("/reply "):
            try:
                parts = user_text.split(" ", 2)
                target_user_id = int(parts[1])
                reply_text = parts[2]

                bot.send_message(
                    target_user_id,
                    f"💬 **Ответ от администратора:**\n\n{reply_text}",
                    parse_mode=PARSE_MODE
                )
                bot.reply_to(message, f"✅ Ответ успешно отправлен пользователю {target_user_id}!")
                return {"status": "ok"}
            except Exception as e:
                bot.reply_to(message, f"❌ Ошибка отправки: {e}")
                return {"status": "ok"}

        if user_text and (user_text == "🚀 Начать" or user_text.startswith("/start")):
            user_states[user_id] = "normal"
            reset_user_chat(user_id)

            welcome_text = (
                f"👋 **Привет\!** Я твой ИИ\-ассистент на базе Gemini\.\n\n"
                f"🎭 Настраивай стиль общения кнопкой **«🎭 Выбрать роль»**\!\n"
                f"⭐ Кнопка **«⭐ Premium»** позволяет купить дополнительные генерации картинок за звёзды\.\n"
                f"🎨 Я также понимаю голос, фото и помню контекст\."
            )
            bot.reply_to(message, welcome_text, parse_mode=PARSE_MODE, reply_markup=get_main_keyboard())
            return {"status": "ok"}

        if user_text == "🎭 Выбрать роль" or user_text == "/role":
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("🤖 Обычный ассистент", callback_data="role_default"),
                types.InlineKeyboardButton("💻 Строгий программист", callback_data="role_programmer"),
                types.InlineKeyboardButton("😏 Саркастичный собеседник", callback_data="role_sarcastic"),
                types.InlineKeyboardButton("🎓 Мудрый преподаватель", callback_data="role_teacher")
            )
            bot.reply_to(message, "👇 Выберите стиль общения бота:", reply_markup=markup)
            return {"status": "ok"}

        if user_text and user_text.startswith("/image "):
            prompt = user_text.replace("/image", "").strip()
            if not prompt:
                bot.reply_to(message, "⚠️ Пожалуйста, укажите описание для картинки после команды, например:\n`/image cyberpunk cat`", parse_mode=PARSE_MODE)
                return {"status": "ok"}

            current_balance = user_image_limits.get(user_id, 0)
            if current_balance <= 0:
                bot.reply_to(
                    message,
                    "⚠️ У вас закончились дополнительные генерации картинок!\n\nНажмите кнопку **«⭐ Premium (5 генераций)»**, чтобы приобрести пакет за Telegram Stars.",
                    parse_mode=PARSE_MODE,
                    reply_markup=get_main_keyboard()
                )
                return {"status": "ok"}

            try:
                bot.send_chat_action(message.chat.id, 'upload_photo')
                user_image_limits[user_id] = current_balance - 1

                encoded_prompt = urllib.parse.quote(prompt)
                image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"

                caption_text = (
                    f"🎨 **Запрос:** {escape_markdown_v2(prompt)}\n"
                    f"⭐ **Остаток генераций:** `{user_image_limits[user_id]}`"
                )
                bot.send_photo(
                    message.chat.id,
                    photo=image_url,
                    caption=caption_text,
                    parse_mode=PARSE_MODE,
                    reply_markup=get_main_keyboard()
                )
            except Exception as e:
                user_image_limits[user_id] += 1
                bot.reply_to(message, f"❌ Ошибка при генерации изображения: {e}", parse_mode=PARSE_MODE)
            return {"status": "ok"}

        if user_text == "👤 О себе":
            balance = user_image_limits.get(user_id, 0)
            profile_text = (
                f"👤 **Информация о вашем аккаунте:**\n\n"
                f"🆔 **ID:** `{user_id}`\n"
                f"📌 **Имя:** {full_name}\n"
                f"🔗 **Username:** {user_tag}\n"
                f"🌐 **Язык Telegram:** `{language_code}`\n"
                f"🎨 **Баланс генераций /image:** `{balance}`\n\n"
                f"*Примечание: точная страна и номер телефона скрыты настройками безопасности Telegram.*"
            )
            bot.reply_to(message, profile_text, parse_mode=PARSE_MODE, reply_markup=get_main_keyboard())
            return {"status": "ok"}

        if user_text == "⚠️ Жалоба / Поддержка":
            user_states[user_id] = "waiting_for_ticket"
            support_text = (
                "💬 **Служба поддержки**\n\n"
                "Опишите вашу проблему или оставьте жалобу **одним сообщением**, и я передам её администратору."
            )
            bot.reply_to(message, support_text, parse_mode=PARSE_MODE, reply_markup=types.ReplyKeyboardRemove())
            return {"status": "ok"}

        if user_states.get(user_id) == "waiting_for_ticket" and user_text:
            user_states[user_id] = "normal"
            admin_message = (
                f"🚨 **Новое обращение в поддержку!**\n\n"
                f"👤 **Имя:** {full_name}\n"
                f"🔗 **Юзернейм:** {user_tag}\n"
                f"🆔 **ID:** `{user_id}`\n"
                f"💬 **Текст:** {escape_markdown_v2(user_text)}\n\n"
                f"`/reply {user_id} Текст ответа`"
            )
            try:
                bot.send_message(ADMIN_CHAT_ID, admin_message, parse_mode=PARSE_MODE)
                bot.reply_to(message, "✅ Сообщение успешно отправлено администратору!", reply_markup=get_main_keyboard())
            except Exception:
                bot.reply_to(message, "❌ Ошибка при отправке сообщения.", reply_markup=get_main_keyboard())
            return {"status": "ok"}

        # Основной генеративный ответ (с экранированием текста от нейросети)
        if user_text:
            try:
                chat = get_user_chat(user_id)
                response = chat.send_message(user_text)
                
                # Экранируем ответ от нейросети, чтобы он не сломал разметку
                safe_response_text = escape_markdown_v2(response.text)
                
                bot.reply_to(message, safe_response_text, parse_mode=PARSE_MODE, reply_markup=get_main_keyboard())

            except Exception as e:
                bot.reply_to(message, f"❌ Ошибка при запросе к нейросети: {e}", parse_mode=PARSE_MODE)

    # Обработка фото
    if update_obj.message and update_obj.message.photo:
        message = update_obj.message
        user_id = message.from_user.id
        try:
            photo = message.photo[-1]
            file_info = bot.get_file(photo.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            temp_filename = "temp_image.jpg"
            with open(temp_filename, "wb") as f:
                f.write(downloaded_file)

            user_prompt = message.caption or "Опиши, что изображено на этой фотографии, в соответствии с твоей ролью."
            safe_user_prompt = escape_markdown_v2(user_prompt)

            image_file = client.files.upload(file=temp_filename)
            chat = get_user_chat(user_id)
            response = chat.send_message([image_file, safe_user_prompt])
            
            safe_response_text = escape_markdown_v2(response.text)

            bot.reply_to(message, safe_response_text, parse_mode=PARSE_MODE, reply_markup=get_main_keyboard())
            if os.path.exists(

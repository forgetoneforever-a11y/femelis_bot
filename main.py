import os
import urllib.parse
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

# Хранилище состояний, активных сессий чата, ролей и баланса дополнительных запросов /image
user_states = {}
user_chats = {}
user_roles = {}
user_image_limits = {} # Хранит количество доступных платных генераций для каждого пользователя

# Предустановленные роли (системные инструкции)
ROLES = {
    "default": "Ты полезный, дружелюбный и эрудированный ИИ-ассистент.",
    "programmer": "Ты строгий, профессиональный Senior-программист. Отвечай кратко, пиши чистый код, указывай на ошибки в архитектуре и логике без лишней «воды».",
    "sarcastic": "Ты саркастичный и ироничный собеседник. Отвечай с черным юмором и легким пренебрежением к человеческой лени, но по делу.",
    "teacher": "Ты терпеливый и мудрый преподаватель. Объясняй сложные вещи простыми словами, приводи жизненные аналогии и задавай наводящие вопросы."
}

def get_user_chat(user_id):
    """Создает или возвращает существующую сессию чата с учетом выбранной роли пользователя"""
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
    """Сбрасывает сессию чата (при изменении роли или новом старте)"""
    if user_id in user_chats:
        del user_chats[user_id]
    return get_user_chat(user_id)

def get_main_keyboard():
    """Главная клавиатура бота"""
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

@app.post(f"/{TELEGRAM_TOKEN}")
def process_webhook(update: dict):
    """Эндпоинт для обработки входящих обновлений от Telegram"""
    
    update_obj = telebot.types.Update.de_json(update)

    # Обработка успешного платежа звёздами
    if update_obj.pre_checkout_query:
        bot.answer_pre_checkout_query(update_obj.pre_checkout_query.id, ok=True)
        return {"status": "ok"}

    if update_obj.message and update_obj.message.successful_payment:
        message = update_obj.message
        user_id = message.from_user.id
        payment = message.successful_payment
        
        if payment.invoice_payload == "buy_5_images":
            # Начисляем 5 дополнительных генераций
            current_balance = user_image_limits.get(user_id, 0)
            user_image_limits[user_id] = current_balance + 5
            
            bot.reply_to(
                message, 
                f"🎉 **Оплата прошла успешно!**\n\nВам зачислено **5 дополнительных генераций** изображений.\nБаланс платных генераций: `{user_image_limits[user_id]}`", 
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
        return {"status": "ok"}

    # Обработка нажатий на инлайн-кнопки (выбор ролей)
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
                    parse_mode="Markdown"
                )
        return {"status": "ok"}

    # 1. Обработка текстовых сообщений
    if update_obj.message and update_obj.message.text:
        message = update_obj.message
        user_text = message.text
        user_id = message.from_user.id
        
        first_name = message.from_user.first_name or ""
        last_name = message.from_user.last_name or ""
        username = message.from_user.username
        language_code = message.from_user.language_code or "не указан"
        
        full_name = f"{first_name} {last_name}".strip()
        user_tag = f"@{username}" if username else "нет юзернейма"

        # Ответ администратора на жалобу через /reply
        if user_id == ADMIN_CHAT_ID and user_text and user_text.startswith("/reply "):
            try:
                parts = user_text.split(" ", 2)
                target_user_id = int(parts[1])
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
            reset_user_chat(user_id)
            
            welcome_text = (
                "👋 **Привет!** Я твой ИИ-ассистент на базе Gemini.\n\n"
                "🎭 Настраивай стиль общения кнопкой **«🎭 Выбрать роль»**!\n"
                "⭐ Кнопка **«⭐ Premium»** позволяет купить дополнительные генерации картинок за звёзды."
            )
            bot.reply_to(message, welcome_text, parse_mode="Markdown", reply_markup=get_main_keyboard())
            return {"status": "ok"}

        # Кнопка /role
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

        # Кнопка покупки Premium за Telegram Stars
        if user_text == "⭐ Premium (5 генераций)" or user_text == "/premium":
            title = "⭐ Пакет Premium: 5 генераций картинок"
            description = "Дает право на 5 дополнительных запросов в генераторе изображений /image."
            payload = "buy_5_images"
            currency = "XTR" # Валюта Telegram Stars
            prices = [types.LabeledPrice(label="5 генераций", amount=5)] # Стоимость: 5 Telegram Stars
            
            try:
                bot.send_invoice(
                    chat_id=message.chat.id,
                    title=title,
                    description=description,
                    invoice_payload=payload,
                    provider_token="", # Для цифровых товаров (Stars) токен провайдера оставляем пустым ("")
                    currency=currency,
                    prices=prices,
                    start_parameter="buy-images"
                )
            except Exception as e:
                bot.reply_to(message, f"❌ Ошибка создания счета: {e}", reply_markup=get_main_keyboard())
            return {"status": "ok"}

        # Генерация изображений с проверкой баланса
        if user_text and user_text.startswith("/image "):
            prompt = user_text.replace("/image", "").strip()
            if not prompt:
                bot.reply_to(message, "⚠️ Пожалуйста, укажите описание для картинки после команды, например:\n`/image cyberpunk cat`", parse_mode="Markdown")
                return {"status": "ok"}

            # Проверяем баланс платных запросов (например, дадим 2 бесплатных, а дальше требуем звезды)
            current_balance = user_image_limits.get(user_id, 0)
            
            # Для примера: если у пользователя меньше 1 генерации, списываем или просим купить
            # Здесь можно настроить логику: бесплатные лимиты или строгая покупка
            if current_balance <= 0:
                bot.reply_to(
                    message, 
                    "⚠️ У вас закончились дополнительные генерации картинок!\n\nНажмите кнопку **«⭐ Premium (5 генераций)»**, чтобы приобрести пакет за Telegram Stars.",
                    parse_mode="Markdown",
                    reply_markup=get_main_keyboard()
                )
                return {"status": "ok"}

            try:
                bot.send_chat_action(message.chat.id, 'upload_photo')
                
                # Уменьшаем баланс на 1 генерацию
                user_image_limits[user_id] = current_balance - 1
                
                encoded_prompt = urllib.parse.quote(prompt)
                image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"

                bot.send_photo(
                    message.chat.id,
                    photo=image_url,
                    caption=f"🎨 *Запрос:* {prompt}\n⭐ *Остаток генераций:* `{user_image_limits[user_id]}`",
                    parse_mode="Markdown",
                    reply_markup=get_main_keyboard()
                )
            except Exception as e:
                # Возвращаем попытку при ошибке
                user_image_limits[user_id] += 1
                bot.reply_to(message, f"❌ Ошибка при генерации изображения: {e}", reply_markup=get_main_keyboard())
            return {"status": "ok"}

        # Кнопка "О себе"
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
            bot.reply_to(message, profile_text, parse_mode="Markdown", reply_markup=get_main_keyboard())
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

        # Генерация ответа через текстовый чат (с учетом роли и контекста)
        if user_text:
            try:
                chat = get_user_chat(user_id)
                response = chat.send_message(user_text)
                ai_response = response.text
                bot.reply_to(message, ai_response, reply_markup=get_main_keyboard())

            except Exception as e:
                bot.reply_to(message, f"❌ Ошибка при запросе к нейросети: {e}", reply_markup=get_main_keyboard())

    # 2. Обработка фотографий
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

            image_file = client.files.upload(file=temp_filename)
            chat = get_user_chat(user_id)
            response = chat.send_message([image_file, user_prompt])

            bot.reply_to(message, response.text, reply_markup=get_main_keyboard())

            if os.path.exists(temp_filename):
                os.remove(temp_filename)

        except Exception as e:
            bot.reply_to(message, f"❌ Не удалось обработать изображение: {e}", reply_markup=get_main_keyboard())

    # 3. Обработка голосовых сообщений
    if update_obj.message and update_obj.message.voice:
        message = update_obj.message
        user_id = message.from_user.id
        try:
            voice_info = bot.get_file(message.voice.file_id)
            downloaded_voice = bot.download_file(voice_info.file_path)

            temp_audio = "temp_voice.ogg"
            with open(temp_audio, "wb") as f:
                f.write(downloaded_voice)

            audio_file = client.files.upload(file=temp_audio)
            chat = get_user_chat(user_id)
            response = chat.send_message([
                audio_file, 
                "Распознай речь из этого голосового сообщения и ответь на него."
            ])

            bot.reply_to(message, f"🎙 *Ответ:*\n\n{response.text}", parse_mode="Markdown", reply_markup=get_main_keyboard())

            if os.path.exists(temp_audio):
                os.remove(temp_audio)

        except Exception as e:
            bot.reply_to(message, f"❌ Не удалось обработать голосовое сообщение: {e}", reply_markup=get_main_keyboard())

    return {"status": "ok"}

@app.get("/")
def index():
    return {"status": "Bot is running!"}

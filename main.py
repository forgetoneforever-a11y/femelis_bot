import os
import urllib.parse
import re
import json
from datetime import date
from dotenv import load_dotenv
from fastapi import FastAPI
import telebot
from telebot import types
from google import genai
from google.genai import types as genai_types

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

ADMIN_CHAT_ID = 8870678654

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)
client = genai.Client(api_key=GEMINI_API_KEY)
app = FastAPI()

# Файлы для сохранения данных
USERS_FILE = "users.json"
LIMITS_FILE = "limits.json"
SETTINGS_FILE = "settings.json"
BLOCKED_FILE = "blocked.json"

user_states = {}
user_chats = {}
user_roles = {}

PARSE_MODE = "MarkdownV2"

ROLES = {
    "default": "Ты полезный, дружелюбный и эрудированный ИИ-ассистент.",
    "programmer": "Ты строгий, профессиональный Senior-программист. Отвечай кратко, пиши чистый код, указывай на ошибки в архитектуре и логике без лишней «воды».",
    "sarcastic": "Ты саркастичный и ироничный собеседник. Отвечай с черным юмором и легким пренебрежением к человеческой лени, но по делу.",
    "teacher": "Ты терпеливый и мудрый преподаватель. Объясняй сложные вещи простыми словами, приводи жизненные аналогии и задавай наводящие вопросы."
}

def load_data(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_data(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

# Управление техническим перерывом
def is_maintenance_mode():
    settings = load_data(SETTINGS_FILE)
    return settings.get("maintenance", False)

def set_maintenance_mode(status: bool):
    settings = load_data(SETTINGS_FILE)
    settings["maintenance"] = status
    save_data(SETTINGS_FILE, settings)

# Черный список заблокированных пользователей
def load_blocked():
    data = load_data(BLOCKED_FILE)
    if isinstance(data, list):
        return set(data)
    return set()

def is_user_blocked(user_id):
    return user_id in load_blocked()

def set_user_blocked(user_id, blocked: bool):
    blocked_set = load_blocked()
    if blocked:
        blocked_set.add(user_id)
    else:
        blocked_set.discard(user_id)
    save_data(BLOCKED_FILE, list(blocked_set))

# Лимиты генераций
raw_limits = load_data(LIMITS_FILE)
user_image_data = {}
for k, v in raw_limits.items():
    if isinstance(v, dict):
        user_image_data[int(k)] = v
    else:
        user_image_data[int(k)] = {"balance": v, "last_date": str(date.today())}

def save_all_limits():
    save_data(LIMITS_FILE, user_image_data)

def get_user_limit_info(user_id):
    today_str = str(date.today())
    if user_id not in user_image_data:
        user_image_data[user_id] = {"balance": 5, "last_date": today_str}
        save_all_limits()
    else:
        data = user_image_data[user_id]
        if data.get("last_date") != today_str:
            data["balance"] = 5
            data["last_date"] = today_str
            save_all_limits()
    return user_image_data[user_id]

def update_user_balance(user_id, new_balance):
    info = get_user_limit_info(user_id)
    info["balance"] = new_balance
    save_all_limits()

def load_users():
    data = load_data(USERS_FILE)
    if isinstance(data, list):
        return set(data)
    return set()

def save_user(user_id):
    users = load_users()
    if user_id not in users:
        users.add(user_id)
        save_data(USERS_FILE, list(users))

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

def get_main_keyboard(is_admin=False):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_start = types.KeyboardButton("🚀 Начать")
    btn_profile = types.KeyboardButton("👤 О себе")
    btn_roles = types.KeyboardButton("🎭 Выбрать роль")
    btn_premium = types.KeyboardButton("⭐ Купить генерации")
    btn_support = types.KeyboardButton("⚠️ Жалоба / Поддержка")
    markup.add(btn_start, btn_profile)
    markup.add(btn_roles, btn_premium)
    markup.add(btn_support)
    
    if is_admin:
        btn_admin = types.KeyboardButton("⚙️ Админ-панель")
        markup.add(btn_admin)
    return markup

def get_admin_panel_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    btn1 = types.KeyboardButton("1. Отправить личное сообщение пользователю")
    btn2 = types.KeyboardButton("2. Заблокировать / Разблокировать пользователя")
    btn3 = types.KeyboardButton("3. Дать 5 попыток на /image генерацию")
    btn_exit = types.KeyboardButton("🚪 Выйти из админ-панели")
    markup.add(btn1, btn2, btn3, btn_exit)
    return markup

def escape_markdown_v2(text):
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    regex = re.compile(f'([{re.escape(escape_chars)}])')
    return regex.sub(r'\\\1', text)

@app.on_event("startup")
def setup_webhook():
    webhook_url = f"https://femelis-bot.onrender.com/{TELEGRAM_TOKEN}"
    bot.remove_webhook()
    bot.set_webhook(url=webhook_url)

@app.post(f"/{TELEGRAM_TOKEN}")
def process_webhook(update: dict):
    update_obj = telebot.types.Update.de_json(update)

    if update_obj.pre_checkout_query:
        bot.answer_pre_checkout_query(update_obj.pre_checkout_query.id, ok=True)
        return {"status": "ok"}

    if update_obj.message and update_obj.message.successful_payment:
        message = update_obj.message
        user_id = message.from_user.id
        
        if is_user_blocked(user_id):
            bot.reply_to(message, "вы заблокированы по нежелательным для администрации случае")
            return {"status": "ok"}

        if is_maintenance_mode() and user_id != ADMIN_CHAT_ID:
            bot.reply_to(message, "БОТ ЗАКРЫТ НА ТЕХНИЧЕСКИЙ ПЕРЕРЫВ")
            return {"status": "ok"}

        payment = message.successful_payment
        if payment.invoice_payload == "buy_5_images":
            info = get_user_limit_info(user_id)
            new_balance = info["balance"] + 5
            update_user_balance(user_id, new_balance)

            response_text = (
                f"🎉 **Оплата прошла успешно\!**\n\n"
                f"Вам зачислено **5 дополнительных генераций** изображений\.\n"
                f"Текущий баланс: `{new_balance}`"
            )
            bot.reply_to(
                message,
                response_text,
                parse_mode=PARSE_MODE,
                reply_markup=get_main_keyboard(user_id == ADMIN_CHAT_ID)
            )
        return {"status": "ok"}

    if update_obj.callback_query:
        call = update_obj.callback_query
        user_id = call.from_user.id
        
        if is_user_blocked(user_id):
            bot.answer_callback_query(call.id, "вы заблокированы по нежелательным для администрации случае", show_alert=True)
            return {"status": "ok"}

        if is_maintenance_mode() and user_id != ADMIN_CHAT_ID:
            bot.answer_callback_query(call.id, "БОТ ЗАКРЫТ НА ТЕХНИЧЕСКИЙ ПЕРЕРЫВ", show_alert=True)
            return {"status": "ok"}

        data = call.data
        if data.startswith("role_"):
            role_key = data.replace("role_", "")
            if role_key in ROLES:
                user_roles[user_id] = role_key
                reset_user_chat(user_id)

                bot.answer_callback_query(call.id, f"Роль изменена!")
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.id,
                    text=f"✅ Успешно установлена роль: **{role_key}**\.\n\nМожете продолжать общение\!",
                    parse_mode=PARSE_MODE
                )
        return {"status": "ok"}

    if update_obj.message and (update_obj.message.text or update_obj.message.photo or update_obj.message.voice):
        message = update_obj.message
        user_id = message.from_user.id

        # Проверка на блокировку
        if is_user_blocked(user_id):
            bot.reply_to(message, "вы заблокированы по нежелательным для администрации случае")
            return {"status": "ok"}

        # Проверка на техперерыв
        if is_maintenance_mode() and user_id != ADMIN_CHAT_ID:
            bot.reply_to(message, "БОТ ЗАКРЫТ НА ТЕХНИЧЕСКИЙ ПЕРЕРЫВ")
            return {"status": "ok"}

        # Управление техработами через команды (для админа)
        if user_id == ADMIN_CHAT_ID and message.text:
            if message.text == "/maintenance on":
                set_maintenance_mode(True)
                bot.reply_to(message, "🛠 Режим технических работ **включен**.")
                return {"status": "ok"}
            elif message.text == "/maintenance off":
                set_maintenance_mode(False)
                bot.reply_to(message, "🚀 Режим технических работ **выключен**, бот снова доступен всем.")
                return {"status": "ok"}

        # --- ОБРАБОТКА АДМИН-ПАНЕЛИ И АВТОРИЗАЦИИ ---
        if user_id == ADMIN_CHAT_ID and message.text:
            state = user_states.get(user_id)

            if message.text == "⚙️ Админ-панель":
                user_states[user_id] = "waiting_for_login"
                bot.reply_to(message, "🔐 Введите логин администратора:", reply_markup=types.ReplyKeyboardRemove())
                return {"status": "ok"}

            elif state == "waiting_for_login":
                if message.text == "sadbaby":
                    user_states[user_id] = "waiting_for_password"
                    bot.reply_to(message, "🔑 Логин верный. Введите пароль администратора:")
                else:
                    user_states[user_id] = "normal"
                    bot.reply_to(message, "❌ Неверный логин. Авторизация отменена.", reply_markup=get_main_keyboard(True))
                return {"status": "ok"}

            elif state == "waiting_for_password":
                if message.text == "hatemylife":
                    user_states[user_id] = "admin_logged_in"
                    bot.reply_to(message, "✅ **Успешный вход в панель управления пользователями\!**\n\nВыберите действие ниже:", parse_mode=PARSE_MODE, reply_markup=get_admin_panel_keyboard())
                else:
                    user_states[user_id] = "normal"
                    bot.reply_to(message, "❌ Неверный пароль. Авторизация отменена.", reply_markup=get_main_keyboard(True))
                return {"status": "ok"}

            elif state == "admin_logged_in":
                if message.text == "🚪 Выйти из админ-панели":
                    user_states[user_id] = "normal"
                    bot.reply_to(message, "🚪 Выход из админ-панели выполнен.", reply_markup=get_main_keyboard(True))
                    return {"status": "ok"}

                elif message.text == "1. Отправить личное сообщение пользователю":
                    user_states[user_id] = "admin_send_msg_id"
                    bot.reply_to(message, "✍️ Введите **ID пользователя**, которому хотите отправить сообщение:")
                    return {"status": "ok"}

                elif message.text == "2. Заблокировать / Разблокировать пользователя":
                    user_states[user_id] = "admin_block_id"
                    bot.reply_to(message, "🛡 Введите **ID пользователя**, которого нужно заблокировать (или разблокировать):")
                    return {"status": "ok"}

                elif message.text == "3. Дать 5 попыток на /image генерацию":
                    user_states[user_id] = "admin_give_limits_id"
                    bot.reply_to(message, "🎨 Введите **ID пользователя**, которому нужно добавить 5 генераций:")
                    return {"status": "ok"}

            elif state == "admin_send_msg_id":
                try:
                    target_id = int(message.text.strip())
                    user_states[user_id] = {"substate": "admin_send_msg_text", "target": target_id}
                    bot.reply_to(message, f"💬 Введите текст сообщения для пользователя `{target_id}`:")
                except ValueError:
                    bot.reply_to(message, "❌ Неверный ID. Введите числовой ID пользователя:")
                return {"status": "ok"}

            elif isinstance(state, dict) and state.get("substate") == "admin_send_msg_text":
                target_id = state["target"]
                text_to_send = message.text
                user_states[user_id] = "admin_logged_in"
                try:
                    bot.send_message(target_id, f"💬 **Сообщение от администрации:**\n\n{text_to_send}")
                    bot.reply_to(message, f"✅ Сообщение успешно отправлено пользователю `{target_id}`!", reply_markup=get_admin_panel_keyboard())
                except Exception as e:
                    bot.reply_to(message, f"❌ Ошибка отправки: {e}", reply_markup=get_admin_panel_keyboard())
                return {"status": "ok"}

            elif state == "admin_block_id":
                try:
                    target_id = int(message.text.strip())
                    user_states[user_id] = "admin_logged_in"
                    currently_blocked = is_user_blocked(target_id)
                    set_user_blocked(target_id, not currently_blocked)
                    
                    status_text = "разблокирован ✅" if currently_blocked else "заблокирован 🚫"
                    bot.reply_to(message, f"✅ Пользователь `{target_id}` теперь **{status_text}**.", reply_markup=get_admin_panel_keyboard())
                except ValueError:
                    bot.reply_to(message, "❌ Неверный ID. Попробуйте снова или выберите пункт меню:")
                return {"status": "ok"}

            elif state == "admin_give_limits_id":
                try:
                    target_id = int(message.text.strip())
                    user_states[user_id] = "admin_logged_in"
                    
                    info = get_user_limit_info(target_id)
                    new_balance = info["balance"] + 5
                    update_user_balance(target_id, new_balance)
                    
                    bot.reply_to(message, f"✅ Пользователю `{target_id}` успешно начислено 5 генераций. Новый баланс: `{new_balance}`.", reply_markup=get_admin_panel_keyboard())
                except ValueError:
                    bot.reply_to(message, "❌ Неверный ID. Попробуйте снова или выберите пункт меню:")
                return {"status": "ok"}

        # Обработка текста обычных пользователей
        if message.text:
            user_text = message.text
            save_user(user_id)

            first_name = message.from_user.first_name or ""
            last_name = message.from_user.last_name or ""
            username = message.from_user.username
            language_code = message.from_user.language_code or "не указан"

            full_name = f"{first_name} {last_name}".strip()
            user_tag = f"@{username}" if username else "нет юзернейма"

            if user_text == "🚀 Начать" or user_text.startswith("/start"):
                user_states[user_id] = "normal"
                reset_user_chat(user_id)

                welcome_text = (
                    f"👋 **Привет\!** Я твой ИИ\-ассистент на базе Gemini\.\n\n"
                    f"🎁 Каждой день вам доступно **5 бесплатных генераций** картинок командой `/image`\.\n"
                    f"🎭 Настраивай стиль общения кнопкой **«🎭 Выбрать роль»**\!\n"
                    f"🎨 Я также понимаю голос, фото и помню контекст\."
                )
                bot.reply_to(message, welcome_text, parse_mode=PARSE_MODE, reply_markup=get_main_keyboard(user_id == ADMIN_CHAT_ID))
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

            if user_text == "⭐ Купить генерации" or user_text == "/premium":
                title = "⭐ Пакет: 5 дополнительных генераций"
                description = "Дает право на 5 дополнительных запросов в генераторе изображений /image."
                payload = "buy_5_images"
                currency = "XTR"
                prices = [types.LabeledPrice(label="5 генераций", amount=5)]
                
                try:
                    bot.send_invoice(
                        chat_id=message.chat.id,
                        title=title,
                        description=description,
                        invoice_payload=payload,
                        provider_token="",
                        currency=currency,
                        prices=prices,
                        start_parameter="buy-images"
                    )
                except Exception as e:
                    bot.reply_to(message, f"❌ Ошибка создания счета: {escape_markdown_v2(str(e))}", parse_mode=PARSE_MODE, reply_markup=get_main_keyboard(user_id == ADMIN_CHAT_ID))
                return {"status": "ok"}

            if user_text.startswith("/image "):
                prompt = user_text.replace("/image", "").strip()
                if not prompt:
                    bot.reply_to(message, "⚠️ Пожалуйста, укажите описание для картинки после команды, например:\n`/image cyberpunk cat`", parse_mode=PARSE_MODE)
                    return {"status": "ok"}

                info = get_user_limit_info(user_id)
                current_balance = info["balance"]

                if current_balance <= 0:
                    bot.reply_to(
                        message,
                        "⚠️ У вас закончились бесплатные генерации на сегодня!\n\nОни обновятся завтра, либо вы можете приобрести пакет через кнопку **«⭐ Купить генерации»**.",
                        parse_mode=PARSE_MODE,
                        reply_markup=get_main_keyboard(user_id == ADMIN_CHAT_ID)
                    )
                    return {"status": "ok"}

                try:
                    bot.send_chat_action(message.chat.id, 'upload_photo')
                    new_balance = current_balance - 1
                    update_user_balance(user_id, new_balance)

                    encoded_prompt = urllib.parse.quote(prompt)
                    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"

                    caption_text = (
                        f"🎨 **Запрос:** {escape_markdown_v2(prompt)}\n"
                        f"🎁 **Остаток на сегодня:** `{new_balance}`"
                    )
                    bot.send_photo(
                        message.chat.id,
                        photo=image_url,
                        caption=caption_text,
                        parse_mode=PARSE_MODE,
                        reply_markup=get_main_keyboard(user_id == ADMIN_CHAT_ID)
                    )
                except Exception as e:
                    update_user_balance(user_id, current_balance)
                    bot.reply_to(message, f"❌ Ошибка при генерации изображения: {escape_markdown_v2(str(e))}", parse_mode=PARSE_MODE)
                return {"status": "ok"}

            if user_text == "👤 О себе":
                info = get_user_limit_info(user_id)
                balance = info["balance"]
                profile_text = (
                    f"👤 **Информация о вашем аккаунте:**\n\n"
                    f"🆔 **ID:** `{user_id}`\n"
                    f"📌 **Имя:** {escape_markdown_v2(full_name)}\n"
                    f"🔗 **Username:** {escape_markdown_v2(user_tag)}\n"
                    f"🌐 **Язык Telegram:** `{language_code}`\n"
                    f"🎨 **Доступно генераций сегодня:** `{balance}` из 5\n\n"
                    f"*Примечание: бесплатные генерации обновляются ежедневно\.*"
                )
                bot.reply_to(message, profile_text, parse_mode=PARSE_MODE, reply_markup=get_main_keyboard(user_id == ADMIN_CHAT_ID))
                return {"status": "ok"}

            if user_text == "⚠️ Жалоба / Поддержка":
                user_states[user_id] = "waiting_for_ticket"
                support_text = (
                    "💬 Служба поддержки\n\n"
                    "Опишите вашу проблему или оставьте жалобу одним сообщением, и я передам её администратору."
                )
                bot.reply_to(message, support_text, parse_mode=None, reply_markup=types.ReplyKeyboardRemove())
                return {"status": "ok"}

            if user_states.get(user_id) == "waiting_for_ticket" and user_text:
                user_states[user_id] = "normal"
                admin_message = (
                    f"🚨 Новое обращение в поддержку!\n\n"
                    f"👤 Имя: {full_name}\n"
                    f"🔗 Юзернейм: {user_tag}\n"
                    f"🆔 ID: {user_id}\n"
                    f"💬 Текст: {user_text}\n"
                )
                try:
                    bot.send_message(ADMIN_CHAT_ID, admin_message, parse_mode=None)
                    bot.reply_to(message, "✅ Сообщение успешно отправлено администратору!", reply_markup=get_main_keyboard(user_id == ADMIN_CHAT_ID))
                except Exception as e:
                    bot.reply_to(message, f"❌ Ошибка при отправке: {e}", parse_mode=None)
                return {"status": "ok"}

            try:
                chat = get_user_chat(user_id)
                response = chat.send_message(user_text)
                safe_response_text = escape_markdown_v2(response.text)
                bot.reply_to(message, safe_response_text, parse_mode=PARSE_MODE, reply_markup=get_main_keyboard(user_id == ADMIN_CHAT_ID))
            except Exception as e:
                bot.reply_to(message, f"❌ Ошибка при запросе к нейросети: {escape_markdown_v2(str(e))}", parse_mode=PARSE_MODE)

        # Обработка фото
        elif message.photo:
            save_user(user_id)
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
                bot.reply_to(message, safe_response_text, parse_mode=PARSE_MODE, reply_markup=get_main_keyboard(user_id == ADMIN_CHAT_ID))

                if os.path.exists(temp_filename):
                    os.remove(temp_filename)
            except Exception as e:
                bot.reply_to(message, f"❌ Не удалось обработать изображение: {escape_markdown_v2(str(e))}", parse_mode=PARSE_MODE)

        # Обработка голоса
        elif message.voice:
            save_user(user_id)
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

                safe_response_text = escape_markdown_v2(response.text)
                bot.reply_to(message, f"🎙 *Ответ:*\n\n{safe_response_text}", parse_mode=PARSE_MODE, reply_markup=get_main_keyboard(user_id == ADMIN_CHAT_ID))

                if os.path.exists(temp_audio):
                    os.remove(temp_audio)
            except Exception as e:
                bot.reply_to(message, f"❌ Не удалось обработать голосовое сообщение: {escape_markdown_v2(str(e))}", parse_mode=PARSE_MODE)

    return {"status": "ok"}

@app.get("/")
def index():
    return {"status": "Bot is running!"}

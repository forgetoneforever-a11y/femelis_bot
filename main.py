import os
from dotenv import load_dotenv
import telebot
from google import genai

# Загружаем переменные из файла .env
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Инициализируем бота и клиент Gemini
bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)


@bot.message_handler(func=lambda message: True)
def handle_message(message):
  user_text = message.text
  print(f"Получено сообщение от {message.from_user.first_name}: {user_text}")

  try:
    # Отправляем запрос к модели Gemini 2.5 Flash
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=user_text,
    )
    # Отправляем ответ обратно в Telegram
    bot.reply_to(message, response.text)
  except Exception as e:
    bot.reply_to(message, f"Произошла ошибка при обращении к ИИ: {e}")


if __name__ == "__main__":
  print("Бот запущен и ожидает сообщения...")
  bot.infinity_polling()
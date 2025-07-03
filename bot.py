# bot.py
import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# --- Конфигурация ---
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://batyrai.com")

# Проверяем, что токен задан
if not BOT_TOKEN:
    raise ValueError("Не найден TELEGRAM_BOT_TOKEN в .env файле")

# Создаем объекты бота и диспетчера
bot = Bot(token=BOT_TOKEN, parse_mode="HTML") # Добавляем parse_mode по умолчанию
dp = Dispatcher()

# --- Обработчики команд ---

# Обработчик команды /start
@dp.message(CommandStart())
async def send_welcome(message: types.Message):
    web_app_info = WebAppInfo(url=WEB_APP_URL)
    button = InlineKeyboardButton(text="🛡️ Создать портрет Батыра", web_app=web_app_info)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[button]])
    
    welcome_text = (
        f"👋 Ассалаумағалейкум, {message.from_user.first_name}!\n\n"
        "Я — BatyrAI. Готов превратить ваше фото в портрет легендарного батыра.\n\n"
        "Нажмите кнопку ниже, чтобы начать магию!"
    )
    await message.answer(welcome_text, reply_markup=keyboard)

    # ✅ ДОБАВЛЕНО: Отправляем дополнительное сообщение, чтобы подбодрить пользователя
    await asyncio.sleep(1) # Небольшая задержка для естественности
    await message.answer("Когда приложение откроется, просто загрузите ваше лучшее фото и доверьтесь мне. 😉")

# Обработчик команды /help
@dp.message(Command("help"))
async def send_help(message: types.Message):
    help_text = (
        "<b>Как пользоваться ботом BatyrAI?</b>\n\n"
        "1. Нажмите кнопку <b>'Меню'</b> внизу или введите команду /start.\n"
        "2. В открывшемся приложении загрузите ваше фото.\n"
        "3. Следуйте инструкциям на экране и дождитесь результата (1-2 минуты).\n\n"
        "<b>Требования к фото:</b> лицо должно быть видно чётко, анфас, с хорошим освещением."
    )
    await message.answer(help_text)

# --- Запуск бота ---
async def main():
    print("Бот запущен и готов к работе...")
    # Удаляем старые вебхуки, если они были, на случай если вы переключали режимы
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
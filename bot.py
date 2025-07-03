# bot.py
import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from dotenv import load_dotenv
# ✅ Правильный импорт для настроек по умолчанию
from aiogram.client.default import DefaultBotProperties

# Загружаем переменные окружения
load_dotenv()

# --- Конфигурация ---
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://batyrai.com")

# Проверяем, что токен задан
if not BOT_TOKEN:
    raise ValueError("Не найден TELEGRAM_BOT_TOKEN в .env файле")

# --- Создаем объекты бота и диспетчера ---

# ✅ Новый, правильный способ установки parse_mode по умолчанию
default_properties = DefaultBotProperties(parse_mode="HTML")
bot = Bot(token=BOT_TOKEN, default=default_properties)

dp = Dispatcher()

# --- Обработчики команд ---

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

    await asyncio.sleep(1)
    await message.answer("Когда приложение откроется, просто загрузите ваше лучшее фото и доверьтесь мне. 😉")

@dp.message(Command("help"))
async def send_help(message: types.Message):
    help_text = (
        "<b>Как пользоваться ботом BatyrAI?</b>\n\n"
        "1. Нажмите кнопку <b>'Меню'</b> внизу или введите команду /start.\n"
        "2. В открывшемся приложении загрузите ваше фото.\n"
        "3. Следуйте инструкциям на экране и дождитесь результата (1-2 минуты).\n\n"
        "<b>Требования к фото:</b> лицо должно быть видно чётко, анфас, с хорошим освещением."
    )
    # ✅ Убираем лишний parse_mode, так как он задан по умолчанию
    await message.answer(help_text)

# --- Запуск бота ---
async def main():
    print("Бот запущен и готов к работе...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
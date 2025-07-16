# bot.py
import asyncio
import os
import logging  # <-- Импортируем logging
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from dotenv import load_dotenv
from aiogram.client.default import DefaultBotProperties

# ✅ --- НАЧАЛО ИЗМЕНЕНИЙ ---
# Настраиваем базовую конфигурацию логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
# ✅ --- КОНЕЦ ИЗМЕНЕНИЙ ---


# Загружаем переменные окружения
load_dotenv()

# --- Конфигурация ---
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://batyrai.com")

if not BOT_TOKEN:
    raise ValueError("Не найден TELEGRAM_BOT_TOKEN в .env файле")

# --- 1. Локализация: Словарь с текстами ---
LOCALES = {
    'en': {
        'welcome': "👋 Greetings, {first_name}!\n\nI am BatyrAI. Ready to turn your photo into a portrait of a legendary batyr.\n\nPress the button below to start the magic!",
        'welcome_tip': "When the app opens, just upload your best photo and trust me. 😉",
        'button_create': "🛡️ Create a Batyr Portrait",
        'help': "<b>How to use the BatyrAI bot?</b>\n\n1. Press the <b>'Menu'</b> button below or type the /start command.\n2. In the opened application, upload your photo.\n3. Follow the on-screen instructions and wait for the result (1-2 minutes).\n\n<b>Photo requirements:</b> the face should be clearly visible, full-face, with good lighting.",
    },
    'ru': {
        'welcome': "👋 Ассалаумағалейкум, {first_name}!\n\nЯ — BatyrAI. Готов превратить ваше фото в портрет легендарного батыра.\n\nНажмите кнопку ниже, чтобы начать магию!",
        'welcome_tip': "Когда приложение откроется, просто загрузите ваше лучшее фото и доверьтесь мне. 😉",
        'button_create': "🛡️ Создать портрет Батыра",
        'help': "<b>Как пользоваться ботом BatyrAI?</b>\n\n1. Нажмите кнопку <b>'Меню'</b> внизу или введите команду /start.\n2. В открывшемся приложении загрузите ваше фото.\n3. Следуйте инструкциям на экране и дождитесь результата (1-2 минуты).\n\n<b>Требования к фото:</b> лицо должно быть видно чётко, анфас, с хорошим освещением.",
    },
    'kk': {
        'welcome': "👋 Сәлем, {first_name}!\n\nМен — BatyrAI. Сіздің фотосуретіңізді аты аңызға айналған батырдың портретіне айналдыруға дайынмын.\n\nСиқырды бастау үшін төмендегі батырманы басыңыз!",
        'welcome_tip': "Қосымша ашылғанда, ең жақсы фотосуретіңізді жүктеп, маған сенім артыңыз. 😉",
        'button_create': "🛡️ Батыр портретін жасау",
        'help': "<b>BatyrAI ботын қалай пайдалануға болады?</b>\n\n1. Төмендегі <b>'Мәзір'</b> батырмасын басыңыз немесе /start пәрменін енгізіңіз.\n2. Ашылған қосымшада фотосуретіңізді жүктеңіз.\n3. Экрандағы нұсқауларды орындап, нәтижені күтіңіз (1-2 минут).\n\n<b>Фотосуретке қойылатын талаптар:</b> бет анық, тіке қарап, жақсы жарықтандырылған болуы керек.",
    }
}

# --- 2. Функция-помощник для получения перевода ---
def get_text(key: str, lang_code: str | None) -> str:
    lang = lang_code.split('-')[0] if lang_code else 'en'
    # ✅ Заменяем print на logging для отладки
    logging.info(f"User lang_code: '{lang_code}', used lang: '{lang}' for key: '{key}'")
    return LOCALES.get(lang, LOCALES['en']).get(key, f"<{key}_not_found>")

# --- Создаем объекты бота и диспетчера ---
default_properties = DefaultBotProperties(parse_mode="HTML")
bot = Bot(token=BOT_TOKEN, default=default_properties)
dp = Dispatcher()

# --- 3. Обновленные обработчики команд ---
@dp.message(CommandStart())
async def send_welcome(message: Message):
    lang_code = message.from_user.language_code
    button_text = get_text('button_create', lang_code)
    web_app_info = WebAppInfo(url=WEB_APP_URL)
    button = InlineKeyboardButton(text=button_text, web_app=web_app_info)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[button]])
    welcome_text = get_text('welcome', lang_code).format(first_name=message.from_user.first_name)
    await message.answer(welcome_text, reply_markup=keyboard)
    await asyncio.sleep(1)
    tip_text = get_text('welcome_tip', lang_code)
    await message.answer(tip_text)

@dp.message(Command("help"))
async def send_help(message: Message):
    lang_code = message.from_user.language_code
    help_text = get_text('help', lang_code)
    await message.answer(help_text)

# --- Запуск бота ---
async def main():
    # ✅ Заменяем print на logging.info
    logging.info("Бот запущен и готов к работе...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
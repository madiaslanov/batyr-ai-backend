# Полностью скопируй в файл: error_messages.py

MESSAGES = {
    "auth_header_missing": {
        "ru": "Заголовок X-Telegram-Init-Data отсутствует.",
        "en": "X-Telegram-Init-Data header is missing.",
        "kz": "X-Telegram-Init-Data тақырыбы жоқ."
    },
    "auth_validation_failed": {
        "ru": "Не удалось проверить учетные данные Telegram.",
        "en": "Could not validate Telegram credentials.",
        "kz": "Telegram тіркелгі деректерін тексеру мүмкін болмады."
    },
    "payment_required": {
        "ru": "У вас закончились кредиты на генерацию. Пожалуйста, пополните баланс.",
        "en": "You have run out of generation credits. Please top up your balance.",
        "kz": "Генерацияға арналған несиелеріңіз аяқталды. Балансыңызды толтырыңыз."
    },
    "invalid_file_type": {
        "ru": "Недопустимый тип файла. Пожалуйста, загрузите изображение.",
        "en": "Invalid file type. Please upload an image.",
        "kz": "Жарамсыз файл түрі. Суретті жүктеп салыңыз."
    },
    "task_not_found": {
        "ru": "Задача не найдена.",
        "en": "Task not found.",
        "kz": "Тапсырма табылмады."
    },
    "photo_send_failed": {
        "ru": "Не удалось отправить фото в чат.",
        "en": "Failed to send photo to chat.",
        "kz": "Фотосуретті чатқа жіберу мүмкін болмады."
    },
    "face_not_found": {
        "ru": "Не удалось найти лицо на фото. Попробуйте другое, более четкое изображение.",
        "en": "Could not find a face in the photo. Please try another, clearer image.",
        "kz": "Фотосуретте бет табылмады. Басқа, анығырақ кескінді байқап көріңіз."
    },
    "generation_failed_generic": {
        "ru": "Произошла ошибка во время генерации. Попробуйте позже.",
        "en": "An error occurred during generation. Please try again later.",
        "kz": "Генерация кезінде қате пайда болды. Кейінірек қайталап көріңіз."
    },
    "timeout_error": {
        "ru": "Генерация занимает слишком много времени. Попробуйте позже.",
        "en": "Generation is taking too long. Please try again later.",
        "kz": "Генерация тым көп уақыт алуда. Кейінірек қайталап көріңіз."
    },
    "empty_speech": {
        "ru": "Не удалось распознать речь или вы ничего не сказали.",
        "en": "Could not recognize speech, or you said nothing.",
        "kz": "Сөйлеуді тану мүмкін болмады немесе сіз ештеңе айтпадыңыз."
    },
    "assistant_internal_error": {
        "ru": "Произошла внутренняя ошибка ассистента. Попробуйте позже.",
        "en": "An internal assistant error occurred. Please try again later.",
        "kz": "Көмекшінің ішкі қатесі орын алды. Кейінірек қайталап көріңіз."
    }
}

def get_error_message(key: str, lang: str) -> str:
    """Возвращает переведенное сообщение об ошибке."""
    default_lang = 'ru'
    if key in MESSAGES and lang in MESSAGES[key]:
        return MESSAGES[key][lang]
    elif key in MESSAGES:
        return MESSAGES[key].get(default_lang, "An unknown error occurred.")
    return "An unknown error occurred."
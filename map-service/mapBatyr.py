# app.py

import os
import io
import json
import base64
import logging
import hmac
import hashlib
from urllib.parse import unquote
from datetime import datetime

from flask import Flask, jsonify, abort, request, Response
from flask_cors import CORS
from dotenv import load_dotenv
from pydub import AudioSegment
import azure.cognitiveservices.speech as speechsdk
from openai import AzureOpenAI

# --- 1. Настройка и загрузка переменных ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
load_dotenv()

# Ключи для карты (TTS) и ассистента (STT, LLM, TTS)
SPEECH_KEY = os.getenv("SPEECH_KEY")
SPEECH_REGION = os.getenv("SPEECH_REGION")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
OPENAI_API_VERSION = os.getenv("OPENAI_API_VERSION")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Константы для ассистента
SPEECH_VOICE_NAME = "kk-KZ-DauletNeural"
SPEECH_RECOGNITION_LANGUAGE = "kk-KZ"
SYSTEM_PROMPT = "Сен – тарих пәнінің сарапшысы, Батыр атты AI-көмекшісің. Қысқа, құрметпен және мәні бойынша жауап бер. Отвечай 1-2 предложениями. Сенің міндетің – білім беру."

# --- 2. Проверки и инициализация клиентов ---
# Проверяем наличие всех ключей. Если чего-то не хватает, ассистент работать не будет, но карта - будет.
if not all([SPEECH_KEY, SPEECH_REGION, AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT, OPENAI_API_VERSION, AZURE_OPENAI_DEPLOYMENT_NAME, BOT_TOKEN]):
    logging.warning("Одна или несколько переменных окружения для AI-ассистента не заданы. Эндпоинт /api/ask-assistant может не работать.")

try:
    AZURE_OPENAI_CLIENT = AzureOpenAI(api_key=AZURE_OPENAI_KEY, api_version=OPENAI_API_VERSION, azure_endpoint=AZURE_OPENAI_ENDPOINT)
    logging.info("Клиент Azure OpenAI успешно инициализирован.")
except Exception as e:
    logging.error(f"Не удалось инициализировать клиент Azure OpenAI: {e}")

app = Flask(__name__)
CORS(app)

# --- 3. Загрузка данных для карты (без изменений) ---
DATA_FILE = 'batyrs_data.json'
try:
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        DB_DATA = json.load(f)
    logging.info(f"✅ Данные из файла '{DATA_FILE}' успешно загружены.")
except Exception as e:
    logging.critical(f"❌ КРИТИЧЕСКАЯ ОШИБКА при загрузке данных: {e}", exc_info=True)
    DB_DATA = {}

# --- 4. Эндпоинты для карты (без изменений) ---
@app.route('/api/region/<string:region_id>', methods=['GET'])
def get_region_info(region_id):
    logging.info(f"🐌 Запрос на данные региона: {region_id}")
    region_data = DB_DATA.get(region_id)
    if not region_data:
        return abort(404, description=f"Регион с ID '{region_id}' не найден.")
    return jsonify(region_data)

@app.route('/api/tts', methods=['POST'])
def text_to_speech_azure():
    if not all([SPEECH_KEY, SPEECH_REGION]):
        logging.error("❌ [TTS] Ключи или регион не найдены.")
        return jsonify({"error": "Azure TTS service is not configured."}), 500
    
    data = request.get_json()
    text_to_speak = data.get('text')
    if not text_to_speak:
        return jsonify({"error": "No text provided."}), 400

    logging.info(f"🔊 [TTS] Запрос на озвучку текста: {text_to_speak[:50]}...")
    try:
        speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
        speech_config.speech_synthesis_voice_name = SPEECH_VOICE_NAME
        # Используем MP3 для лучшего сжатия
        speech_config.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3)
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
        result = synthesizer.speak_text_async(text_to_speak).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            logging.info("✅ [TTS] Аудио успешно сгенерировано.")
            return Response(result.audio_data, mimetype='audio/mp3')
        else:
            logging.error(f"❌ [TTS] Ошибка синтеза: {result.cancellation_details}")
            return jsonify({"error": "Speech synthesis failed."}), 500
    except Exception as e:
        logging.error(f"❌ [TTS] Внутренняя ошибка: {e}", exc_info=True)
        return jsonify({"error": "Internal server error during TTS."}), 500


# ✅↓↓↓ НОВЫЙ ЭНДПОИНТ И ЛОГИКА ДЛЯ ГОЛОСОВОГО АССИСТЕНТА ↓↓↓✅

# --- 5. Вспомогательные функции для ассистента ---
def recognize_speech_from_bytes(audio_bytes: bytes) -> str:
    audio_segment = AudioSegment.from_file(io.BytesIO(audio_bytes))
    audio_segment = audio_segment.set_channels(1).set_frame_rate(16000)
    wav_buffer = io.BytesIO()
    audio_segment.export(wav_buffer, format="wav")
    wav_buffer.seek(0)

    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION, speech_recognition_language=SPEECH_RECOGNITION_LANGUAGE)
    stream = speechsdk.audio.PullAudioInputStream(wav_buffer.read())
    audio_config = speechsdk.audio.AudioConfig(stream=stream)
    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
    result = recognizer.recognize_once_async().get()

    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        if not result.text or result.text.isspace(): raise ValueError("Распознан пустой текст.")
        logging.info(f"✅ [Assistant] Распознано: '{result.text}'")
        return result.text
    elif result.reason == speechsdk.ResultReason.NoMatch:
        raise ValueError("Не удалось распознать речь.")
    cancellation_details = result.cancellation_details
    logging.error(f"Ошибка распознавания: {cancellation_details.reason}. Детали: {cancellation_details.error_details}")
    raise RuntimeError(f"Ошибка сервиса распознавания: {cancellation_details.reason}")

def get_answer_from_llm(question: str, history: list) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history + [{"role": "user", "content": question}]
    try:
        response = AZURE_OPENAI_CLIENT.chat.completions.create(model=AZURE_OPENAI_DEPLOYMENT_NAME, messages=messages, temperature=0.7, max_tokens=150)
        if not response.choices or not response.choices[0].message.content:
            logging.warning("Ответ от LLM был отфильтрован.")
            return "Кешіріңіз, менің жауабым мазмұн саясатына байланысты бұғатталды."
        answer = response.choices[0].message.content
        logging.info(f"✅ [Assistant] Ответ от LLM получен: '{answer[:50]}...'")
        return answer
    except Exception as e:
        if "content_filter" in str(e):
             logging.warning(f"Запрос заблокирован фильтром содержимого: {e}")
             return "Кешіріңіз, сұранысыңыз мазмұн саясатына байланысты өңделмеді."
        logging.error(f"🔥 [Assistant] Ошибка при обращении к OpenAI: {e}", exc_info=True)
        raise RuntimeError("Ошибка при обращении к сервису OpenAI.")

def synthesize_speech_for_assistant(text: str) -> bytes:
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    speech_config.speech_synthesis_voice_name = SPEECH_VOICE_NAME
    speech_config.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3)
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    result = synthesizer.speak_text_async(text).get()
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data
    raise RuntimeError(f"Ошибка синтеза речи: {result.cancellation_details.reason}")


# --- 6. Основной эндпоинт для ассистента ---
@app.route('/api/ask-assistant', methods=['POST'])
def ask_assistant():
    init_data = request.headers.get('X-Telegram-Init-Data')
    if not init_data or not BOT_TOKEN:
        return jsonify({"error": "Auth data is missing or server is not configured"}), 401
    try:
        unquoted_init_data = unquote(init_data)
        data_check_string, hash_from_telegram = [], ''
        for item in sorted(unquoted_init_data.split('&')):
            key, value = item.split('=', 1)
            if key == 'hash': hash_from_telegram = value
            else: data_check_string.append(f"{key}={value}")
        data_check_string = "\n".join(data_check_string)
        secret_key = hmac.new("WebAppData".encode(), BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if calculated_hash != hash_from_telegram:
            return jsonify({"error": "Invalid data signature"}), 403
    except Exception as e:
        logging.warning(f"Ошибка валидации Telegram initData: {e}")
        return jsonify({"error": "Could not validate Telegram credentials."}), 403
    
    try:
        if 'audio_file' not in request.files:
            return jsonify({"error": "No audio file part"}), 400
        
        history = json.loads(request.form.get('history_json', '[]'))
        audio_bytes = request.files['audio_file'].read()
        
        logging.info(f"✅ [Assistant] Получен аудиофайл: {len(audio_bytes)} байт.")

        recognized_text = recognize_speech_from_bytes(audio_bytes)
        answer_text = get_answer_from_llm(recognized_text, history)
        answer_audio_bytes = synthesize_speech_for_assistant(answer_text)
        audio_base64 = base64.b64encode(answer_audio_bytes).decode('utf-8')
        
        return jsonify({"userText": recognized_text, "assistantText": answer_text, "audioBase64": audio_base64})
    except ValueError as e:
        logging.warning(f"Ошибка данных от клиента (400): {e}")
        return jsonify({"detail": str(e)}), 400
    except Exception as e:
        logging.error("Непредвиденная ошибка в /api/ask-assistant", exc_info=True)
        return jsonify({"detail": "Произошла непредвиденная внутренняя ошибка ассистента."}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
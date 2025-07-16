# Полностью замените содержимое файла assistant.py

import os
import io
import json
import base64
import logging
import datetime
import hmac
import hashlib
from urllib.parse import unquote
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Security
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
import azure.cognitiveservices.speech as speechsdk
from openai import AzureOpenAI
from typing import List, Dict
from pydub import AudioSegment
from pydantic import BaseModel, Field
from openai import BadRequestError

# --- 1. Настройка логирования ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 2. Загрузка переменных и константы ---
load_dotenv()
SPEECH_KEY = os.getenv("SPEECH_KEY")
SPEECH_REGION = os.getenv("SPEECH_REGION")
SPEECH_VOICE_NAME = "kk-KZ-DauletNeural"
SPEECH_RECOGNITION_LANGUAGE = "kk-KZ"
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
OPENAI_API_VERSION = os.getenv("OPENAI_API_VERSION")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
SYSTEM_PROMPT = "Сен – тарих пәнінің сарапшысы, Батыр атты AI-көмекшісің. Қысқа, құрметпен және мәні бойынша жауап бер. Отвечай 1-2 предложениями. Сенің міндетің – білім беру."

# --- 3. Проверки и инициализация клиентов ---
if not all([SPEECH_KEY, SPEECH_REGION, AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT, OPENAI_API_VERSION, AZURE_OPENAI_DEPLOYMENT_NAME]):
    raise RuntimeError("Одна или несколько переменных окружения Azure не заданы.")

try:
    AZURE_OPENAI_CLIENT = AzureOpenAI(api_key=AZURE_OPENAI_KEY, api_version=OPENAI_API_VERSION, azure_endpoint=AZURE_OPENAI_ENDPOINT)
    logging.info("Клиент Azure OpenAI успешно инициализирован.")
except Exception as e:
    logging.error(f"Не удалось инициализировать клиент Azure OpenAI: {e}")
    raise

# --- 4. Pydantic-модели ---
class AssistantResponse(BaseModel):
    userText: str = Field(..., description="Распознанный текст пользователя.")
    assistantText: str = Field(..., description="Текстовый ответ ассистента.")
    audioBase64: str = Field(..., description="Аудиоответ в формате Base64.")

# --- 5. Приложение FastAPI с условным отключением документации ---
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
fastapi_kwargs = {"title": "Batyr AI Assistant API", "description": "Отдельный сервис для голосового AI-ассистента.", "version": "1.0.0"}
if ENVIRONMENT == "production":
    fastapi_kwargs.update({"docs_url": None, "redoc_url": None, "openapi_url": None})
app = FastAPI(**fastapi_kwargs)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- Секция защиты API через Telegram initData ---
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не задан! Сервис не может быть запущен безопасно.")

telegram_init_data_header = APIKeyHeader(name="X-Telegram-Init-Data", auto_error=False)

# Эта зависимость теперь нужна только для аутентификации
async def get_validated_telegram_data(init_data: str = Security(telegram_init_data_header)):
    if not init_data:
        raise HTTPException(status_code=401, detail="X-Telegram-Init-Data header is missing")
    try:
        unquoted_init_data = unquote(init_data)
        data_check_string, hash_from_telegram = [], ''
        for item in sorted(unquoted_init_data.split('&')):
            key, value = item.split('=', 1)
            if key == 'hash':
                hash_from_telegram = value
            else:
                data_check_string.append(f"{key}={value}")
        data_check_string = "\n".join(data_check_string)
        secret_key = hmac.new("WebAppData".encode(), BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if calculated_hash != hash_from_telegram:
            raise HTTPException(status_code=403, detail="Invalid data signature")
        user_data_str = dict(kv.split('=') for kv in unquoted_init_data.split('&')).get('user', '{}')
        return json.loads(user_data_str)
    except Exception as e:
        logging.warning(f"Ошибка валидации Telegram initData: {e}")
        raise HTTPException(status_code=403, detail="Could not validate Telegram credentials.")


# --- 6. Вспомогательные функции ---
def recognize_speech_from_bytes(audio_bytes: bytes, original_filename: str) -> str:
    logging.info(f"Начало распознавания речи. Получено байтов: {len(audio_bytes)}")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_audio_dir = "temp_audio"
    os.makedirs(temp_audio_dir, exist_ok=True)
    try:
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_bytes))
        audio_segment = audio_segment.set_channels(1).set_frame_rate(16000)
        wav_filepath = os.path.join(temp_audio_dir, f"to_azure_{timestamp}.wav")
        audio_segment.export(wav_filepath, format="wav")
    except Exception as e:
        logging.error(f"🔥 Ошибка конвертации аудио: {e}", exc_info=True)
        raise ValueError("Не удалось обработать аудиофайл.")
    try:
        speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION, speech_recognition_language=SPEECH_RECOGNITION_LANGUAGE)
        audio_config = speechsdk.audio.AudioConfig(filename=wav_filepath)
        recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
        result = recognizer.recognize_once_async().get()
    finally:
        try:
            os.remove(wav_filepath)
        except OSError as e:
            logging.error(f"Не удалось удалить временный файл {wav_filepath}: {e}")
    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        if not result.text or result.text.isspace(): raise ValueError("Распознан пустой текст.")
        logging.info(f"✅ Распознано: '{result.text}'")
        return result.text
    elif result.reason == speechsdk.ResultReason.NoMatch: raise ValueError("Не удалось распознать речь.")
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        logging.error(f"Ошибка распознавания (Canceled): {cancellation_details.reason}. Детали: {cancellation_details.error_details}")
        if cancellation_details.error_code == speechsdk.CancellationErrorCode.AuthenticationFailure:
            raise RuntimeError("Ошибка аутентификации Azure. Проверьте SPEECH_KEY и SPEECH_REGION.")
        raise RuntimeError(f"Ошибка сервиса распознавания: {cancellation_details.reason}")
    raise RuntimeError("Неизвестная ошибка при распознавании речи.")

def get_answer_from_llm(question: str, history: List[Dict[str, str]]) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history + [{"role": "user", "content": question}]
    try:
        response = AZURE_OPENAI_CLIENT.chat.completions.create(model=AZURE_OPENAI_DEPLOYMENT_NAME, messages=messages, temperature=0.7, max_tokens=80)
        if not response.choices or not response.choices[0].message.content:
            logging.warning("Ответ от LLM был отфильтрован content filter'ом (пустой choice).")
            return "Кешіріңіз, менің жауабым мазмұн саясатына байланысты бұғатталды. Басқаша сұрап көріңізші."
        answer = response.choices[0].message.content
        logging.info(f"Ответ от LLM получен: '{answer[:50]}...'")
        return answer
    except BadRequestError as e:
        if e.response and e.response.status_code == 400 and e.body and 'content_filter' in e.body.get('code', ''):
            logging.warning(f"Запрос заблокирован фильтром содержимого Azure: {e.body}")
            return "Кешіріңіз, сұранысыңыз мазмұн саясатына байланысты өңделмеді. Басқаша сұрап көріңізші."
        else:
            logging.error(f"🔥 Ошибка BadRequest при обращении к Azure OpenAI: {e}", exc_info=True)
            raise RuntimeError("Ошибка в запросе к сервису OpenAI.")
    except Exception as e:
        logging.error(f"🔥 Непредвиденная ошибка при обращении к Azure OpenAI: {e}", exc_info=True)
        raise RuntimeError("Ошибка при обращении к сервису OpenAI.")

def synthesize_speech_from_text(text: str) -> bytes:
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    speech_config.speech_synthesis_voice_name = SPEECH_VOICE_NAME
    speech_config.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3)
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    result = synthesizer.speak_text_async(text).get()
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted: return result.audio_data
    raise RuntimeError(f"Ошибка синтеза речи: {result.cancellation_details.reason}")


# --- 7. Финальный эндпоинт - теперь без проверок и лимитов ---
@app.post("/api/ask-assistant", response_model=AssistantResponse, dependencies=[Depends(get_validated_telegram_data)])
async def ask_assistant(audio_file: UploadFile = File(...), history_json: str = Form("[]")):
    """
    Этот эндпоинт теперь полностью бесплатный и безлимитный.
    Проверяется только аутентификация пользователя через Telegram.
    """
    try:
        history = json.loads(history_json) if isinstance(history_json, str) else []
        if not isinstance(history, list): history = []
        
        audio_bytes = await audio_file.read()
        recognized_text = recognize_speech_from_bytes(audio_bytes, audio_file.filename)
        answer_text = get_answer_from_llm(recognized_text, history)
        answer_audio_bytes = synthesize_speech_from_text(answer_text)
        audio_base64 = base64.b64encode(answer_audio_bytes).decode('utf-8')
        
        logging.info("Ассистент успешно ответил пользователю.")
        return AssistantResponse(userText=recognized_text, assistantText=answer_text, audioBase64=audio_base64)

    except ValueError as e:
        logging.warning(f"Ошибка данных от клиента (400): {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.error("Непредвиденная ошибка в /api/ask-assistant", exc_info=True)
        raise HTTPException(status_code=500, detail="Произошла непредвиденная внутренняя ошибка ассистента.")
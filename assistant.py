# assistant.py
import os
import io
import json
import base64
import logging
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import azure.cognitiveservices.speech as speechsdk
from openai import AzureOpenAI
from typing import List, Dict
from pydub import AudioSegment
from pydantic import BaseModel, Field

# --- 1. Настройка логирования ---
# Логирование - это стандарт для продакшена. Оно гибче, чем print().
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# --- 2. Загрузка переменных и константы ---
load_dotenv()

# Конфигурация Azure Speech
SPEECH_KEY = os.getenv("SPEECH_KEY")
SPEECH_REGION = os.getenv("SPEECH_REGION")
SPEECH_VOICE_NAME = "kk-KZ-DauletNeural" # Голос для синтеза
SPEECH_RECOGNITION_LANGUAGE = "kk-KZ"   # Язык распознавания

# Конфигурация Azure OpenAI
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
OPENAI_API_VERSION = os.getenv("OPENAI_API_VERSION")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

# Системный промпт для ассистента
SYSTEM_PROMPT = "Сен – тарих пәнінің сарапшысы, Батыр атты AI-көмекшісің. Қысқа, құрметпен және мәні бойынша жауап бер. Сенің міндетің – білім беру. Пайдаланушымен сұхбат жүргіз."

# --- 3. Проверки и инициализация клиентов ---
if not all([SPEECH_KEY, SPEECH_REGION, AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT, OPENAI_API_VERSION, AZURE_OPENAI_DEPLOYMENT_NAME]):
    raise RuntimeError("Одна или несколько переменных окружения не заданы. Проверьте .env файл.")

try:
    AZURE_OPENAI_CLIENT = AzureOpenAI(
        api_key=AZURE_OPENAI_KEY,
        api_version=OPENAI_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )
    logging.info("Клиент Azure OpenAI успешно инициализирован.")
except Exception as e:
    logging.error(f"Не удалось инициализировать клиент Azure OpenAI: {e}")
    raise

# --- 4. Pydantic-модели для валидации и документации ---
class AssistantResponse(BaseModel):
    userText: str = Field(..., description="Распознанный текст пользователя.")
    assistantText: str = Field(..., description="Текстовый ответ ассистента.")
    audioBase64: str = Field(..., description="Аудиоответ в формате Base64.")


# --- 5. Приложение FastAPI ---
app = FastAPI(
    title="Batyr AI Assistant API",
    description="Отдельный сервис для голосового AI-ассистента.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене лучше указать конкретный домен фронтенда
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- 6. Вспомогательные функции с улучшенным логированием ---

def recognize_speech_from_bytes(audio_bytes: bytes) -> str:
    """Конвертирует аудио-байты и распознает речь с помощью Azure Speech."""
    logging.info(f"Начало распознавания речи. Получено байтов: {len(audio_bytes)}")
    
    if len(audio_bytes) < 1000: # Проверка на почти пустой файл
        raise ValueError("Аудиофайл слишком мал или пуст.")
        
    try:
        # Важно: для этой части на сервере должен быть установлен FFmpeg!
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_bytes))
        logging.info("Аудио успешно загружено в pydub для конвертации.")
        
        audio_segment = audio_segment.set_channels(1).set_frame_rate(16000)
        
        wav_buffer = io.BytesIO()
        audio_segment.export(wav_buffer, format="wav")
        wav_bytes = wav_buffer.getvalue()
        logging.info("Аудио успешно сконвертировано в WAV 16kHz mono.")

    except Exception as e:
        logging.error(f"🔥 Ошибка конвертации аудио с помощью pydub: {e}", exc_info=True)
        raise ValueError("Не удалось обработать аудиофайл. Убедитесь, что FFmpeg установлен на сервере.")

    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION, speech_recognition_language=SPEECH_RECOGNITION_LANGUAGE)
    stream = speechsdk.audio.PushAudioInputStream()
    audio_config = speechsdk.audio.AudioConfig(stream=stream)
    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
    
    stream.write(wav_bytes)
    stream.close()

    result = recognizer.recognize_once_async().get()

    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        if not result.text or result.text.isspace():
            logging.warning("Распознан пустой текст.")
            raise ValueError("Распознан пустой текст.")
        logging.info(f"Распознано: '{result.text}'")
        return result.text
    elif result.reason == speechsdk.ResultReason.NoMatch:
        logging.warning("Речь не распознана (NoMatch).")
        raise ValueError("Не удалось распознать речь.")
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        logging.error(f"Ошибка распознавания (Canceled): {cancellation_details.reason}. Детали: {cancellation_details.error_details}")
        raise RuntimeError(f"Ошибка сервиса распознавания: {cancellation_details.reason}")
    
    raise RuntimeError("Неизвестная ошибка при распознавании речи.")


def get_answer_from_llm(question: str, history: List[Dict[str, str]]) -> str:
    """Получает ответ от языковой модели Azure OpenAI."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history + [{"role": "user", "content": question}]
    logging.info(f"Отправка запроса в Azure OpenAI с {len(messages)} сообщениями.")
    
    try:
        response = AZURE_OPENAI_CLIENT.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=messages,
            temperature=0.7,
            max_tokens=150
        )
        answer = response.choices[0].message.content
        logging.info(f"Ответ от LLM получен: '{answer[:50]}...'")
        return answer
    except Exception as e:
        logging.error(f"🔥 Ошибка при обращении к Azure OpenAI: {e}", exc_info=True)
        # Пробрасываем ошибку выше, чтобы эндпоинт вернул корректный статус 500
        raise RuntimeError("Ошибка при обращении к сервису OpenAI.")


def synthesize_speech_from_text(text: str) -> bytes:
    """Синтезирует речь из текста с помощью Azure Speech."""
    logging.info(f"Начало синтеза речи для текста: '{text[:50]}...'")
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    speech_config.speech_synthesis_voice_name = SPEECH_VOICE_NAME
    speech_config.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3)
    
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    result = synthesizer.speak_text_async(text).get()
    
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        logging.info(f"Синтез речи успешно завершен. Размер аудио: {len(result.audio_data)} байт.")
        return result.audio_data
    
    cancellation_details = result.cancellation_details
    logging.error(f"Ошибка синтеза речи: {cancellation_details.reason}. Детали: {cancellation_details.error_details}")
    raise RuntimeError(f"Ошибка сервиса синтеза речи: {cancellation_details.reason}")


# --- 7. Финальный эндпоинт с улучшенной обработкой ошибок ---
@app.post("/api/ask-assistant", response_model=AssistantResponse)
async def ask_assistant(
    audio_file: UploadFile = File(...),
    history_json: str = Form("[]")
):
    try:
        try:
            history = json.loads(history_json)
            if not isinstance(history, list):
                history = []
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Неверный формат JSON в поле history_json.")

        audio_bytes = await audio_file.read()
        
        # Шаг 1: Распознать речь
        recognized_text = recognize_speech_from_bytes(audio_bytes)
        
        # Шаг 2: Получить ответ от LLM
        answer_text = get_answer_from_llm(recognized_text, history)
        
        # Шаг 3: Синтезировать аудиоответ
        answer_audio_bytes = synthesize_speech_from_text(answer_text)

        # Шаг 4: Подготовить ответ
        audio_base64 = base64.b64encode(answer_audio_bytes).decode('utf-8')

        return AssistantResponse(
            userText=recognized_text,
            assistantText=answer_text,
            audioBase64=audio_base64
        )

    except ValueError as e:
        # Ошибки, связанные с неверными данными от клиента (пустое аудио, нераспознанная речь)
        logging.warning(f"Ошибка данных от клиента (400): {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Все остальные, непредвиденные ошибки
        logging.error("Произошла непредвиденная ошибка в эндпоинте /api/ask-assistant", exc_info=True)
        raise HTTPException(status_code=500, detail="Произошла непредвиденная внутренняя ошибка ассистента.")
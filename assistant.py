# assistant.py
import os
import io
import json
import base64
import traceback
import uuid  # <-- Импорт для создания уникальных имен файлов
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import azure.cognitiveservices.speech as speechsdk
from openai import AzureOpenAI
from typing import List
from pydub import AudioSegment

# Загружаем переменные окружения
load_dotenv()

# --- Конфигурация Azure ---
SPEECH_KEY = os.getenv("SPEECH_KEY")
SPEECH_REGION = os.getenv("SPEECH_REGION")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

# --- Проверки и клиенты ---
if not (SPEECH_KEY and SPEECH_REGION):
    raise RuntimeError("Не найдены SPEECH_KEY или SPEECH_REGION в .env файле")
if not os.getenv("AZURE_OPENAI_KEY"):
    raise RuntimeError("Не найден AZURE_OPENAI_KEY в .env файле")

AZURE_OPENAI_CLIENT = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version=os.getenv("OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)

# --- Приложение FastAPI для ассистента ---
app = FastAPI(
    title="Batyr AI Assistant API",
    description="Отдельный сервис для голосового AI-ассистента."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Вспомогательные функции ---

# ✅ ФИНАЛЬНАЯ ВЕРСИЯ ФУНКЦИИ РАСПОЗНАВАНИЯ С МАКСИМАЛЬНО НАДЕЖНОЙ КОНВЕРТАЦИЕЙ
def recognize_speech_from_bytes(audio_bytes: bytes) -> str:
    request_id = str(uuid.uuid4())
    input_filepath = f"/app/debug_audio/{request_id}_input.webm"
    output_filepath = f"/app/debug_audio/{request_id}_converted.wav"
    
    try:
        # 1. Сначала сохраняем полученные байты во временный файл
        with open(input_filepath, "wb") as f:
            f.write(audio_bytes)
        print(f"Сохранен входящий файл: {input_filepath}, размер: {len(audio_bytes)} байт")

        # 2. Говорим pydub загрузить аудио из этого файла. Это самый надежный способ.
        audio_segment = AudioSegment.from_file(input_filepath)

        # 3. Конвертируем в нужный формат: WAV, 16kHz, моно
        audio_segment = audio_segment.set_channels(1).set_frame_rate(16000)

        # 4. Экспортируем сконвертированный файл на диск
        audio_segment.export(output_filepath, format="wav")
        
        # 5. Читаем байты из уже готового, чистого WAV-файла
        with open(output_filepath, "rb") as f:
            wav_bytes = f.read()
        print(f"Сконвертировано в WAV: {output_filepath}, размер: {len(wav_bytes)} байт")

    except Exception as e:
        print(f"🔥 Ошибка на этапе конвертации аудио: {e}")
        raise ValueError("Не удалось обработать аудиофайл.")
    finally:
        # 6. Убираем за собой временные файлы в любом случае
        if os.path.exists(input_filepath): os.remove(input_filepath)
        if os.path.exists(output_filepath): os.remove(output_filepath)

    # 7. Работаем с Azure SDK, передавая ему чистые WAV-байты
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION, speech_recognition_language="kk-KZ")
    stream = speechsdk.audio.PushAudioInputStream()
    audio_config = speechsdk.audio.AudioConfig(stream=stream)
    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
    
    stream.write(wav_bytes)
    stream.close() 

    result = recognizer.recognize_once_async().get()

    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        print(f"Распознано: '{result.text}'")
        if not result.text or result.text.isspace():
             raise ValueError("Распознан пустой текст.")
        return result.text
    elif result.reason == speechsdk.ResultReason.NoMatch:
        raise ValueError("Не удалось распознать речь.")
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            print(f"Код ошибки: {cancellation_details.error_details}")
        raise RuntimeError(f"Ошибка распознавания: {cancellation_details.reason}")
    raise RuntimeError(f"Неизвестный результат распознавания: {result.reason}")

def get_answer_from_llm(question: str, history: List[dict]) -> str:
    system_prompt = "Сен – тарих пәнінің сарапшысы, Батыр атты AI-көмекшісің. Қысқа, құрметпен және мәні бойынша жауап бер. Сенің міндетің – білім беру. Пайдаланушымен сұхбат жүргіз."
    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": question}]
    try:
        response = AZURE_OPENAI_CLIENT.chat.completions.create(model=AZURE_OPENAI_DEPLOYMENT_NAME, messages=messages, temperature=0.7, max_tokens=150)
        answer = response.choices[0].message.content
        print(f"Ответ от LLM: '{answer}'")
        return answer
    except Exception as e:
        print(f"🔥 Ошибка при обращении к Azure OpenAI: {e}")
        return "Кешіріңіз, менде ішкі қате пайда болды."

def synthesize_speech_from_text(text: str) -> bytes:
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    speech_config.speech_synthesis_voice_name = "kk-KZ-DauletNeural"
    speech_config.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3)
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    result = synthesizer.speak_text_async(text).get()
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data
    raise RuntimeError(f"Ошибка синтеза речи: {result.cancellation_details.reason}")


# --- ФИНАЛЬНЫЙ, РАБОЧИЙ ЭНДПОИНТ ---
@app.post("/api/ask-assistant")
async def ask_assistant(audio_file: UploadFile = File(...), history_json: str = Form("[]")):
    try:
        history = json.loads(history_json)
        if not isinstance(history, list):
            history = []
        audio_bytes = await audio_file.read()
        recognized_text = recognize_speech_from_bytes(audio_bytes)
        answer_text = get_answer_from_llm(recognized_text, history)
        answer_audio_bytes = synthesize_speech_from_text(answer_text)
        audio_base64 = base64.b64encode(answer_audio_bytes).decode('utf-8')
        return JSONResponse(content={"userText": recognized_text, "assistantText": answer_text, "audioBase64": audio_base64})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Произошла непредвиденная ошибка ассистента.")
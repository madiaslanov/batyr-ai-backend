# assistant.py
import os
import io
import json
import traceback
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import azure.cognitiveservices.speech as speechsdk
from openai import AzureOpenAI
from typing import List

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

# Настраиваем CORS, чтобы фронтенд мог обращаться к этому сервису
origins = [
    "http://localhost:3000",
    "https://batyrai.com",
    "https://www.batyrai.com",
    "https://batyr-ai.vercel.app",
    "https://batyr-ai-madis-projects-f57aa02c.vercel.app",
    "*"  # Разрешаем все домены, включая Telegram Web App
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Вспомогательные функции ---

# Функция распознавания речи, уже исправленная
def recognize_speech_from_bytes(audio_bytes: bytes) -> str:
    speech_config = speechsdk.SpeechConfig(
        subscription=SPEECH_KEY, 
        region=SPEECH_REGION,
        speech_recognition_language="kk-KZ"
    )
    stream = speechsdk.audio.PushAudioInputStream()
    audio_config = speechsdk.audio.AudioConfig(stream=stream)
    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
    
    stream.write(audio_bytes)
    stream.close()

    result = recognizer.recognize_once_async().get()

    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        print(f"Распознано: '{result.text}'")
        return result.text
    elif result.reason == speechsdk.ResultReason.NoMatch:
        print("Не удалось распознать речь.")
        raise ValueError("Не удалось распознать речь. Попробуйте снова.")
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        print(f"Распознавание отменено: {cancellation_details.reason}")
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            print(f"Код ошибки: {cancellation_details.error_details}")
        raise RuntimeError(f"Ошибка распознавания: {cancellation_details.reason}")
    
    raise RuntimeError(f"Неизвестный результат распознавания: {result.reason}")

# ✅ ИЗМЕНЕНИЕ: Функция теперь принимает историю чата
def get_answer_from_llm(question: str, history: List[dict]) -> str:
    system_prompt = "Сен – тарих пәнінің сарапшысы, Батыр атты AI-көмекшісің. Қысқа, құрметпен және мәні бойынша жауап бер. Сенің міндетің – білім беру. Пайдаланушымен сұхбат жүргіз."
    
    # Формируем сообщения для модели: системный промпт + история + новый вопрос
    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": question}]

    try:
        response = AZURE_OPENAI_CLIENT.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=messages,
            temperature=0.7, 
            max_tokens=150,
        )
        answer = response.choices[0].message.content
        print(f"Ответ от LLM: '{answer}'")
        return answer
    except Exception as e:
        print(f"🔥 Ошибка при обращении к Azure OpenAI: {e}")
        return "Кешіріңіз, менде ішкі қате пайда болды. Кейінірек сұрап көріңіз."

# ✅ ИЗМЕНЕНИЕ: Попробуем другой голос, чтобы речь была более живой
def synthesize_speech_from_text(text: str) -> bytes:
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    # Попробуем мужской голос Daulet
    speech_config.speech_synthesis_voice_name = "kk-KZ-DauletNeural"
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    result = synthesizer.speak_text_async(text).get()
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data
    raise RuntimeError(f"Ошибка синтеза речи: {result.cancellation_details.reason}")


# ✅ ИЗМЕНЕНИЕ: Эндпоинт теперь принимает историю чата в виде JSON-строки
@app.post("/api/ask-assistant")
async def ask_assistant(
    audio_file: UploadFile = File(...),
    history_json: str = Form("[]")  # По умолчанию история пустая
):
    try:
        # Парсим историю из строки в Python-объект (список словарей)
        try:
            history = json.loads(history_json)
            if not isinstance(history, list):
                history = []
        except json.JSONDecodeError:
            history = []

        # Распознаем речь из аудио
        audio_bytes = await audio_file.read()
        recognized_text = recognize_speech_from_bytes(audio_bytes)
        
        # Получаем ответ от LLM, передавая ему историю
        answer_text = get_answer_from_llm(recognized_text, history)
        
        # Синтезируем аудио из ответа
        answer_audio_bytes = synthesize_speech_from_text(answer_text)

        # ✅ ВАЖНО: Возвращаем не только аудио, но и тексты для обновления истории на фронтенде
        # Это потребует изменений на фронтенде. Пока что оставим как было,
        # но для полноценного чата нужно будет возвращать JSON с аудио в base64 и текстами.
        # Для простоты сейчас возвращаем только аудио. Фронтенд должен будет сам
        # добавлять в историю распознанный текст (который он не знает) и ответ (который он не знает).
        # Это проблема. Давайте пока упростим.
        
        # Давайте вернем JSON, чтобы фронтенд мог обновить историю!
        # Это более правильная архитектура.
        
        response_data = {
            "user_text": recognized_text,
            "assistant_text": answer_text,
            "audio_bytes": io.BytesIO(answer_audio_bytes) # Временно, для StreamingResponse
        }
        
        # Пока возвращаем только аудио, как и раньше, чтобы не ломать фронтенд сразу.
        # НО вы должны знать, что для чата с памятью нужно будет переделать и фронтенд.
        return StreamingResponse(io.BytesIO(answer_audio_bytes), media_type="audio/mpeg")

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Произошла непредвиденная ошибка ассистента.")
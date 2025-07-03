# assistant.py
import os
import io
import traceback
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import azure.cognitiveservices.speech as speechsdk
from openai import AzureOpenAI

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
    "https://batyr-ai-madis-projects-f57aa02c.vercel.app"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Вспомогательные функции ---
def recognize_speech_from_bytes(audio_bytes: bytes) -> str:
    speech_config = speechsdk.SpeechConfig(
        subscription=SPEECH_KEY, 
        region=SPEECH_REGION,
        speech_recognition_language="kk-KZ"
    )

    # ✅ ИЗМЕНЕНИЕ ЗДЕСЬ
    # Создаем AudioConfig, который работает с потоком байтов в памяти.
    # Это правильный способ для Azure Speech SDK.
    stream = speechsdk.audio.PushAudioInputStream()
    audio_config = speechsdk.audio.AudioConfig(stream=stream)
    
    # Создаем распознаватель с новой конфигурацией
    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
    
    # "Скармливаем" наши байты в поток
    stream.write(audio_bytes)
    stream.close() # Важно закрыть поток, чтобы SDK знало, что аудио закончилось

    # Распознаем
    result = recognizer.recognize_once_async().get()

    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        print(f"Распознано: '{result.text}'")
        return result.text
    elif result.reason == speechsdk.ResultReason.NoMatch:
        # Этот случай теперь менее вероятен, но оставим для надежности
        print("Не удалось распознать речь.")
        raise ValueError("Не удалось распознать речь. Попробуйте снова.")
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        print(f"Распознавание отменено: {cancellation_details.reason}")
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            print(f"Код ошибки: {cancellation_details.error_details}")
        raise RuntimeError(f"Ошибка распознавания: {cancellation_details.reason}")
    
    # Добавим обработку других возможных статусов
    raise RuntimeError(f"Неизвестный результат распознавания: {result.reason}")


def get_answer_from_llm(question: str) -> str:
    # ... (код этой функции остается без изменений) ...
    system_prompt = "Ты — AI-ассистент, эксперт по истории Казахстана. Отвечай кратко, уважительно и по-существу. Твоя задача — просвещать."
    try:
        response = AZURE_OPENAI_CLIENT.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[ {"role": "system", "content": system_prompt}, {"role": "user", "content": question} ],
            temperature=0.7, max_tokens=150,
        )
        answer = response.choices[0].message.content
        print(f"Ответ от LLM: '{answer}'")
        return answer
    except Exception as e:
        print(f"🔥 Ошибка при обращении к Azure OpenAI: {e}")
        return "К сожалению, у меня возникла внутренняя ошибка. Попробуйте спросить позже."


def synthesize_speech_from_text(text: str) -> bytes:
    # ... (код этой функции остается без изменений) ...
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    speech_config.speech_synthesis_voice_name = "kk-KZ-AigulNeural"
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    result = synthesizer.speak_text_async(text).get()
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data
    raise RuntimeError(f"Ошибка синтеза речи: {result.cancellation_details.reason}")


# --- Единственный эндпоинт этого сервиса ---
@app.post("/api/ask-assistant")
async def ask_assistant(audio_file: UploadFile = File(...)):
    try:
        audio_bytes = await audio_file.read()
        recognized_text = recognize_speech_from_bytes(audio_bytes)
        answer_text = get_answer_from_llm(recognized_text)
        answer_audio_bytes = synthesize_speech_from_text(answer_text)
        return StreamingResponse(io.BytesIO(answer_audio_bytes), media_type="audio/mpeg")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Произошла непредвиденная ошибка ассистента.")
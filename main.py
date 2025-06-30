from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel
import azure.cognitiveservices.speech as speechsdk
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class TTSRequest(BaseModel):
    text: str

@app.post("/api/tts")
async def tts_endpoint(data: TTSRequest):
    subscription_key = os.environ.get("AZURE_SPEECH_KEY")
    region = os.environ.get("AZURE_SPEECH_REGION")

    if not subscription_key or not region:
        return Response(status_code=500, content="Azure credentials not found")

    speech_config = speechsdk.SpeechConfig(
        subscription=subscription_key,
        region=region
    )
    speech_config.speech_synthesis_language = "kk-KZ"
    speech_config.speech_synthesis_voice_name = "kk-KZ-SayanaNeural"

    # ❌ НЕ нужно: audio_config = AudioOutputConfig(...)
    # ✅ Просто создаём synthesizer без audio_config
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config)

    result = synthesizer.speak_text_async(data.text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return Response(content=result.audio_data, media_type="audio/mpeg")
    else:
        return Response(status_code=500, content="TTS synthesis failed")

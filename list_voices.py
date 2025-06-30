from google.cloud import texttospeech
from google.oauth2 import service_account

# Укажи путь к JSON-ключу
key_path = "C:/Users/madia/backendApps/batyr-ai-back/tts-key.json"
credentials = service_account.Credentials.from_service_account_file(key_path)

client = texttospeech.TextToSpeechClient(credentials=credentials)

voices = client.list_voices()

for voice in voices.voices:
    if "ru-RU" in voice.language_codes:
        print(f"🎤 Name: {voice.name}")
        print(f"    Gender: {voice.ssml_gender}")
        print(f"    Sample Rate: {voice.natural_sample_rate_hertz} Hz\n")

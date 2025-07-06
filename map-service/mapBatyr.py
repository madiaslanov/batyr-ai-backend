import os
import json
from flask import Flask, jsonify, abort, request, Response
from flask_cors import CORS
# Импортируем SDK от Azure
import azure.cognitiveservices.speech as speechsdk

app = Flask(__name__)
CORS(app)

# --- Настройки Azure Speech Service из переменных окружения ---
# Docker Compose подставит их из вашего .env файла
AZURE_TTS_KEY = os.getenv('AZURE_TTS_KEY')
AZURE_REGION = os.getenv('AZURE_REGION')

# --- Загрузка данных для карты (этот блок остается без изменений) ---
DATA_FILE = 'batyrs_data.json'
try:
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        DB_DATA = json.load(f)
        print(f"✅ Данные из файла '{DATA_FILE}' успешно загружены.")
except Exception as e:
    print(f"❌ КРИТИЧЕСКАЯ ОШИБКА при загрузке данных: {e}")
    exit()

# --- Эндпоинт для получения данных о регионе (остается без изменений) ---
@app.route('/<string:region_id>', methods=['GET'])
def get_region_info(region_id):
    print(f"🐌 Запрос на данные региона: {region_id}")
    region_data = DB_DATA.get(region_id)
    
    if not region_data:
        return abort(404, description=f"Регион с ID '{region_id}' не найден.")
    
    return jsonify(region_data)

# ✅↓↓↓ НОВЫЙ ЭНДПОИНТ ДЛЯ ОЗВУЧКИ ЧЕРЕЗ AZURE ↓↓↓✅
@app.route('/api/tts', methods=['POST'])
def text_to_speech_azure():
    # 1. Проверяем, что сервер правильно сконфигурирован
    if not all([AZURE_TTS_KEY, AZURE_REGION]):
        print("❌ [Azure] Ключи или регион не найдены в переменных окружения.")
        return jsonify({"error": "Azure TTS service is not configured on the server."}), 500

    # 2. Получаем текст из запроса от фронтенда
    data = request.get_json()
    text_to_speak = data.get('text')
    if not text_to_speak:
        return jsonify({"error": "No text provided."}), 400

    print(f"🔊 [Azure] Запрос на озвучку текста: {text_to_speak[:50]}...")

    try:
        # 3. Настраиваем подключение к Azure
        speech_config = speechsdk.SpeechConfig(subscription=AZURE_TTS_KEY, region=AZURE_REGION)
        
        # Указываем, что хотим получить аудиопоток в память, а не в файл или на динамики
        audio_config = speechsdk.audio.AudioOutputConfig(use_default_speaker=False, filename=None)

        # Выбираем голос. Доступны:
        # 'kk-KZ-DauletNeural' (мужской)
        # 'kk-KZ-AigulNeural' (женский)
        speech_config.speech_synthesis_voice_name = 'kk-KZ-DauletNeural'

        # 4. Создаем синтезатор и запрашиваем аудио
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
        result = synthesizer.speak_text_async(text_to_speak).get()

        # 5. Обрабатываем результат
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            print("✅ [Azure] Аудио успешно сгенерировано.")
            # Получаем бинарные данные аудио (в формате WAV)
            audio_data = result.audio_data
            # Отправляем аудиофайл обратно на фронтенд
            return Response(audio_data, mimetype='audio/wav')
        
        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            print(f"❌ [Azure] Синтез отменен: {cancellation_details.reason}")
            if cancellation_details.reason == speechsdk.CancellationReason.Error:
                print(f"❌ [Azure] Детали ошибки: {cancellation_details.error_details}")
            return jsonify({"error": "Speech synthesis canceled.", "details": str(cancellation_details)}), 500

    except Exception as e:
        print(f"❌ [Azure] Внутренняя ошибка при генерации TTS: {e}")
        return jsonify({"error": "Internal server error during Azure TTS generation."}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
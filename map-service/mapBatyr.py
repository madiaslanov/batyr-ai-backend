# app.py

import os
import io
import json
import base64
import logging
import hmac
import hashlib
from urllib.parse import unquote

from flask import Flask, jsonify, abort, request, Response
from flask_cors import CORS
from dotenv import load_dotenv
from pydub import AudioSegment
import azure.cognitiveservices.speech as speechsdk
from openai import AzureOpenAI

# --- 1. Настройка и загрузка переменных ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
load_dotenv()

# Ключи и константы
SPEECH_KEY = os.getenv("SPEECH_KEY")
SPEECH_REGION = os.getenv("SPEECH_REGION")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
OPENAI_API_VERSION = os.getenv("OPENAI_API_VERSION")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

SPEECH_VOICE_NAME_KZ = "kk-KZ-DauletNeural"
SPEECH_VOICE_NAME_RU = "ru-RU-SvetlanaNeural"
SPEECH_VOICE_NAME_EN = "en-US-JennyNeural"

ASSISTANT_RECOGNITION_LANGUAGE = "kk-KZ"
ASSISTANT_SYSTEM_PROMPT = "Сен – тарих пәнінің сарапшысы, Батыр атты AI-көмекшісің. Қысқа, құрметпен және мәні бойынша жауап бер. Отвечай 1-2 предложениями. Сенің міндетің – білім беру."

# --- 2. Проверки и инициализация клиентов ---
if not all([SPEECH_KEY, SPEECH_REGION, AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT, OPENAI_API_VERSION, AZURE_OPENAI_DEPLOYMENT_NAME, BOT_TOKEN]):
    logging.warning("Одна или несколько переменных окружения для AI-сервисов не заданы.")

try:
    AZURE_OPENAI_CLIENT = AzureOpenAI(api_key=AZURE_OPENAI_KEY, api_version=OPENAI_API_VERSION, azure_endpoint=AZURE_OPENAI_ENDPOINT)
    logging.info("Клиент Azure OpenAI успешно инициализирован.")
except Exception as e:
    logging.error(f"Не удалось инициализировать клиент Azure OpenAI: {e}")

app = Flask(__name__)
CORS(app, expose_headers=['Content-Language'])

# --- 3. Загрузка статических данных для Казахстана ---
DB_DATA = {}
LANGUAGES = ['kz', 'ru', 'en']

for lang in LANGUAGES:
    file_path = f'batyrs_data_{lang}.json'
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            DB_DATA[lang] = json.load(f)
        logging.info(f"✅ Данные для языка '{lang}' из файла '{file_path}' успешно загружены.")
    except FileNotFoundError:
        logging.warning(f"⚠️ Файл данных '{file_path}' не найден!")
        DB_DATA[lang] = {}
    except Exception as e:
        logging.error(f"❌ ОШИБКА при загрузке данных для языка '{lang}': {e}", exc_info=True)
        DB_DATA[lang] = {}

# --- 4. Маппинг ID регионов для GPT ---
REGION_ID_TO_NAME_MAP = {
    'ru': { 'RUBEL': 'Белгородская область', 'RUBRY': 'Брянская область', 'RUVLA': 'Владимирская область', 'RUVOR': 'Воронежская область', 'RUIVA': 'Ивановская область', 'RUKLU': 'Калужская область', 'RUKOS': 'Костромская область', 'RUKRS': 'Курская область', 'RULIP': 'Липецкая область', 'RUMOW': 'Москва', 'RUMOS': 'Московская область', 'RUORL': 'Орловская область', 'RURYA': 'Рязанская область', 'RUSMO': 'Смоленская область', 'RUTAM': 'Тамбовская область', 'RUTVE': 'Тверская область', 'RUTUL': 'Тульская область', 'RUYAR': 'Ярославская область', 'RUARK': 'Архангельская область', 'RUVLG': 'Вологодская область', 'RUKGD': 'Калининградская область', 'RUKR': 'Республика Карелия', 'RUKO': 'Республика Коми', 'RULEN': 'Ленинградская область', 'RUMUR': 'Мурманская область', 'RUNEN': 'Ненецкий АО', 'RUNGR': 'Новгородская область', 'RUPSK': 'Псковская область', 'RUSPE': 'Санкт-Петербург', 'RUAD': 'Республика Адыгея', 'RUAST': 'Астраханская область', 'RUVGG': 'Волгоградская область', 'RUKL': 'Республика Калмыкия', 'RUKDA': 'Краснодарский край', 'RUROS': 'Ростовская область', 'RUDA': 'Республика Дагестан', 'RUIN': 'Республика Ингушетия', 'RUKB': 'Кабардино-Балкарская Республика', 'RUKC': 'Карачаево-Черкесская Республика', 'RUSE': 'Республика Северная Осетия — Алания', 'RUSTA': 'Ставропольский край', 'RUCE': 'Чеченская Республика', 'RUBA': 'Республика Башкортостан', 'RUKIR': 'Кировская область', 'RUME': 'Республика Марий Эл', 'RUMO': 'Республика Мордовия', 'RUNIZ': 'Нижегородская область', 'RUORE': 'Оренбургская область', 'RUPNZ': 'Пензенская область', 'RUPER': 'Пермский край', 'RUSAM': 'Самарская область', 'RUSAR': 'Саратовская область', 'RUTA': 'Республика Татарстан', 'RUUD': 'Удмуртская Республика', 'RUULY': 'Ульяновская область', 'RUCU': 'Чувашская Республика', 'RUKGN': 'Курганская область', 'RUSVE': 'Свердловская область', 'RUTYU': 'Тюменская область', 'RUKHM': 'Ханты-Мансийский АО — Югра', 'RUCHE': 'Челябинская область', 'RUYAN': 'Ямало-Ненецкий АО', 'RUAL': 'Республика Алтай', 'RUALT': 'Алтайский край', 'RUIRK': 'Иркутская область', 'RUKEM': 'Кемеровская область', 'RUKYA': 'Красноярский край', 'RUNVS': 'Новосибирская область', 'RUOMS': 'Омская область', 'RUTOM': 'Томская область', 'RUTY': 'Республика Тыва', 'RUKK': 'Республика Хакасия', 'RUAMU': 'Амурская область', 'RUBU': 'Республика Бурятия', 'RUYEV': 'Еврейская АО', 'RUZAB': 'Забайкальский край', 'RUKAM': 'Камчатский край', 'RUMAG': 'Магаданская область', 'RUPRI': 'Приморский край', 'RUSA': 'Республика Саха (Якутия)', 'RUSAK': 'Сахалинская область', 'RUKHA': 'Хабаровский край', 'RUCHU': 'Чукотский АО' },
    'en': { 'GBABD': 'Aberdeenshire', 'GBABE': 'Aberdeen', 'GBAGB': 'Argyll and Bute', 'GBANS': 'Angus', 'GBCLK': 'Clackmannanshire', 'GBDGY': 'Dumfries and Galloway', 'GBDND': 'Dundee', 'GBEAY': 'East Ayrshire', 'GBEDH': 'Edinburgh', 'GBEDU': 'East Dunbartonshire', 'GBELN': 'East Lothian', 'GBELS': 'Eilean Siar', 'GBERW': 'East Renfrewshire', 'GBFAL': 'Falkirk', 'GBFIF': 'Fife', 'GBGLG': 'Glasgow', 'GBHLD': 'Highland', 'GBIVC': 'Inverclyde', 'GBMLN': 'Midlothian', 'GBMRY': 'Moray', 'GBNAY': 'North Ayrshire', 'GBNLK': 'North Lanarkshire', 'GBORK': 'Orkney', 'GBPKN': 'Perthshire and Kinross', 'GBRFW': 'Renfrewshire', 'GBSAY': 'South Ayrshire', 'GBSCB': 'Scottish Borders', 'GBSLK': 'South Lanarkshire', 'GBSTG': 'Stirling', 'GBWDU': 'West Dunbartonshire', 'GBWLN': 'West Lothian', 'GBZET': 'Shetland Islands', 'GBAGY': 'Anglesey', 'GBBGE': 'Bridgend', 'GBBGW': 'Blaenau Gwent', 'GBCAY': 'Caerphilly', 'GBCGN': 'Ceredigion', 'GBCMN': 'Carmarthenshire', 'GBCRF': 'Cardiff', 'GBCWY': 'Conwy', 'GBDEN': 'Denbighshire', 'GBFLN': 'Flintshire', 'GBGWN': 'Gwynedd', 'GBMON': 'Monmouthshire', 'GBMTY': 'Merthyr Tydfil', 'GBNTL': 'Neath Port Talbot', 'GBNWP': 'Newport', 'GBPEM': 'Pembrokeshire', 'GBPOW': 'Powys', 'GBRCT': 'Rhondda Cynon Taff', 'GBSWA': 'Swansea', 'GBTOF': 'Torfaen', 'GBVGL': 'Vale of Glamorgan', 'GBWRX': 'Wrexham', 'GBANT': 'Antrim', 'GBARD': 'Ards', 'GBARM': 'Armagh', 'GBBFS': 'Belfast', 'GBBLA': 'Ballymena', 'GBBLY': 'Ballymoney', 'GBBNB': 'Banbridge', 'GBCKF': 'Carrickfergus', 'GBCGV': 'Craigavon', 'GBCKT': 'Mid Ulster', 'GBCLR': 'Coleraine', 'GBCSR': 'Castlereagh', 'GBDGN': 'Dungannon', 'GBDOW': 'Down', 'GBDRY': 'Derry', 'GBFER': 'Fermanagh', 'GBLMV': 'Limavady', 'GBLRN': 'Larne', 'GBLSB': 'Lisburn', 'GBMFT': 'Magherafelt', 'GBMYL': 'Moyle', 'GBNDN': 'North Down', 'GBNTA': 'Newtownabbey', 'GBNYM': 'Newry and Mourne', 'GBOMH': 'Omagh', 'GBSTB': 'Strabane', 'GBBDF': 'Bedford', 'GBBKM': 'Buckinghamshire', 'GBBRC': 'Bracknell Forest', 'GBCBF': 'Central Bedfordshire', 'GBESS': 'Essex', 'GBESX': 'East Sussex', 'GBHAM': 'Hampshire', 'GBHRT': 'Hertfordshire', 'GBIOW': 'Isle of Wight', 'GBKEN': 'Kent', 'GBLUT': 'Luton', 'GBMDW': 'Medway', 'GBMIK': 'Milton Keynes', 'GBOXF': 'Oxfordshire', 'GBPOR': 'Portsmouth', 'GBRDG': 'Reading', 'GBSLG': 'Slough', 'GBSOS': 'Southend-on-Sea', 'GBSTH': 'Southampton', 'GBSRY': 'Surrey', 'GBTHR': 'Thurrock', 'GBWBK': 'West Berkshire', 'GBWNM': 'Windsor and Maidenhead', 'GBWOK': 'Wokingham', 'GBWSX': 'West Sussex', 'GBBDG': 'Barking and Dagenham', 'GBBNE': 'Barnet', 'GBBEX': 'Bexley', 'GBBEN': 'Brent', 'GBBRY': 'Bromley', 'GBCMD': 'Camden', 'GBCRY': 'Croydon', 'GBEAL': 'Ealing', 'GBENF': 'Enfield', 'GBGRE': 'Greenwich', 'GBHCK': 'Hackney', 'GBHMF': 'Hammersmith and Fulham', 'GBHRY': 'Haringey', 'GBHRW': 'Harrow', 'GBHAV': 'Havering', 'GBHIL': 'Hillingdon', 'GBHNS': 'Hounslow', 'GBISL': 'Islington', 'GBKEC': 'Kensington and Chelsea', 'GBKTT': 'Kingston upon Thames', 'GBLBH': 'Lambeth', 'GBLEW': 'Lewisham', 'GBLND': 'City of London', 'GBMRT': 'Merton', 'GBNWM': 'Newham', 'GBRDB': 'Redbridge', 'GBRIC': 'Richmond upon Thames', 'GBSWK': 'Southwark', 'GBSTN': 'Sutton', 'GBTWH': 'Tower Hamlets', 'GBWFT': 'Waltham Forest', 'GBWND': 'Wandsworth', 'GBWSM': 'Westminster', 'GBBAS': 'Bath and North East Somerset', 'GBBNH': 'Brighton and Hove', 'GBBMH': 'Bournemouth', 'GBBST': 'Bristol', 'GBCON': 'Cornwall', 'GBDEV': 'Devon', 'GBDOR': 'Dorset', 'GBGLS': 'Gloucestershire', 'GBIOS': 'Isles of Scilly', 'GBNSM': 'North Somerset', 'GBPLY': 'Plymouth', 'GBPOL': 'Poole', 'GBSGC': 'South Gloucestershire', 'GBSOM': 'Somerset', 'GBSWD': 'Swindon', 'GBTOB': 'Torbay', 'GBWIL': 'Wiltshire', 'GBBIR': 'Birmingham', 'GBCOV': 'Coventry', 'GBDBY': 'Derbyshire', 'GBDER': 'Derby', 'GBDUD': 'Dudley', 'GBHEF': 'Herefordshire', 'GBLCE': 'Leicester', 'GBLEC': 'Leicestershire', 'GBLIN': 'Lincolnshire', 'GBNTH': 'Northamptonshire', 'GBNTT': 'Nottinghamshire', 'GBNGM': 'Nottingham', 'GBRUT': 'Rutland', 'GBSAW': 'Sandwell', 'GBSHR': 'Shropshire', 'GBSOL': 'Solihull', 'GBSTE': 'Stoke-on-Trent', 'GBSTS': 'Staffordshire', 'GBTFW': 'Telford and Wrekin', 'GBWLL': 'Walsall', 'GBWAR': 'Warwickshire', 'GBWLV': 'Wolverhampton', 'GBWOR': 'Worcestershire', 'GBBBD': 'Blackburn with Darwen', 'GBBNS': 'Barnsley', 'GBBOL': 'Bolton', 'GBBPL': 'Blackpool', 'GBBRD': 'Bradford', 'GBBUR': 'Bury', 'GBCHE': 'Cheshire East', 'GBCHW': 'Cheshire West and Chester', 'GBCLD': 'Calderdale', 'GBCMA': 'Cumbria', 'GBDAL': 'Darlington', 'GBDNC': 'Doncaster', 'GBDUR': 'Durham', 'GBGAT': 'Gateshead', 'GBHAL': 'Halton', 'GBHPL': 'Hartlepool', 'GBKHL': 'Kingston upon Hull', 'GBKIR': 'Kirklees', 'GBKWL': 'Knowsley', 'GBLAN': 'Lancashire', 'GBLDS': 'Leeds', 'GBLIV': 'Liverpool', 'GBMAN': 'Manchester', 'GBMDB': 'Middlesbrough', 'GBNET': 'Newcastle upon Tyne', 'GBNBL': 'Northumberland', 'GBNEL': 'North East Lincolnshire', 'GBNLN': 'North Lincolnshire', 'GBNTY': 'North Tyneside', 'GBNYK': 'North Yorkshire', 'GBOLD': 'Oldham', 'GBRCC': 'Redcar and Cleveland', 'GBRCH': 'Rochdale', 'GBROT': 'Rotherham', 'GBSLF': 'Salford', 'GBSFT': 'Sefton', 'GBSHF': 'Sheffield', 'GBSHN': 'Merseyside', 'GBSKP': 'Stockport', 'GBSND': 'Sunderland', 'GBSTT': 'Stockton-on-Tees', 'GBSTY': 'South Tyneside', 'GBTAM': 'Tameside', 'GBTRF': 'Trafford', 'GBWGN': 'Wigan', 'GBWKF': 'Wakefield', 'GBWRT': 'Warrington', 'GBYOR': 'York', 'GBCAM': 'Cambridgeshire', 'GBERY': 'East Riding of Yorkshire', 'GBNFK': 'Norfolk', 'GBPTE': 'Peterborough', 'GBSFK': 'Suffolk' }
}

# --- 5. Функция-генератор GPT ---
def generate_region_data_with_gpt(region_name, country_name, hero_type_plural, lang):
    lang_map = {'ru': 'русском', 'en': 'английском', 'kz': 'казахском'}
    language_name = lang_map.get(lang, 'английском')

    prompt = f"""
Ты — историк-эксперт. Твоя задача — сгенерировать краткую историческую справку о регионе.
Я дам тебе название региона, страну и тип героев.
ТЫ ДОЛЖЕН ОТВЕТИТЬ ТОЛЬКО ВАЛИДНЫМ JSON-ОБЪЕКТОМ. Никакого текста до или после JSON.
Структура JSON должна быть ТОЧНО такой:
{{
  "region_name": "{region_name}, {country_name}",
  "main_text": "Краткое (2-3 предложения) введение в историю региона, связанную с его героями.",
  "batyrs": [
    {{
      "name": "Имя героя/рыцаря/богатыря",
      "years": "Годы жизни (примерно, если точные неизвестны)",
      "description": "Краткое описание (2-3 предложения) его деяний, связанных с этим регионом.",
      "image": null
    }}
  ],
  "historical_events": [
    {{
      "name": "Название события",
      "period": "Период или год события",
      "description": "Краткое описание (2-3 предложения) события, связанного с регионом."
    }}
  ]
}}

- Заполни структуру для региона: '{region_name}' в стране '{country_name}'.
- В поле `batyrs` перечисли 2-3 знаковых исторических персонажей (тип: {hero_type_plural}), которые имеют прямое отношение к этому региону.
- В поле `historical_events` укажи 2 ключевых исторических события, связанных с этими героями или регионом.
- В поле `image` всегда ставь `null`.
- Весь ответ, включая ключи и значения в JSON, должен быть на {language_name} языке.
- Будь краток, точен и познавателен.
"""
    logging.info(f"🤖 [GPT] Запрос на генерацию данных для региона: {region_name} на языке: {lang}")
    try:
        response = AZURE_OPENAI_CLIENT.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[{"role": "system", "content": "You are a helpful history expert that responds only in valid JSON format."},
                      {"role": "user", "content": prompt}],
            temperature=0.5,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        logging.info(f"✅ [GPT] JSON-ответ от LLM получен для {region_name}.")
        parsed_json = json.loads(content)
        if "heroes" in parsed_json and "batyrs" not in parsed_json:
            parsed_json["batyrs"] = parsed_json.pop("heroes")
        return parsed_json
    except Exception as e:
        logging.error(f"❌ [GPT] Ошибка при генерации данных: {e}", exc_info=True)
        return None

# --- 6. ОБНОВЛЕННЫЙ ЭНДПОИНТ: Гибридная логика с полной поддержкой языков ---
@app.route('/api/region/<string:region_id>', methods=['GET'])
def get_region_info(region_id):
    theme = request.args.get('theme', 'kz').lower()
    lang = request.headers.get('Accept-Language', 'kz').split(',')[0].lower()
    if lang not in LANGUAGES:
        lang = 'kz'

    logging.info(f"🐌 Запрос на данные. Регион: {region_id}, Тема: {theme}, Язык интерфейса: {lang}")

    # --- Ветвь 1: Карта Казахстана (из файла) ---
    if theme == 'kz':
        lang_data = DB_DATA.get(lang)
        region_data = lang_data.get(region_id.upper()) if lang_data else None
        
        # Если для текущего языка нет данных, пробуем найти на языке по умолчанию (kz)
        if not region_data:
            logging.warning(f"Не найдены данные для {region_id} на языке '{lang}'. Попытка найти на 'kz'.")
            lang_data_fallback = DB_DATA.get('kz', {})
            region_data = lang_data_fallback.get(region_id.upper())
            response_lang = 'kz'
        else:
            response_lang = lang

        if not region_data:
            abort(404, description=f"Регион '{region_id}' не найден ни на одном языке в файлах.")

        response = jsonify(region_data)
        response.headers['Content-Language'] = response_lang
        return response

    # --- Ветвь 2: Карты России и Англии (через GPT) ---
    elif theme in ['ru', 'en']:
        region_name = REGION_ID_TO_NAME_MAP.get(theme, {}).get(region_id.upper())
        if not region_name:
             abort(404, description=f"ID региона '{region_id}' не найден в словаре для темы '{theme}'.")

        # Определяем язык для генерации контента
        gpt_lang = lang if lang in ['ru', 'en'] else ('ru' if theme == 'ru' else 'en')

        # Определяем параметры для промпта в зависимости от языка генерации
        if gpt_lang == 'ru':
            country_name = "Россия" if theme == 'ru' else "Великобритания"
            hero_type = "богатыри и герои" if theme == 'ru' else "рыцари и герои"
        else: # gpt_lang == 'en'
            country_name = "Russia" if theme == 'ru' else "Great Britain"
            hero_type = "heroes and warriors" if theme == 'ru' else "knights and heroes"

        generated_data = generate_region_data_with_gpt(region_name, country_name, hero_type, gpt_lang)
        if not generated_data:
            abort(503, description=f"Не удалось сгенерировать данные для '{region_name}'.")

        response = jsonify(generated_data)
        response.headers['Content-Language'] = gpt_lang
        return response
    
    else:
        abort(400, description=f"Неподдерживаемая тема карты: '{theme}'.")

# --- 7. Эндпоинт для озвучки (Text-to-Speech) ---
@app.route('/api/tts', methods=['POST'])
def text_to_speech_azure():
    if not all([SPEECH_KEY, SPEECH_REGION]):
        return jsonify({"error": "Azure TTS service is not configured."}), 500
    
    data = request.get_json()
    text_to_speak = data.get('text')
    lang_for_tts = request.headers.get('Accept-Language', 'kz').split(',')[0].lower()

    if not text_to_speak:
        return jsonify({"error": "No text provided."}), 400

    if lang_for_tts == 'ru':
        voice_name = SPEECH_VOICE_NAME_RU
    elif lang_for_tts == 'en':
        voice_name = SPEECH_VOICE_NAME_EN
    else:
        voice_name = SPEECH_VOICE_NAME_KZ

    logging.info(f"🔊 [TTS] Запрос на озвучку (язык: {lang_for_tts}, голос: {voice_name}): {text_to_speak[:50]}...")
    try:
        speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
        speech_config.speech_synthesis_voice_name = voice_name
        speech_config.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3)
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
        result = synthesizer.speak_text_async(text_to_speak).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            return Response(result.audio_data, mimetype='audio/mp3')
        else:
            logging.error(f"❌ [TTS] Ошибка синтеза: {result.cancellation_details}")
            return jsonify({"error": "Speech synthesis failed."}), 500
    except Exception as e:
        logging.error(f"❌ [TTS] Внутренняя ошибка: {e}", exc_info=True)
        return jsonify({"error": "Internal server error during TTS."}), 500


# --- 8. Функции и эндпоинт для Голосового ассистента ---
def recognize_speech_from_bytes(audio_bytes: bytes) -> str:
    audio_segment = AudioSegment.from_file(io.BytesIO(audio_bytes))
    audio_segment = audio_segment.set_channels(1).set_frame_rate(16000)
    wav_buffer = io.BytesIO()
    audio_segment.export(wav_buffer, format="wav")
    wav_buffer.seek(0)
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION, speech_recognition_language=ASSISTANT_RECOGNITION_LANGUAGE)
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
    messages = [{"role": "system", "content": ASSISTANT_SYSTEM_PROMPT}] + history + [{"role": "user", "content": question}]
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
    speech_config.speech_synthesis_voice_name = SPEECH_VOICE_NAME_KZ # Ассистент всегда говорит на казахском
    speech_config.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3)
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    result = synthesizer.speak_text_async(text).get()
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data
    raise RuntimeError(f"Ошибка синтеза речи: {result.cancellation_details.reason}")

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
import json
from flask import Flask, jsonify, abort
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DATA_FILE = 'batyrs_data.json'
try:
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        DB_DATA = json.load(f)
        print(f"✅ Данные из файла '{DATA_FILE}' успешно загружены.")
except Exception as e:
    print(f"❌ КРИТИЧЕСКАЯ ОШИБКА при загрузке данных: {e}")
    exit()

@app.route('/api/region/<string:region_id>', methods=['GET'])
def get_region_info(region_id):
    print(f"🐌 Запрос для региона: {region_id}")
    region_data = DB_DATA.get(region_id)
    
    if not region_data:
        return abort(404, description=f"Регион с ID '{region_id}' не найден.")
    
    return jsonify(region_data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
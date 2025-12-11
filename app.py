from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient
from bson.objectid import ObjectId
import json
import google.generativeai as genai
import os
from dotenv import load_dotenv
import requests
import math

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

load_dotenv(".env")

client = MongoClient(os.getenv("MONGO_URI"))
db = client["badminton_db"]
users = db["users"]
trainings = db["trainings"]
trainingplans = db["trainingplans"]
meals = db["meals"]

def get_filtered_trainings(clean_goal):
    # 1) Lọc theo goal (hỗ trợ goal dạng chuỗi hoặc mảng)
    query = {
        "$or": [
            {"goal": clean_goal},
            {"goal": {"$in": [clean_goal]}},
        ]
    }

    filtered = list(trainings.find(query))

    # 2) Fallback nếu số bài tập quá ít (< 10)
    if len(filtered) < 10:
        filtered = list(trainings.find({}))  # fallback lấy tất cả

    return filtered


genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel(os.getenv("MODEL_NAME"))

def save_plan_to_db(plan, training_map):
    doc = {
        "name": plan.get("name", "Lộ trình tập luyện"),
        "description": plan.get("description", ""),
        "goal": plan.get("goal", ""),
        "level": plan.get("level", ""),
        "type": "weekly",
        "isActive": True,
        "planDays": []
    }

    for day_data in plan.get("days", []):
        day = {
            "_id": ObjectId(),
            "day": day_data.get("day", 1),
            "workouts": []
        }

        for w in day_data.get("workouts", []):
            training_name = w.get("trainingName")
            training_id = training_map.get(training_name)

            day["workouts"].append({
                "trainingId": ObjectId(training_id) if training_id else None,
                "time": w.get("time",""),
                "note": w.get("note", ""),
                "order": w.get("order", 0),
                "_id": ObjectId(),
            })

        doc["planDays"].append(day)

    inserted = trainingplans.insert_one(doc)
    return str(inserted.inserted_id)

def generate_training_plans(user_info, trainings_list):
    user_json = json.dumps(user_info, ensure_ascii=False, default=str)
    training_json = json.dumps(trainings_list, ensure_ascii=False)

    raw_goal = user_info.get("goal", "Cải thiện kỹ năng cầu lông")

    if isinstance(raw_goal, list):
        clean_goal = ", ".join([str(item).strip() for item in raw_goal if item])
    elif isinstance(raw_goal, str):
        clean_goal = raw_goal.strip("[]'\" ")
    else:
        clean_goal = "Cải thiện kỹ năng cầu lông"
    if not clean_goal:
        clean_goal = "Cải thiện kỹ năng cầu lông"

    prompt = (
    "Bạn là huấn luyện viên cầu lông chuyên nghiệp. Hãy tạo đúng **3 lộ trình tập luyện 1 tuần** cho người dùng này.\n"
    "Mỗi lộ trình tương ứng với một cấp độ khác nhau:\n"
    "• Lộ trình 1: Cơ bản\n"
    "• Lộ trình 2: Trung bình\n"
    "• Lộ trình 3: Nâng cao\n\n"

    "=== QUY TẮC BẮT BUỘC – KHÔNG ĐƯỢC PHÁ VỠ ===\n"
    "1. Lộ trình Cơ bản    → CHỈ dùng bài tập có trường \"level\": \"Cơ bản\"\n"
    "2. Lộ trình Trung bình → CHỈ dùng bài tập có trường \"level\": \"Trung bình\"\n"
    "3. Lộ trình Nâng cao   → CHỈ dùng bài tập có trường \"level\": \"Nâng cao\"\n"
    "4. Phải tạo ĐÚNG 7 ngày, theo đúng thứ tự từ 1 đến 7 (không được thiếu, không được đảo thứ tự)\n"
    "5. Mỗi ngày phải có TỐI THIỂU 3 bài tập, TỐI ĐA 6 bài tập\n"
    "6. Mọi bài tập bạn chọn BẮT BUỘC PHẢI ĐÚNG THEO MỤC TIÊU CỦA NGƯỜI DÙNG 100%\n"
    "7. Bắt buộc phải có bài tập không để trainingID là null, nếu không có bài tập thì bỏ qua, 1 buổi tập từ 2 đến 4 bài đều được\n"

    "=== MỤC TIÊU CỦA NGƯỜI DÙNG (bắt buộc dùng đúng) ===\n"
    f"{clean_goal}\n\n"

    "### Thông tin người dùng:\n"
    f"{user_json}\n\n"

    "### Danh sách bài tập (chỉ dùng đúng tên trong danh sách này):\n"
    f"{training_json}\n\n"

    "Trả về đúng định dạng JSON sau, KHÔNG thêm bất kỳ chữ nào ngoài JSON:\n"
    "{\n"
    '  "plans": [\n'
    "    {\n"
    '      "name": "Lộ trình Cơ bản – Xây dựng nền tảng",\n'
    '      "description": "Dành cho người mới hoặc ít kinh nghiệm",\n'
    f'      "goal": "{clean_goal}",\n'
    '      "level": "Cơ bản",\n'
    '      "days": [1 đến 7]\n'
    "    },\n"
    "    {\n"
    '      "name": "Lộ trình Trung bình – Tăng tốc độ & sức mạnh",\n'
    '      "description": "Dành cho người đã có nền tảng, muốn tiến bộ rõ rệt",\n'
    f'      "goal": "{clean_goal}",\n'
    '      "level": "Trung bình",\n'
    '      "days": [ ... ]\n'
    "    },\n"
    "    {\n"
    '      "name": "Lộ trình Nâng cao – Hoàn thiện kỹ chiến thuật",\n'
    '      "description": "Dành cho người chơi lâu năm hoặc thi đấu",\n'
    f'      "goal": "{clean_goal}",\n'
    '      "level": "Nâng cao",\n'
    '      "days": [ ... ]\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Mỗi workout phải có đúng 4 trường:\n"
    "- \"trainingName\": tên chính xác trong danh sách\n"
    "- \"note\": ghi chú chi tiết, dễ hiểu\n"
    "- \"time\": giờ bắt đầu tập theo định dạng HH:MM (ví dụ: \"18:00\", \"09:00\", \"20:00\")\n"
    "- \"order\": số thứ tự trong ngày\n\n"
    "Chỉ trả về JSON thuần, không ```json, không giải thích."
)

    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json"
            )
        )
        return response.text
    except Exception as e:
        print("Gemini Error:", e)
        return json.dumps({
            "plans": [],
            "error": "Gemini quota exceeded"
        }, ensure_ascii=False)

@app.route("/recommend/training-plan/<user_id>", methods=["GET"])
def recommend_training_plan(user_id):

    # 1️⃣ Lấy user
    user = users.find_one({"_id": ObjectId(user_id)}, {"passwordHash": 0})
    if not user:
        return jsonify({"error": "User không tồn tại"}), 404

    user["_id"] = str(user["_id"])

    # --- Chuẩn hóa goal ---
    raw_goal = user.get("goal", [])

    if isinstance(raw_goal, list):
        clean_goal = ", ".join([str(g).strip() for g in raw_goal if g])
    elif isinstance(raw_goal, str):
        clean_goal = raw_goal.strip("[]'\" ")
    else:
        clean_goal = ""

    if not clean_goal:
        clean_goal = "Cải thiện kỹ năng cầu lông"

    # --- Lọc bài tập theo goal (đã sửa) ---
    training_docs = get_filtered_trainings(clean_goal)

    trainings_list = []
    training_map = {}

    for t in training_docs:
        name = t.get("title")
        if not name:
            continue

        trainings_list.append({
            "title": name,
            "goal": t.get("goal"),
            "level": t.get("level"),
            "description": t.get("description", ""),
        })

        training_map[name] = str(t["_id"])

    ai_output = generate_training_plans(user, trainings_list)

    try:
        json_output = json.loads(ai_output)
    except Exception:
        return jsonify({
            "error": "AI trả về không đúng JSON",
            "raw": ai_output
        }), 400

    plans = json_output.get("plans", [])

    saved_ids = [save_plan_to_db(p, training_map) for p in plans]

    return jsonify({
        "message": "Đã tạo và lưu 3 lộ trình thành công",
        "planIds": saved_ids,
        "plans": plans
    })


def get_training_list():
    """Lấy danh sách bài tập từ database"""
    training_docs = list(trainings.find({}, {"title": 1, "goal": 1, "level": 1, "description": 1})).limit(30)
    training_list = []
    
    for t in training_docs:
        if t.get("title"):
            training_list.append({
                "name": t.get("title"),
                "goal": t.get("goal", ""),
                "level": t.get("level", ""),
                "description": t.get("description", "")[:100] if t.get("description") else ""
            })
    
    return training_list

def get_meal_list():
    """Lấy danh sách món ăn từ database"""
    meal_docs = list(meals.find({}, {"name": 1, "calories": 1, "goal": 1, "mealType": 1, "description": 1})).limit(30)
    meal_list = []
    
    for m in meal_docs:
        if m.get("name"):
            meal_list.append({
                "name": m.get("name"),
                "calories": m.get("calories", 0),
                "goal": m.get("goal", ""),
                "mealType": m.get("mealType", ""),
                "description": m.get("description", "")[:100] if m.get("description") else ""
            })
    
    return meal_list

def ask_gemini(question: str, training_list: list, meal_list: list, user_info: dict = None) -> str:
    """
    Gửi câu hỏi + dữ liệu bài tập và món ăn cho Gemini AI, trả về text tư vấn về cầu lông
    
    Args:
        question: Câu hỏi của người dùng
        training_list: Danh sách bài tập
        meal_list: Danh sách món ăn
        user_info: Thông tin người dùng (optional)
    """
    
    training_lines = []
    for t in training_list[:20]:  
        level = t.get("level", "Chưa xác định")
        goal = t.get("goal", "Chưa xác định")
        desc = t.get("description", "")
        line = f"- {t['name']} (Trình độ: {level}, Mục tiêu: {goal})"
        if desc:
            line += f" - {desc}"
        training_lines.append(line)
    
    training_text = "\n".join(training_lines) if training_lines else "Chưa có bài tập nào"
    
    meal_lines = []
    for m in meal_list[:15]:  
        calories = m.get("calories", 0)
        goal = m.get("goal", "")
        meal_type = m.get("mealType", "")
        desc = m.get("description", "")
        line = f"- {m['name']} ({meal_type}, {calories} cal, Mục tiêu: {goal})"
        if desc:
            line += f" - {desc}"
        meal_lines.append(line)
    
    meal_text = "\n".join(meal_lines) if meal_lines else "Chưa có món ăn nào"
    
    user_context = ""
    if user_info:
        user_goals = user_info.get("goal", [])
        if isinstance(user_goals, list):
            goals_str = ", ".join([str(g) for g in user_goals if g])
        else:
            goals_str = str(user_goals) if user_goals else ""
        
        user_context = f"""
Thông tin người dùng:
- Tên: {user_info.get('name', 'N/A')}
- Trình độ: {user_info.get('badmintonLevel', 'Chưa xác định')}
- Kinh nghiệm: {user_info.get('badmintonExperience', 'Chưa xác định')}
- Mục tiêu: {goals_str if goals_str else 'Chưa xác định'}
- Chiều cao: {user_info.get('height', 'N/A')} cm
- Cân nặng: {user_info.get('weight', 'N/A')} kg
"""
    user_name = user_info.get("name") if user_info else None
    greeting = f"Chào {user_name}!" if user_name else "Chào bạn!"
    prompt = f"""
Bạn là chatbot tư vấn chuyên nghiệp về cầu lông và dinh dưỡng thể thao cho ứng dụng Badminton App.

Ứng dụng này giúp người dùng:
- Tập luyện cầu lông với các bài tập được cá nhân hóa
- Quản lý dinh dưỡng phù hợp với mục tiêu tập luyện
- Theo dõi tiến độ và lịch tập luyện
- Học kiến thức về kỹ thuật và chiến thuật cầu lông

{user_context if user_context else ""}

Danh sách bài tập hiện có:
{training_text}

Danh sách món ăn hiện có:
{meal_text}

Hướng dẫn trả lời:
- Bắt đầu đoạn chat bằng lời chào: "{greeting}" trong câu trả lời đầu tiên, sau đó trả lời trực tiếp các câu hỏi tiếp theo.
- Chỉ trả lời đúng ý câu hỏi, ngắn gọn và dễ hiểu
- Nếu câu hỏi về bài tập, kế hoạch tập luyện, kỹ thuật cầu lông → tham khảo danh sách bài tập và đưa ra lời khuyên cụ thể
- Nếu câu hỏi về dinh dưỡng, món ăn, calories → tham khảo danh sách món ăn và đưa ra gợi ý phù hợp
- Nếu câu hỏi về cách sử dụng app, tính năng → hướng dẫn cách sử dụng các tính năng trong app
- Nếu câu hỏi về tiến độ, lịch tập → hướng dẫn xem trong phần Schedule và Progress
- Không liệt kê tất cả bài tập hoặc món ăn trừ khi được yêu cầu cụ thể
- Trả lời tự nhiên, thân thiện, không dùng dấu ** hay * để format
- Nếu không biết câu trả lời, hãy thừa nhận và đề xuất liên hệ quản trị viên qua chat hỗ trợ

Khách hàng hỏi: {question}
"""
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Xin lỗi, có lỗi xảy ra khi xử lý câu hỏi của bạn. Vui lòng thử lại sau. ({str(e)})"

@app.route("/chat", methods=["POST"])
def chat():
    """
    Endpoint chat với AI chatbot
    Body: {
        "message": "Câu hỏi của người dùng",
        "userId": "user_id (optional)" - để lấy thông tin người dùng
    }
    """
    data = request.get_json()
    question = data.get("message", "").strip()
    
    if not question:
        return jsonify({"reply": "Xin lỗi, bạn chưa nhập câu hỏi."}), 400
    
    user_info = None
    user_id = data.get("userId")
    if user_id:
        try:
            user = users.find_one({"_id": ObjectId(user_id)}, {"passwordHash": 0})
            if user:
                user["_id"] = str(user["_id"])
                user_info = user
        except Exception as e:
            print(f"Error getting user info: {e}")

    training_list = get_training_list()
    meal_list = get_meal_list()
    
    reply = ask_gemini(question, training_list, meal_list, user_info)

    reply_clean = reply.replace("**", "").replace("*", "").replace("```", "")
    
    return jsonify({"reply": reply_clean})

def calculate_distance(lat1, lon1, lat2, lon2):
    """Tính khoảng cách giữa 2 điểm (km)"""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)

def search_nearby_courts(latitude, longitude):
    """
    Tìm TOP 5 sân cầu lông gần nhất
    
    Args:
        latitude: Vĩ độ
        longitude: Kinh độ
    
    Returns:
        List của 5 sân cầu lông gần nhất
    """
    api_key = os.getenv("HERE_API_KEY")
    
    if not api_key:
        return {"error": "Chưa cấu hình HERE API Key"}
    
    # HERE Discover API
    url = "https://discover.search.hereapi.com/v1/discover"
    
    params = {
        'at': f'{latitude},{longitude}',
        'q': 'badminton court',
        'limit': 10,  # Lấy 10 để có đủ dữ liệu, sau đó filter ra 5
        'apiKey': api_key,
        'lang': 'vi-VN'
    }
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        if 'items' not in data or len(data['items']) == 0:
            # Thử keyword rộng hơn
            params['q'] = 'badminton'
            response = requests.get(url, params=params)
            data = response.json()
        
        courts = []
        for place in data.get('items', []):
            position = place.get('position', {})
            court_lat = position.get('lat')
            court_lng = position.get('lng')
            
            if not court_lat or not court_lng:
                continue
            
            distance = calculate_distance(latitude, longitude, court_lat, court_lng)
            
            address = place.get('address', {})
            full_address = address.get('label', 'N/A')
            
            # Lấy thông tin liên hệ
            contacts = place.get('contacts', [])
            phone = None
            if contacts and contacts[0].get('phone'):
                phone = contacts[0]['phone'][0].get('value')
            
            # Giờ mở cửa
            opening_hours = place.get('openingHours', [])
            is_open = opening_hours[0].get('isOpen') if opening_hours else None
            
            courts.append({
                'id': place.get('id'),
                'name': place.get('title', 'Sân cầu lông'),
                'address': full_address,
                'latitude': court_lat,
                'longitude': court_lng,
                'distance': distance,
                'phone': phone,
                'isOpen': is_open
            })
        
        # Sắp xếp theo khoảng cách và lấy TOP 5
        courts.sort(key=lambda x: x['distance'])
        return courts[:5]
        
    except Exception as e:
        print(f"HERE API Error: {e}")
        return {"error": f"Lỗi khi tìm kiếm: {str(e)}"}

# ========== ENDPOINT ==========

@app.route("/api/nearby-courts", methods=["POST"])
def nearby_courts():
    """
    Tìm TOP 5 sân cầu lông gần nhất
    
    Body:
    {
        "latitude": 10.8231,
        "longitude": 106.6297
    }
    
    Response:
    {
        "success": true,
        "courts": [
            {
                "id": "here:pds:place:...",
                "name": "Sân cầu lông ABC",
                "address": "123 Nguyễn Huệ, Q1, TP.HCM",
                "latitude": 10.8231,
                "longitude": 106.6297,
                "distance": 0.5,
                "phone": "0901234567",
                "isOpen": true
            }
        ]
    }
    """
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "Thiếu dữ liệu"}), 400
    
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    
    if not latitude or not longitude:
        return jsonify({"error": "Thiếu thông tin vị trí (latitude, longitude)"}), 400
    
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except ValueError:
        return jsonify({"error": "Dữ liệu vị trí không hợp lệ"}), 400
    
    courts = search_nearby_courts(latitude, longitude)
    
    if isinstance(courts, dict) and 'error' in courts:
        return jsonify(courts), 500
    
    return jsonify({
        "success": True,
        "userLocation": {
            "latitude": latitude,
            "longitude": longitude
        },
        "totalCourts": len(courts),
        "courts": courts
    })


if __name__ == "__main__":
    app.debug = True
    app.run()

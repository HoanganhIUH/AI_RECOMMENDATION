from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient
from bson.objectid import ObjectId
import json
import google.generativeai as genai
import os
from dotenv import load_dotenv

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

load_dotenv(".env")

client = MongoClient(os.getenv("MONGO_URI"))
db = client["badminton_db"]
users = db["users"]
trainings = db["trainings"]
trainingplans = db["trainingplans"]
meals = db["meals"]



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
    "7. Bắt buộc phải có bài tập không để trainingID là null\n"
    "Tuyệt đối không lấy bài tập từ level khác dù chỉ 1 bài và phải đúng với mục tiêu của người dùng. Nếu thiếu bài thì giảm buổi/thời gian.\n\n"

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

    response = model.generate_content(
    prompt,
    generation_config=genai.types.GenerationConfig(
        response_mime_type="application/json"
    )
)
    return response.text

@app.route("/recommend/training-plan/<user_id>", methods=["GET"])
def recommend_training_plan(user_id):

    # 1️⃣ Lấy user
    user = users.find_one({"_id": ObjectId(user_id)}, {"passwordHash": 0})
    if not user:
        return jsonify({"error": "User không tồn tại"}), 404

    user["_id"] = str(user["_id"])

    training_docs = list(trainings.find({}))
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
    training_docs = list(trainings.find({}, {"title": 1, "goal": 1, "level": 1, "description": 1}))
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
    meal_docs = list(meals.find({}, {"name": 1, "calories": 1, "goal": 1, "mealType": 1, "description": 1}))
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

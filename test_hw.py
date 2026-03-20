import requests
import json

data = {
    "subject": "math",
    "score": 40,
    "improvement_points": "二次方程式の解の公式を覚えましょう",
    "count_basic": 1,
    "count_normal": 1,
    "count_advanced": 0,
    "mode": "quality",
    "details": [
        {
            "question": "x^2 - 4x + 4 = 0を解け",
            "user_answer": "x = 4",
            "correct_answer": "x = 2",
            "is_correct": False
        }
    ]
}

try:
    res = requests.post("http://127.0.0.1:5000/generate_homework", json=data)
    print("STATUS:", res.status_code)
    try:
        print(json.dumps(res.json(), indent=2, ensure_ascii=False))
    except Exception as e:
        print("Not json:", res.text)
except Exception as e:
    print("ERROR:", e)

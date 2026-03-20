import requests
import json

data = {
    "subject": "math",
    "level": "中級",
    "count": 2
}

try:
    res = requests.post("http://127.0.0.1:5000/generate_test", json=data)
    print("STATUS:", res.status_code)
    print(json.dumps(res.json(), indent=2, ensure_ascii=False))
except Exception as e:
    print("ERROR:", e)

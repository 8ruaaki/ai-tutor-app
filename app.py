import os
import json
import re
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
# ※最新のモデル名（gemini-1.5-flash等）に合わせることを推奨します
model = genai.GenerativeModel('gemini-2.5-flash')

app = Flask(__name__)

# スプレッドシート連携
def get_sheet():
    try:
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file('credentials.json', scopes=scopes)
        client = gspread.authorize(creds)
        return client.open_by_key(os.getenv("SPREADSHEET_ID")).sheet1
    except Exception as e:
        return None

# --- 各ページルーティング ---
@app.route('/')
def index(): return render_template('index.html')

@app.route('/test_page')
def test_page(): return render_template('test.html')

@app.route('/report_page')
def report_page(): return render_template('report.html')

@app.route('/homework_page')
def homework_page(): return render_template('homework.html')

# --- API: テスト生成 (1問1回答・長文5問固定) ---
@app.route('/generate_test', methods=['POST'])
def generate_test():
    data = request.json
    subject = data.get('subject', '')
    level = data.get('level', '初級')
    count = int(data.get('count', 5))
    
    is_reading_mode = "長文" in subject

    if is_reading_mode:
        target_count = 5
        prompt = f"""
        単元: {subject} 難易度: {level}
        【構成ルール】
        1. 本文を1つ作成。(必要に応じてタイトルも)
        2. 問題は必ず5問。
        3. 重要：各設問は【必ず4択の選択式】にしてください。
        4. 出力JSON形式を厳守：
        {{
          "passage_title": "..",
          "passage_body": "..",
          "questions": [
            {{
              "question": "問題文",
              "choices": ["選択肢1", "選択肢2", "選択肢3", "選択肢4"],
              "correct_answer": "正解の文字列"
            }}
          ]
        }}
        """
    else:
        target_count = count
        prompt = f"""
        単元: {subject}
        難易度: {level}
        
        【構成ルール】
        1. 【合計 {count} 問】の小テストを作成してください。
        2. 1つの設問（ID）につき、解くべき問題は「絶対に1つだけ」にしてください。(1)(2)などの小問分けは厳禁です。
        3. 記述問題の解答欄は1つしかありません。解答も1つだけにしてください。
        4. 選択式（4択）、空欄補充、記述式をバランスよく混ぜてください。
        
        【数式・表記ルール】
        1. 数式は必ず LaTeX 形式を使用し、$ $ で囲んで出力してください。
           例: $x^2$, $\\frac{{1}}{{2}}$, $\\sqrt{{x}}$, $\\times$, $\\div$
        2. 2乗を ^2 と書くようなプログラミング的表記は禁止です。
        
        【出力JSONフォーマット（厳守）】
        {{
          "questions": [
            {{
              "question": "問題文（数式は$ $で囲む）",
              "choices": ["選択肢1", "選択肢2", "選択肢3", "選択肢4"], 
              "correct_answer": "正解の文字列（選択肢がある場合は、選択肢の中の1つと完全一致させること）"
            }}
          ]
        }}
        ※選択肢がない問題（記述式など）の場合は、"choices": [] と空の配列にしてください。
        ※キー名は必ず "question", "choices", "correct_answer" の3つを使用してください。
        """

    try:
        response = model.generate_content(prompt)
        json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))
            result["is_reading_mode"] = is_reading_mode
            result["questions"] = result["questions"][:target_count]
            return jsonify({"status": "success", **result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# --- API: 採点 ---
# app.py の submit_grading 関数を以下に書き換えてください
@app.route('/submit_grading', methods=['POST'])
def submit_grading():
    data = request.json
    # AIへの指示をより厳密にします
    prompt = f"""
    あなたは厳格な採点官です。以下のデータを正確に採点し、必ず指定されたJSON形式のみを出力してください。
    
    【データ】
    問題: {json.dumps(data['questions'], ensure_ascii=False)}
    ユーザー解答: {json.dumps(data['answers'], ensure_ascii=False)}
    
    【採点ルール】
    1. is_correctは、解答が正解と一致しているか、記述式なら意味が通じればtrueにしてください。
    2. user_answerには「ユーザーが入力した値」を、correct_answerには「本来の正解」を入れてください。
    3. 解説(explanation)は日本語で簡潔に書いてください。
    4. 良かった点(good_points)と改善点(improvement_points)も必ず日本語で出力してください。
    5. 良かった点(good_points)は具体的に4文で書いてください。
    6. 改善点(improvement_points)は具体的に3文で書いてください。

    【出力形式（これ以外の文字は一切出力しないでください）】
    {{
      "score": 点数(0-100),
      "good_points": "...",
      "improvement_points": "...",
      "details": [
        {{"question": "..", "user_answer": "..", "correct_answer": "..", "is_correct": true/false, "explanation": ".."}}
      ]
    }}
    """
    try:
        response = model.generate_content(prompt)
        # AIがJSON以外の文字を混ぜても抽出できるように re.DOTALL を使用
        json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))
            return jsonify({"status": "success", "result": result})
        else:
            return jsonify({"status": "error", "message": "JSON形式の抽出に失敗しました"})
    except Exception as e:
        print(f"Server Error: {e}")
        return jsonify({"status": "error", "message": str(e)})

# --- API: 宿題生成 (修正版) ---
@app.route('/generate_homework', methods=['POST'])
def generate_homework():
    # request.form ではなく request.json を使用してデータを取得
    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "データが空です"})

    subject = data.get('subject', '')
    score = data.get('score', 0)
    improvement = data.get('improvement_points', '')
    
    # JavaScriptから送られた数値を取得
    try:
        n_basic = int(data.get('count_basic', 0))
        n_normal = int(data.get('count_normal', 0))
        n_advanced = int(data.get('count_advanced', 0))
    except (ValueError, TypeError):
        n_basic = n_normal = n_advanced = 0
        
    total_questions = n_basic + n_normal + n_advanced

    # AIへの指示（プロンプト）
    prompt = f"""
あなたはプロの学習教材作成者です。
以下のテスト結果に基づき、無駄な装飾を省いた実戦的な「復習問題シート」を作成してください。

【テスト結果】
- 単元: {subject}
- スコア: {score}点
- 重点強化ポイント: {improvement}

【厳守：問題数ルール】
1. #核心ポイントのまとめ（最重要）
    今回のテスト結果と、単元「{subject}」の本質を突き詰めた解説を書いてください。
    以下の3つの要素を必ず含めること：
    - **【核心ポイント】**: 単元「{subject}」の学習で押さえるべき重要ポイントを簡潔に説明してください。
    - **【今回のあなたの落とし穴】**: 前回の指摘事項「{improvement}」を分析し、なぜそこでミスが起きるのか、どうすれば防げるのかをピンポイントで解説してください。
    - **【プロの解法テクニック】**: 実戦で使えるコツを伝授してください。
2. # 復習トレーニング：以下の問題数を絶対に守ってください。
   - 問1（基礎レベル, 教科書の例題レベル）：必ず {n_basic} 問
   - 問2（標準レベル, 定期テストのレベル）：必ず {n_normal} 問
   - 問3（発展レベル, 入試問題のレベル）：必ず {n_advanced} 問
   - 合計問数：{total_questions} 問
   ※各問題の下には「（解答欄：　　　）」を設けてください。
3. # 【別紙】解答と解説：全問の正答とステップ解説。

【表記ルール】
- 数式は LaTeX 形式を使用し、$ $ で囲んで出力すること。
- 例: $x^2$, $\\frac{{1}}{{2}}$, $\\sqrt{{x}}$, $\\times$, $\\div$
- Markdown形式で出力し、挨拶などの余計な文言は一切含めないでください。
"""
    try:
        response = model.generate_content(prompt)
        return jsonify({"status": "success", "homework_content": response.text})
    except Exception as e:
        print(f"Homework Generation Error: {e}")
        return jsonify({"status": "error", "message": str(e)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/homework')
def homework_route():
    # ここで templates/homework.html を読み込むように指示します
    return render_template('homework.html')

if __name__ == '__main__':
    app.run(debug=True)

       ##- 問1は{c_basic}問、問2は{c_normal}問、問3は{c_advanced}問を出題してください。
       ##- 合計で {int(c_basic) + int(c_normal) + int(c_advanced)} 問の問題を作成してください。
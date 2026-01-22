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
    level = data.get('level', '中級')
    count = int(data.get('count', 5))
    
    is_reading_mode = "長文" in subject

    if is_reading_mode:
        target_count = 5
        prompt = f"""
        単元: {subject} 難易度: {level}
        【構成ルール】
        1. 本文を1つ作成。
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
        3. 選択式（4択）、空欄補充、記述式をバランスよく混ぜてください。
        
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
    5. 良かった点(good_points)は具体的に5文以上で書いてください。
    6. 改善点(improvement_points)は具体的に3文以上で書いてください。

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

# --- API: 宿題生成 (プロンプト大幅強化版) ---
@app.route('/generate_homework', methods=['POST'])
def generate_homework():
    data = request.json
    subject = data.get('subject')
    score = data.get('score')
    improvement = data.get('improvement_points')
    
    prompt = f"""
    あなたはプロの学習教材作成者です。
    以下のテスト結果に基づき、無駄な装飾を省いた実戦的な「復習問題シート」を作成してください。
    名前欄や日付欄などの事務的な項目は一切不要です。

    【データ】
    - 単元: {subject}
    - 前回のスコア: {score}点
    - 重点強化ポイント: {improvement}

    【プリント構成の指示】
    
    1. # 核心ポイントのまとめ
       今回の単元で絶対に外せない公式や考え方を、箇条書きで簡潔にまとめてください。
       生徒が「ここを見れば解ける」という辞書のような内容にします。

    2. # 復習トレーニング（問題のみ）
       - 問1：基礎の再確認（穴埋めや単純な計算・和訳など）、5問程度
       - 問2：類題演習（テストで間違えたパターンに似た問題）、10問程度
       - 問3：応用チャレンジ（少しひねった発展問題）、5問程度
       ※各問題の下には、必ず解答を書き込むための「（解答欄：　　　）」を大きめに設けてください。

    3. # 【別紙】解答と解説
       - 全問の正解を明記してください。
       - なぜその答えになるのか、解き方の手順（ステップ）を論理的に解説してください。
    
    4. 【数式表記ルール】
        1. 数式は必ず LaTeX 形式を使用し、$ $ で囲んで出力してください。
        2. 例: xの2乗は $x^2$、分数は $\\frac{{1}}{{2}}$、ルートは $\\sqrt{{x}}$ と書くこと。
        3. かけ算は $\\times$、わり算は $\div$ を使用してください。

    【出力ルール】
    - Markdown形式で出力すること。
    - 余計な挨拶（「作成しました」等）は不要です。# から始めてください。
    """
    try:
        response = model.generate_content(prompt)
        return jsonify({"status": "success", "homework_content": response.text})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(debug=True)
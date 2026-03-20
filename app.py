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
model1 = genai.GenerativeModel('gemini-2.5-flash-lite-preview-09-2025')
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
        4. 傍線部（下線部）を示す際は、マークダウン（**等）ではなく、必ずHTMLタグの `<u>傍線部</u>` を使用してください。
        5. 出力JSON形式を厳守：
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
        4. 選択式（4択）、空欄補充（穴埋め）、記述式をバランスよく混ぜてください。
        5. **空欄補充（穴埋め）問題を出題する場合は、必ず `reflection_and_validation` 内で「完成した正しい全文」と「抜き出す正解部分」を先に言語化し、その「抜き出す正解部分」をそのままそっくり `(　　)` に単純置換して問題文（question）を生成してください。**
        6. 「一文字のひらがなを入れよ」などの文字数指定や制限は、AI自身が計算を誤る原因となるため、絶対に条件にしないでください。
        
        【数式・表記・改行ルール】
        1. 数式は必ず LaTeX 形式を使用し、$ $ で囲んで出力してください。
           例: $x^2$, $\\frac{{1}}{{2}}$, $\\sqrt{{x}}$, $\\times$, $\\div$
        2. 2乗を ^2 と書くようなプログラミング的表記は禁止です。
        3. 傍線部（下線部）を示す際は、マークダウン（**等）ではなく、必ずHTMLタグの `<u>傍線部</u>` を使用してください。
        4. 問題文の中に選択肢を含める場合や、複数の情報を提示する場合は、適宜 `\n` (改行) を入れて見やすくしてください。
        5. **出力する各問題の作成前に、必ず内部で事実確認、論理破綻、文法ミスの検証を `reflection_and_validation` フィールドで簡潔に（2〜3文で）行ってから作問してください。短時間で生成できるよう冗長な推論は避けてください。**
        
        【出力JSONフォーマット（厳守）】
        {{
          "questions": [
            {{
              "reflection_and_validation": "問題の意図、事実確認、複数解釈が生じないかの簡潔な検証プロセスを記載",
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
        if is_reading_mode:
            response = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(response_mime_type="application/json"), request_options={"timeout": 120})
        else:
            response = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(response_mime_type="application/json"), request_options={"timeout": 120})
        
        # response_mime_typeにより確実にJSONが返ってくるため、直接loadsする
        result = json.loads(response.text)
        result["is_reading_mode"] = is_reading_mode
        result["questions"] = result["questions"][:target_count]
        return jsonify({"status": "success", **result})
    except json.JSONDecodeError as e:
        return jsonify({"status": "error", "message": "JSON形式の抽出に失敗しました: " + str(e)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# --- API: 採点 ---
# app.py の submit_grading 関数を以下に書き換えてください
@app.route('/submit_grading', methods=['POST'])
def submit_grading():
    data = request.json
    # AIへの指示をより厳密にします
    prompt = f"""
    あなたは学習指導報告書を作成するプロの講師です。以下の学習ログに基づき、保護者様へお送りする「指導報告文」を生成してください。
    
    【データ】
    学習内容: {json.dumps(data['questions'], ensure_ascii=False)}
    生徒の解答: {json.dumps(data['answers'], ensure_ascii=False)}
    
    【採点・文言ルール】
    1. is_correctは、解答が正解と一致しているか、記述式なら意味が通じればtrueにしてください。
    2. 解説(explanation)は日本語で簡潔に書いてください。
    3. 良かった点(good_points)と、改善点または今後の展望(improvement_points)は必ず日本語、です・ます調で出力してください。
    4. 良かった点(good_points)は「授業中の理解度や取り組みの姿勢」として4文で書いてください。
    5. **改善点(improvement_points)は3文で書いてください。もし点数が100点（満点）の場合は、改善点ではなく「今後の展望・次週への目標」として書いてください。**
    6. 保護者様は「これが単発のテスト（小テスト）」であることは知りません。「今日の授業中での様子や習得度」として自然に報告してください。
    7. **「高い正答率」「全問正解」「テスト結果」といった試験的な言葉の使用は厳禁です。** 代わりに「内容をスムーズに整理できていました」「着実に身についている様子でした」等の表現を使ってください。
    8. 具体的な問題番号（問1など）や問題文の内容を細かく引用せず、全体を通じた抽象的・総合的な評価を一般論で述べてください。
    9. 主語に「ユーザー」や「あなた」などは使わず、丁寧で客観的な表現にしてください。
    10. **採点の際は、必ず `grading_reasoning` フィールドにて「なぜ正答なのか」「なぜユーザーの解答が◯/×なのか」を1〜2文で自問自答してから `is_correct` を判定してください。**
    
    【出力JSONフォーマット】
    {{
      "score": 合計点数(0-100),
      "good_points": "...",
      "improvement_points": "...",
      "details": [
        {{
          "question": "..",
          "user_answer": "..",
          "correct_answer": "..",
          "grading_reasoning": "採点の根拠や論理的ステップを簡潔に記載",
          "is_correct": true/false,
          "explanation": ".."
        }}
      ]
    }}
    """
    try:
        response = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(response_mime_type="application/json"), request_options={"timeout": 120})
        result = json.loads(response.text)
        return jsonify({"status": "success", "result": result})
    except json.JSONDecodeError as e:
        return jsonify({"status": "error", "message": "JSON形式の解析に失敗しました"})
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
    # --- 追加：モードの取得とモデルの選択 ---
    # フロントエンドの radio ボタンの value ('fast' または 'quality') を受け取る
    mode = data.get('mode', 'quality') 
    
    # model1 は高速な flash-lite、model は標準の flash を使用
    selected_model = model1 if mode == 'fast' else model
    # ------------------------------------------

    subject = data.get('subject', '')
    score = data.get('score', 0)
    improvement = data.get('improvement_points', '')
    details = data.get('details', [])
    
    # ユーザーが間違えた問題などの詳細テキストを作成
    details_text = ""
    for idx, d in enumerate(details):
        is_co = "正解" if d.get('is_correct') else "不正解"
        details_text += f"問{idx+1}: {d.get('question')}\nユーザーの解答: {d.get('user_answer')} (正答: {d.get('correct_answer')}) - {is_co}\n\n"

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
あなたはプロの学習教材作成者です。以下の【テスト結果】と【前回の解答詳細】に基づき、「復習問題シート」のJSONデータを作成してください。
ユーザーが間違えた問題を分析して、基礎が抜けている部分の類題や補強問題を中心に必ず出力してください。

【テスト結果】
- 学年・教科・単元: {subject}
- スコア: {score}点
- 重点強化ポイント: {improvement}

【前回の解答詳細】
{details_text}

【厳守：構成ルール】
1. 以下の問題数を絶対に守り、合計 {total_questions} 問を作成してください。（問1:基礎 {n_basic}問, 問2:標準 {n_normal}問, 問3:発展 {n_advanced}問）
2. 数式は必ず LaTeX 形式を使用し、$ $ で囲んで出力してください。（例: $x^2$, $\\frac{{1}}{{2}}$, $\\sqrt{{x}}$）
3. 傍線部（下線部）を示す際は、マークダウンではなく必ずHTMLタグの `<u>傍線部</u>` を使用してください。
4. **空欄補充（穴埋め）問題を出題する場合は、必ず `drafting_process` 内で「完成した正しい全文」と「抜き出す正解部分」を先に言語化し、その「抜き出す正解部分」をそのままそっくり `(　　)` に単純置換して問題文（question）を生成してください。**
5. 「一文字のひらがなを入れよ」などの文字数指定や制限は、AI自身が計算を誤る原因となるため、絶対に条件にしないでください。
6. 問題文に改行が必要な場合（選択肢を列挙する場合など）は、適宜 `\n` を挿入してください。
5. Markdownの挨拶などは一切含めないでください。
6. **問題を生成する前に、必ず `drafting_process` フィールドにて、「ユーザーの誤答の根本原因にアプローチできているか」「事実誤認、文法ミス、論理破綻がないか」を簡潔に（2〜3文で）検証してください。短時間で生成できるよう冗長な推論は避けてください。**
7. 解説（explanation）を記述してから正答（correct_answer）を記述することで、論理ステップを踏ませてください。
8. 問題文（question）は具体的に記述し、生徒が「何をどう答えればよいか」迷わない明確な指示文を含めてください。

【出力JSONフォーマット】（以下のキーだけで構成すること）
{{
  "homework_title": "あなた専用の復習プリント",
  "questions": [
    {{
      "drafting_process": "この問題を出題する背景と、事実・文法の簡潔な自己検証プロセス",
      "type": "基礎 または 標準 または 発展",
      "question": "問題文をここに詳細に記述",
      "explanation": "解き方の解説をここに記述",
      "correct_answer": "正答をここに記述"
    }}
  ]
}}
"""
    try:
        response = selected_model.generate_content(prompt, generation_config=genai.types.GenerationConfig(response_mime_type="application/json"), request_options={"timeout": 120})
        result = json.loads(response.text)
        return jsonify({"status": "success", "homework_data": result})
    except Exception as e:
        print(f"Homework Generation Error: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/homework')
def homework_route():
    # ここで templates/homework.html を読み込むように指示します
    return render_template('homework.html')

if __name__ == '__main__':
    app.run(debug=True)

       ##- 問1は{c_basic}問、問2は{c_normal}問、問3は{c_advanced}問を出題してください。
       ##- 合計で {int(c_basic) + int(c_normal) + int(c_advanced)} 問の問題を作成してください。
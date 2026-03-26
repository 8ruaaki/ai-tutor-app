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
model1 = genai.GenerativeModel('gemini-2.5-flash')
model = genai.GenerativeModel('gemini-3-flash-preview')
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
    1. is_correctは、解答が正解と一致しているか、または別解になりうる場合にtrueにしてください。
    2. explanationは日本語で詳しく書いてください。is_correctがfalseの場合のみ、なぜ間違っているのかを具体的に指摘してください。
    3. 良かった点(good_points)と、改善点または今後の展望(improvement_points)は必ず日本語、です・ます調で出力してください。
    4. もし点数が100点（満点）の場合は、改善点ではなく「今後の展望・次週への目標」として書いてください。**
    5. 保護者様は「これが単発のテスト（小テスト）」であることは知りません。「今日の授業中での様子や習得度」として自然に報告してください。
    6. **「高い正答率」「全問正解」「テスト結果」といった試験的な言葉の使用は厳禁です。** 代わりに「内容をスムーズに整理できていました」「着実に身についている様子でした」等の表現を使ってください。
    7. 具体的な問題番号（問1など）や問題文の内容を細かく引用せず、全体を通じた抽象的・総合的な評価を一般論で述べてください。
    8. 主語に「ユーザー」や「あなた」などは使わず、丁寧で客観的な表現にしてください。
    9. **採点の際は、必ず `grading_reasoning` フィールドにて「なぜ正答なのか」「なぜユーザーの解答が正解、もしくは不正解なのか」を1〜2文で自問自答してから `is_correct` を判定してください。**
    10. good_pointsとimprovement_pointsは必ず4文で書いてください。

    【good_pointsとimprovement_pointsの構成】
    # good_pointsの構成
      1. 実施したことの詳細: 何を、どの範囲、どれくらい行ったかを具体的に記述。
      2. 実施の意図（なぜそれを実施したのか）: 前回の課題や本日の目標に基づいた指導の狙いを記述。
      3. 習得したスキルの抽象化: 解けた問題そのものだけでなく、そこから得られた「汎用的な能力（考え方・解法）」を抽象化して記述。
      4. 成功要因の分析（なぜ解けたのか）: 本人の姿勢、変化、工夫など、正解に至った理由をプロの視点で分析。
      5. 称賛と応援メッセージ: 具体的な事実に基づいた褒め言葉と、次回の成長を期待するメッセージ。
    
    # improvement_pointsの構成
      1. 改善が必要な領域の特定: どの部分が理解不足か、または誤解しているかを具体的に指摘。
      2. 改善の方向性: どのように考えれば正解に至るのか、具体的な思考プロセスやアプローチを提示。
      3. 練習方法の提案: 次回に向けてどのような練習をすれば良いか、具体的なアクションプランを提案。
      4. 成長への期待: 改善の方向性を示し、前向きな気持ちで次に取り組めるような励ましの言葉。
    
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
9. 語彙整序問題において、使用しない語句を含めることは絶対に避けてください。
10. 出題する問題の形式は様々にしてください。

【難易度の定義】
基礎：公式や用語、原理をそのまま当てはめるだけで解ける問題（英語であれば穴埋め問題）
標準：基礎知識を複数組み合わせたり、少し視点を変えたりして解く問題（英語であれば語彙整序問題や誤文訂正）
発展：未知の状況に対して、どの知識を使うべきか判断し、論理を組み立てて解く問題（英語であれば和訳問題や英作文問題）

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
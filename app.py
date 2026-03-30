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

# RAG用データ取得 (問題集と単語リスト)
def get_rag_data():
    questions_id = os.getenv("QUESTIONS_SHEET_ID")
    vocab_id = os.getenv("VOCAB_SHEET_ID")
    
    if not questions_id or not vocab_id or questions_id == "ここにIDを書く" or vocab_id == "ここにIDを書く":
        return ""
        
    try:
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file('credentials.json', scopes=scopes)
        client = gspread.authorize(creds)
        
        q_sheet = client.open_by_key(questions_id).sheet1
        v_sheet = client.open_by_key(vocab_id).sheet1
        
        # 上限を設けて取得（プロンプト長制限のため）
        q_data = q_sheet.get_all_values()[:50]
        v_data = v_sheet.get_all_values()[:50]
        
        q_str = "\n".join([", ".join(row) for row in q_data])
        v_str = "\n".join([", ".join(row) for row in v_data])
        
        return f"\n【参考データ（問題集）】\n{q_str}\n\n【参考データ（単語リスト）】\n{v_str}\n"
    except Exception as e:
        print("RAG Data Fetch Error:", e)
        return ""

# --- 各ページルーティング ---
@app.route('/')
def index(): return render_template('index.html')

@app.route('/test_page')
def test_page(): return render_template('test.html')

@app.route('/report_page')
def report_page(): return render_template('report.html')

@app.route('/homework_page')
def homework_page(): return render_template('homework.html')

# --- API: テスト生成 (英語文法4択・RAG・再検証) ---
@app.route('/generate_test', methods=['POST'])
def generate_test():
    data = request.json
    subject = data.get('subject', '')
    level = data.get('level', '中級')
    count = int(data.get('count', 5))
    
    rag_context = get_rag_data()

    prompt = f"""
    単元: {subject}
    難易度: {level}
    {rag_context}
    
    あなたは英語のプロの講師です。ユーザーが指定した単元と難易度に基づき、【英語の文法4択問題】を合計 {count} 問作成してください。必要に応じて上記の【参考データ】を活用してください。
    
    【構成ルール】
    1. 全ての問題を必ず「英語の文法4択問題」にしてください。
    2. 1つの設問につき解くべき問題は絶対に1つだけにしてください。
    3. `choices`の配列には必ず4つの選択肢を含めてください。
    4. `correct_answer` には、正解となる選択肢の文字列を完全に一致する形で1つだけ記述してください。
    5. 空欄補充（穴埋め）問題を出題する場合は、正解をそのままそっくり `(　　)` に置換してください。
    
    【出力JSONフォーマット】
    {{
      "questions": [
        {{
          "reflection_and_validation": "問題の意図、事実確認、複数解釈が生じないかの簡潔な検証プロセスを記載",
          "question": "問題文",
          "choices": ["選択肢1", "選択肢2", "選択肢3", "選択肢4"], 
          "correct_answer": "正解の文字列"
        }}
      ]
    }}
    """

    try:
        response = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(response_mime_type="application/json"), request_options={"timeout": 120})
        initial_json = response.text
        
        verify_prompt = f"""
        以下のJSON形式の英語文法問題集を確認し、条件を満たしているか検証・修正して、再度JSON形式で出力してください。API応答の高速化のため、検証結果の理由等は含めず、純粋なJSONデータのみを出力してください。
        
        【検証条件】
        1. 全ての問題が「英語の文法4択問題」であるか。
        2. 全ての問題に置いて `choices` の配列要素が正確に4つであるか。
        3. `correct_answer` が `choices` の中の1つと完全に一致しているか。
        4. 問題として成立しており、複数正解が存在しないか。
        
        【元のデータ】
        {initial_json}
        """
        verify_response = model.generate_content(verify_prompt, generation_config=genai.types.GenerationConfig(response_mime_type="application/json"), request_options={"timeout": 120})
        
        result = json.loads(verify_response.text)
        result["is_reading_mode"] = False
        result["questions"] = result["questions"][:count]
        return jsonify({"status": "success", **result})
    except json.JSONDecodeError as e:
        return jsonify({"status": "error", "message": "JSON形式の抽出に失敗しました: " + str(e)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# --- API: 採点 ---
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

# --- API: 宿題生成 (英語文法4択・RAG・再検証) ---
@app.route('/generate_homework', methods=['POST'])
def generate_homework():
    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "データが空です"})
    
    mode = data.get('mode', 'quality') 
    selected_model = model1 if mode == 'fast' else model

    subject = data.get('subject', '')
    score = data.get('score', 0)
    improvement = data.get('improvement_points', '')
    details = data.get('details', [])
    
    details_text = ""
    for idx, d in enumerate(details):
        is_co = "正解" if d.get('is_correct') else "不正解"
        details_text += f"問{idx+1}: {d.get('question')}\nユーザーの解答: {d.get('user_answer')} (正答: {d.get('correct_answer')}) - {is_co}\n\n"

    try:
        n_basic = int(data.get('count_basic', 0))
        n_normal = int(data.get('count_normal', 0))
        n_advanced = int(data.get('count_advanced', 0))
    except (ValueError, TypeError):
        n_basic = n_normal = n_advanced = 0
        
    total_questions = n_basic + n_normal + n_advanced
    rag_context = get_rag_data()

    prompt = f"""
あなたは英語のプロの学習教材作成者です。以下の【テスト結果】と【前回の解答詳細】に基づき、「英語文法4択問題の復習プリント」のJSONデータを作成してください。
必要に応じて以下の【参考データ】を活用してください。
{rag_context}

【テスト結果】
- 単元: {subject}
- スコア: {score}点
- 重点強化ポイント: {improvement}

【前回の解答詳細】
{details_text}

【厳守：構成ルール】
1. 以下の問題数を絶対に守り、合計 {total_questions} 問を作成してください。
2. 全ての問題を必ず「英語の文法4択問題」にしてください。
3. `correct_answer` には正解を、`choices` には必ず4つの選択肢を含めてください。
4. Markdownの挨拶などは一切含めないでください。
5. 出題する問題の形式（文法事項）には多様性を持たせてください。

【出力JSONフォーマット】（以下のキーだけで構成すること）
{{
  "homework_title": "あなた専用の復習プリント",
  "questions": [
    {{
      "drafting_process": "この問題を出題する背景と、事実・文法の簡潔な自己検証プロセス",
      "type": "基礎 または 標準 または 発展",
      "question": "問題文をここに詳細に記述",
      "choices": ["選択肢1", "選択肢2", "選択肢3", "選択肢4"],
      "explanation": "解き方の解説をここに記述",
      "correct_answer": "正答をここに記述"
    }}
  ]
}}
"""
    try:
        response = selected_model.generate_content(prompt, generation_config=genai.types.GenerationConfig(response_mime_type="application/json"), request_options={"timeout": 120})
        initial_json = response.text
        
        verify_prompt = f"""
        以下のJSON形式の英語文法復習プリントを確認し、条件を満たしているか検証・修正して、再度JSON形式で出力してください。API応答の高速化のため、検証結果の理由等は含めず、純粋なJSONデータのみを出力してください。
        
        【検証条件】
        1. 全ての問題が「英語の文法4択問題」であるか。
        2. 全ての問題に置いて `choices` の配列要素が正確に4つであるか。
        3. `correct_answer` が `choices` の中の1つと完全に一致しているか。
        4. 問題として成立しており、複数正解が存在しないか。
        
        【元のデータ】
        {initial_json}
        """
        verify_response = selected_model.generate_content(verify_prompt, generation_config=genai.types.GenerationConfig(response_mime_type="application/json"), request_options={"timeout": 120})
        
        result = json.loads(verify_response.text)
        return jsonify({"status": "success", "homework_data": result})
    except Exception as e:
        print(f"Homework Generation Error: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/homework')
def homework_route():
    return render_template('homework.html')

if __name__ == '__main__':
    app.run(debug=True)
# AI 学習支援アプリ (AI Tutor)

Gemini APIを活用した、自動問題生成・採点・宿題作成システムです。

## 機能
- **テスト生成**: 単元と難易度に応じた問題をAIが自動作成（数学のLaTeX表記対応）
- **自動採点**: 記述式・選択式を問わずAIがリアルタイムに採点
- **宿題作成**: 苦手なポイントを分析し、パーソナライズされた宿題プリントを生成

## セットアップ
1. このリポジトリをクローン
2. 必要なライブラリのインストール:
   `pip install flask python-dotenv google-generativeai`
3. `.env` ファイルを作成し、APIキーを設定:
   `GEMINI_API_KEY=あなたのAPIキー`
4. アプリの起動:
   `python app.py`
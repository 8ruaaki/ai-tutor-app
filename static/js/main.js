document.addEventListener('DOMContentLoaded', () => {
    if (window.location.pathname.includes('test_page')) {
        initializeTest();
    }
});

/**
 * テスト生成
 */
async function initializeTest() {
    const subject = sessionStorage.getItem('targetSubject');
    const level = sessionStorage.getItem('targetLevel') || '中級';
    const count = sessionStorage.getItem('targetCount') || 5;
    const overlay = document.getElementById('loading-overlay');
    const wrapper = document.getElementById('test-wrapper');

    if (!subject) {
        window.location.href = '/';
        return;
    }

    if (overlay) overlay.style.display = 'flex';

    try {
        const res = await fetch('/generate_test', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ subject, level, count })
        });
        const data = await res.json();

        if (data.status === 'success') {
            window.currentQuestions = data.questions;
            window.isReadingMode = data.is_reading_mode;

            if (window.isReadingMode) {
                wrapper.className = 'reading-mode';
                document.getElementById('passage-container').style.display = 'block';
                document.getElementById('passage-title').innerText = data.passage_title;
                document.getElementById('passage-body').innerText = data.passage_body;
            } else {
                wrapper.className = 'standard-mode';
            }

            const container = document.getElementById('questions-container');
            container.innerHTML = data.questions.map((q, i) => renderQuestionHTML(q, i)).join('');
            
            document.getElementById('submit-btn').style.display = 'block';
            updateProgress();
        }
    } catch (e) {
        console.error("生成エラー:", e);
        alert("問題の生成に失敗しました。トップに戻ります。");
        window.location.href = '/';
    } finally {
        if (overlay) overlay.style.display = 'none';
    }
    if (window.MathJax) {
    MathJax.typesetPromise(); // これが「数式を変換し直して」という命令です
}
}

/**
 * 質問HTML描画
 */
// main.js の中の renderQuestionHTML 関数を差し替え
function renderQuestionHTML(q, i) {
    let inputHTML = '';
    
    // choicesが存在し、かつ配列に中身がある場合
    if (q.choices && Array.isArray(q.choices) && q.choices.length > 0) {
        inputHTML = `<div class="choices-group" style="margin-top: 10px;">
            ${q.choices.map((choice, index) => `
                <label style="display: block; margin-bottom: 8px; padding: 10px; border: 1px solid #ddd; border-radius: 8px; cursor: pointer;">
                    <input type="radio" name="ans-${i}" value="${choice}" onchange="updateProgress()"> 
                    <span style="margin-left: 8px;">${choice}</span>
                </label>
            `).join('')}
        </div>`;
    } else {
        // 記述式の場合
        inputHTML = `<input type="text" id="ans-${i}" class="answer-input" 
                      placeholder="答えを入力してください" 
                      style="width: 100%; padding: 10px; margin-top: 10px;"
                      oninput="updateProgress()" autocomplete="off">`;
    }
    
    return `
        <div class="question-card" style="margin-bottom: 20px; padding: 15px; background: white; border-radius: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);">
            <p><strong>問 ${i + 1}:</strong> ${q.question}</p>
            ${inputHTML}
        </div>`;
}

/**
 * 進捗更新
 */
function updateProgress() {
    let answered = 0;
    const total = window.currentQuestions ? window.currentQuestions.length : 0;
    if (window.currentQuestions) {
        window.currentQuestions.forEach((q, i) => {
            if (q.choices && q.choices.length > 0) {
                if (document.querySelector(`input[name="ans-${i}"]:checked`)) answered++;
            } else {
                const val = document.getElementById(`ans-${i}`);
                if (val && val.value.trim() !== "") answered++;
            }
        });
    }
    const percent = total > 0 ? (answered / total) * 100 : 0;
    const fill = document.getElementById('progress-fill');
    const text = document.getElementById('progress-text');
    if (fill) fill.style.width = percent + "%";
    if (text) text.innerText = `進捗: ${answered} / ${total}`;
}

/**
 * ★ここが重要：採点送信と遷移
 */
// main.js の submitAnswers 関数を以下に書き換えてください
async function submitAnswers() {
    const overlay = document.getElementById('loading-overlay');
    const statusText = document.getElementById('status-text');
    
    const userAnswers = window.currentQuestions.map((q, i) => {
        if (q.choices && q.choices.length > 0) {
            const checked = document.querySelector(`input[name="ans-${i}"]:checked`);
            return checked ? checked.value : "";
        }
        return document.getElementById(`ans-${i}`).value.trim();
    });

    if (overlay) {
        overlay.style.display = 'flex';
        statusText.innerText = "採点中...";
    }

    try {
        const res = await fetch('/submit_grading', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                subject: sessionStorage.getItem('targetSubject'),
                questions: window.currentQuestions,
                answers: userAnswers
            })
        });

        if (!res.ok) throw new Error(`HTTPエラー: ${res.status}`);

        const data = await res.json();
        console.log("採点データ受信:", data); // デバッグ用

        if (data.status === 'success' && data.result) {
            sessionStorage.setItem('lastReport', JSON.stringify(data.result));
            window.location.href = '/report_page';
        } else {
            alert("AIの回答を解析できませんでした。もう一度お試しください。");
        }
    } catch (e) {
        console.error("採点エラーの詳細:", e);
        alert("採点中に通信エラーが発生しました。サーバーの状態を確認してください。");
    } finally {
        if (overlay) overlay.style.display = 'none';
    }
}

function confirmBackHome() {
    if (confirm("テストを中断してトップ画面に戻りますか？（入力した内容は消去されます）")) {
        window.location.href = '/';
    }
}
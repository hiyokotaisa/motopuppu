document.addEventListener('DOMContentLoaded', () => {
    const lapTimeContainer = document.getElementById('lapTimeContainer');
    if (!lapTimeContainer) return;

    const form = lapTimeContainer.closest('form');
    const addLapBtn = document.getElementById('addLapBtn');
    const lapTemplate = document.getElementById('lapTemplate');
    
    // --- ▼▼▼ ここを修正 ▼▼▼ ---
    // 正しいID 'lap_times_json' を指定する
    const hiddenLapInput = document.getElementById('lap_times_json');
    // --- ▲▲▲ 修正ここまで ▲▲▲ ---

    const bestLapDisplay = document.getElementById('bestLap');
    const avgLapDisplay = document.getElementById('avgLap');
    
    // 正規表現: `MM:SS.mmm` または `SS.mmm` 形式にマッチ
    const LAP_TIME_REGEX = /^(?:\d{1,2}:)?\d{1,2}\.\d{1,3}$/;

    // --- ヘルパー関数 ---

    /**
     * "MM:SS.mmm" 形式の文字列を秒単位の数値に変換する
     * @param {string} timeString - 例: "1:58.123" or "58.123"
     * @returns {number|null} - 変換後の秒数、または無効な場合はnull
     */
    function parseTimeToSeconds(timeString) {
        if (!timeString || !LAP_TIME_REGEX.test(timeString.trim())) {
             return null;
        }
        const parts = timeString.split(':');
        let seconds = 0;
        if (parts.length === 2) {
            seconds += parseInt(parts[0], 10) * 60;
            seconds += parseFloat(parts[1]);
        } else {
            seconds += parseFloat(parts[0]);
        }
        return isNaN(seconds) ? null : seconds;
    }

    /**
     * 秒数を "M:SS.fff" 形式の文字列に変換する
     * @param {number} totalSeconds - 秒数
     * @returns {string} - フォーマットされた時間文字列
     */
    function formatSecondsToTime(totalSeconds) {
        if (totalSeconds === null || isNaN(totalSeconds) || totalSeconds === Infinity) return 'N/A';
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = (totalSeconds % 60).toFixed(3).padStart(6, '0'); // SS.fff
        return `${minutes}:${seconds}`;
    }

    // --- メイン処理 ---

    /**
     * 現在入力されている全ラップを収集、計算し、表示を更新する
     */
    function updateCalculationsAndHiddenField() {
        const lapInputs = lapTimeContainer.querySelectorAll('.lap-time-input');
        const validLapTimes = [];
        
        // 各入力欄のバリデーションと値の収集
        lapInputs.forEach(input => {
            const timeValue = input.value.trim();
            if (timeValue === '') {
                input.classList.remove('is-invalid');
            } else if (LAP_TIME_REGEX.test(timeValue)) {
                input.classList.remove('is-invalid');
                validLapTimes.push(timeValue);
            } else {
                input.classList.add('is-invalid');
            }
        });

        // 隠しフィールドを更新
        if (hiddenLapInput) {
            hiddenLapInput.value = JSON.stringify(validLapTimes);
        }

        // ベスト/平均を計算
        const lapSeconds = validLapTimes.map(parseTimeToSeconds).filter(s => s !== null);
        
        if (lapSeconds.length > 0) {
            const best = Math.min(...lapSeconds);
            const sum = lapSeconds.reduce((a, b) => a + b, 0);
            const avg = sum / lapSeconds.length;

            bestLapDisplay.textContent = formatSecondsToTime(best);
            avgLapDisplay.textContent = formatSecondsToTime(avg);
        } else {
            bestLapDisplay.textContent = 'N/A';
            avgLapDisplay.textContent = 'N/A';
        }
    }

    /**
     * 新しいラップ入力欄を追加する
     */
    function addLapRow() {
        const newRow = lapTemplate.content.cloneNode(true);
        const input = newRow.querySelector('.lap-time-input');
        
        // 新しい入力欄にイベントリスナーを追加
        input.addEventListener('input', updateCalculationsAndHiddenField);
        
        lapTimeContainer.appendChild(newRow);
    }
    
    // --- イベントリスナーの設定 ---

    // 「ラップを追加」ボタン
    addLapBtn.addEventListener('click', addLapRow);
    
    // 削除ボタン（イベントデリゲーション）
    lapTimeContainer.addEventListener('click', (event) => {
        const button = event.target.closest('.remove-lap-btn');
        if (button) {
            button.closest('.input-group').remove();
            updateCalculationsAndHiddenField(); // 削除後も再計算
        }
    });
    
    // 入力イベント（イベントデリゲーション）
    lapTimeContainer.addEventListener('input', (event) => {
        if (event.target.classList.contains('lap-time-input')) {
            updateCalculationsAndHiddenField();
        }
    });

    // フォーム送信前に最終更新
    if (form) {
        form.addEventListener('submit', updateCalculationsAndHiddenField);
    }
});
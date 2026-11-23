// 通常UI・Beta UI共通のCSVインポート進捗・エラー処理。
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.import-form').forEach(form => {
        const fieldsContainer = form.querySelector('.import-form-fields');
        const progressContainer = form.querySelector('.import-progress-display');
        const errorContainer = form.querySelector('.import-error-display');
        const errorTextEl = form.querySelector('.import-error-text');
        const stageTextEl = form.querySelector('.import-progress-stage-text');
        const detailTextEl = form.querySelector('.import-progress-detail');
        const progressBar = form.querySelector('.progress-bar');
        const submitBtn = form.querySelector('input[type="submit"], button[type="submit"]');
        let inProgress = false;
        let completed = false;
        const cancelBtn = form.querySelector('.import-cancel-btn');
        const closeBtn = form.querySelector('.import-close-btn');
        const modal = form.closest('.modal');
        modal?.addEventListener('hide.bs.modal', event => {
            if (inProgress && !completed) event.preventDefault();
        });

        const STAGE_LABELS = {
            uploading: 'ファイルをアップロード中',
            parsing: 'CSVを解析中',
            validating: 'ラップタイムを検証中',
            filtering: '外れ値を除外中',
            optimizing: 'GPS軌跡を最適化中',
            saving: 'データベースに保存中',
            done: '完了',
            error: 'エラー',
        };

        const setProgress = (pct, striped, animated) => {
            const determinate = pct !== null;
            const v = determinate ? Math.max(0, Math.min(100, Math.round(pct))) : 100;
            progressBar.style.width = v + '%';
            if (determinate) progressBar.setAttribute('aria-valuenow', v);
            else progressBar.removeAttribute('aria-valuenow');
            progressBar.textContent = determinate ? v + '%' : '';
            progressBar.classList.toggle('progress-bar-striped', !!striped);
            progressBar.classList.toggle('progress-bar-animated', !!animated);
        };

        const showProgress = () => {
            inProgress = true;
            progressBar.classList.remove('bg-success');
            errorContainer.classList.add('d-none');
            fieldsContainer.classList.add('d-none');
            progressContainer.classList.remove('d-none');
            if (submitBtn) submitBtn.disabled = true;
            if (cancelBtn) cancelBtn.disabled = true;
            if (closeBtn) closeBtn.disabled = true;
        };

        const resetForm = () => {
            inProgress = false;
            fieldsContainer.classList.remove('d-none');
            progressContainer.classList.add('d-none');
            if (submitBtn) submitBtn.disabled = false;
            if (cancelBtn) cancelBtn.disabled = false;
            if (closeBtn) closeBtn.disabled = false;
            setProgress(0, true, true);
        };

        const showError = (message) => {
            resetForm();
            errorContainer.classList.remove('d-none');
            errorTextEl.textContent = message || 'エラーが発生しました。';
        };

        const handleEvent = (evt) => {
            const stage = evt.stage;
            const label = STAGE_LABELS[stage] || stage;

            if (stage === 'error') {
                showError(evt.message);
                return;
            }
            if (stage === 'done') {
                stageTextEl.textContent = '完了';
                detailTextEl.textContent = evt.message || '';
                setProgress(100, false, false);
                progressBar.classList.add('bg-success');
                const result = form.querySelector('.import-success-display');
                if (result) {
                    completed = true;
                    progressContainer.classList.add('d-none');
                    result.classList.remove('d-none');
                    const summary = evt.summary || {};
                    for (const [selector, value] of [
                        ['[data-import-laps]', summary.imported_laps],
                        ['[data-import-removed]', summary.removed_laps],
                        ['[data-import-gps]', summary.gps_laps],
                        ['[data-import-best]', summary.best_lap],
                    ]) {
                        const element = result.querySelector(selector);
                        if (element) element.textContent = value ?? '—';
                    }
                    const detailLink = result.querySelector('[data-import-detail-link]');
                    if (detailLink) detailLink.href = evt.redirect_url || window.location.href;
                    const gpsLink = result.querySelector('[data-import-gps-link]');
                    if (gpsLink) {
                        gpsLink.hidden = !evt.gps_url;
                        if (evt.gps_url) gpsLink.href = evt.gps_url;
                    }
                    if (closeBtn) closeBtn.disabled = false;
                    if (cancelBtn) { cancelBtn.disabled = false; cancelBtn.textContent = '閉じて反映'; }
                    if (submitBtn) submitBtn.hidden = true;
                    modal?.addEventListener('hidden.bs.modal', () => {
                        window.location.href = evt.redirect_url || window.location.href;
                    }, {once: true});
                    return;
                }
                setTimeout(() => {
                    if (evt.redirect_url) {
                        window.location.href = evt.redirect_url;
                    } else {
                        window.location.reload();
                    }
                }, 700);
                return;
            }
            stageTextEl.textContent = label + '...';
            if (stage === 'optimizing' && evt.lap && evt.total_laps) {
                detailTextEl.textContent = `ラップ ${evt.lap} / ${evt.total_laps}`;
                const pct = (evt.lap / evt.total_laps) * 100;
                setProgress(pct, false, true);
            } else {
                detailTextEl.textContent = evt.message || '';
                // 確定的な進捗が無いステージは不確定スピナー風
                setProgress(null, true, true);
            }
        };

        form.addEventListener('submit', function(event) {
            event.preventDefault();
            if (inProgress) return;

            const appendMode = this.querySelector('input[name="append_mode"]:checked');
            const isAppend = Boolean(appendMode && appendMode.value !== 'false');

            let message = '既存のラップタイムは上書きされます。よろしいですか？';
            if (isAppend) {
                message = '既存の記録の後ろに追記します。よろしいですか？\n(この操作は取り消せません)';
            }
            if (this.querySelector('[name="target_session"]')?.value === 'new') {
                message = 'CSVから新しいセッションを作成します。よろしいですか？';
            }
            if (!confirm(message)) return;

            showProgress();
            stageTextEl.textContent = 'アップロード中...';
            detailTextEl.textContent = '0%';
            setProgress(0, false, false);

            const xhr = new XMLHttpRequest();
            xhr.open('POST', form.action, true);
            xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
            xhr.setRequestHeader('Accept', 'application/x-ndjson');

            xhr.upload.onprogress = (e) => {
                if (e.lengthComputable) {
                    const pct = (e.loaded / e.total) * 100;
                    setProgress(pct, false, false);
                    detailTextEl.textContent = Math.round(pct) + '%';
                }
            };
            xhr.upload.onload = () => {
                // アップロード完了 → サーバー処理待ち
                stageTextEl.textContent = 'サーバー処理中...';
                detailTextEl.textContent = '';
                setProgress(null, true, true);
            };

            let buffer = '';
            let lastIndex = 0;
            let terminal = false;
            const receiveEvent = (line) => {
                if (!line.trim() || terminal) return;
                let evt;
                try { evt = JSON.parse(line); } catch (_) { return; }
                if (!evt || typeof evt !== 'object') return;
                if (!Object.prototype.hasOwnProperty.call(STAGE_LABELS, evt.stage)) return;
                if (evt.stage === 'done' || evt.stage === 'error') terminal = true;
                handleEvent(evt);
            };
            const consume = (final = false) => {
                // HTMLエラーをNDJSONとして消費せず、onloadでHTTP状態を判定する。
                if (xhr.status < 200 || xhr.status >= 300) return;
                buffer += xhr.responseText.substring(lastIndex);
                lastIndex = xhr.responseText.length;
                let nl;
                while ((nl = buffer.indexOf('\n')) >= 0) {
                    const line = buffer.substring(0, nl);
                    buffer = buffer.substring(nl + 1);
                    receiveEvent(line);
                }
                if (final && buffer.trim()) {
                    receiveEvent(buffer);
                    buffer = '';
                }
            };
            const fail = (message) => {
                if (terminal) return;
                terminal = true;
                showError(message);
            };
            xhr.onprogress = () => consume();
            xhr.onreadystatechange = () => {
                if (xhr.readyState >= 3) consume();
            };
            xhr.onerror = () => fail('通信エラーが発生しました。記録を確認してから再試行してください。');
            xhr.onabort = () => fail('通信が中断されました。記録を確認してから再試行してください。');
            xhr.ontimeout = () => fail('通信がタイムアウトしました。記録を確認してから再試行してください。');
            xhr.onload = () => {
                consume(true);
                if (terminal) return;
                if (xhr.status < 200 || xhr.status >= 300) {
                    let errorMessage;
                    try { errorMessage = JSON.parse(xhr.responseText).message; } catch (_) { /* HTMLや空の応答 */ }
                    const fallback = xhr.status === 413
                        ? 'アップロードできるサイズの上限を超えました。ファイルサイズを確認してください。(HTTP 413)'
                        : `サーバーエラー (HTTP ${xhr.status})`;
                    fail(errorMessage || fallback);
                } else {
                    fail('処理の完了を確認できませんでした。記録を確認してから再試行してください。');
                }
            };
            xhr.send(new FormData(form));
        });
    });

});

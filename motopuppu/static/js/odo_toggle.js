// motopuppu/static/js/odo_toggle.js

document.addEventListener('DOMContentLoaded', function() {
    const toggleSwitch = document.getElementById('odoDisplayToggle');
    const toggleLabel = document.getElementById('odoDisplayToggleLabel');
    const distanceHeader = document.getElementById('distance_header');
    const distanceValueCells = document.querySelectorAll('.distance-value-cell');

    const ODO_READING_TEXT = 'ODO (km)';
    const ACTUAL_DISTANCE_TEXT = '実走行距離 (km)';
    const ODO_SORT_KEY = 'odo_reading';
    const ACTUAL_SORT_KEY = 'actual_distance';
    const FIXED_TOGGLE_LABEL_TEXT = '実走行距離を表示'; // 固定ラベルテキスト

    let showActualDistance = localStorage.getItem('showActualDistance') === 'true';

    if (toggleLabel) {
        toggleLabel.textContent = FIXED_TOGGLE_LABEL_TEXT;
    }

    function updateDisplay(isActual) {
        if (distanceHeader) {
            const headerLink = distanceHeader.querySelector('a');
            const headerTextSpan = distanceHeader.querySelector('a .header-text');
            const sortIconSpan = distanceHeader.querySelector('a .sort-icon');

            if (headerLink && headerTextSpan && sortIconSpan) {
                const targetSortKey = isActual ? ACTUAL_SORT_KEY : ODO_SORT_KEY;
                const targetHeaderText = isActual ? ACTUAL_DISTANCE_TEXT : ODO_READING_TEXT;

                // ▼▼▼ ここを修正 ▼▼▼
                // textContent でテキストのみを上書きするのではなく、innerHTML を使ってアイコンごと書き換える
                headerTextSpan.innerHTML = `<i class="bi bi-speedometer2 me-2"></i>${targetHeaderText}`;
                // ▲▲▲ ここまで修正 ▲▲▲

                const currentUrlParams = new URLSearchParams(window.location.search);
                const pageSortBy = currentUrlParams.get('sort_by');
                const pageOrder = currentUrlParams.get('order');

                let nextOrder = 'asc'; // デフォルトの次のオーダー

                if (pageSortBy === targetSortKey) { // 現在ソート中のキーが、このヘッダーの担当キーと同じなら
                    if (pageOrder === 'asc') {
                        nextOrder = 'desc'; // 現在昇順なら次は降順
                    } else {
                        nextOrder = 'asc'; // 現在降順(または指定なしで実質降順の場合も含む)なら次は昇順
                    }
                }
                // もし pageSortBy が targetSortKey と異なる場合は、初回クリックとみなし nextOrder は 'asc' のまま

                // ベースURL（パス部分）を取得
                const baseUrl = window.location.origin + window.location.pathname;

                // 新しいクエリパラメータを構築 (既存のフィルター条件は維持)
                const newParams = new URLSearchParams();
                currentUrlParams.forEach((value, key) => {
                    if (key !== 'sort_by' && key !== 'order' && key !== 'page') {
                        newParams.append(key, value);
                    }
                });
                newParams.append('sort_by', targetSortKey);
                newParams.append('order', nextOrder);
                newParams.append('page', '1'); // ソート条件変更時は1ページ目に戻す

                headerLink.href = `${baseUrl}?${newParams.toString()}`;

                // アイコン更新
                if (pageSortBy === targetSortKey) {
                    sortIconSpan.innerHTML = (pageOrder === 'asc') ?
                        '<i class="fas fa-sort-up fa-fw ms-1"></i>' :
                        '<i class="fas fa-sort-down fa-fw ms-1"></i>';
                } else {
                    sortIconSpan.innerHTML = '<i class="fas fa-sort fa-fw text-muted ms-1"></i>';
                }
            }
        }

        distanceValueCells.forEach(cell => {
            const odoValue = cell.dataset.odoValue;
            const actualValue = cell.dataset.actualValue;
            const valueToShow = isActual ? actualValue : odoValue;
            
            let formattedValue = '-';
            if (valueToShow !== undefined && valueToShow !== null && valueToShow !== '') {
                const numValue = parseInt(valueToShow, 10);
                if (!isNaN(numValue)) {
                    formattedValue = numValue.toLocaleString();
                }
            }
            cell.textContent = formattedValue;
        });
    }

    if (toggleSwitch) {
        toggleSwitch.checked = showActualDistance;
        updateDisplay(showActualDistance); // 初期表示を更新

        toggleSwitch.addEventListener('change', function() {
            showActualDistance = this.checked;
            localStorage.setItem('showActualDistance', showActualDistance);
            updateDisplay(showActualDistance); // トグル変更時も表示を更新
        });
    } else {
        // スイッチがないページ（または要素が見つからない場合）のフォールバック
        updateDisplay(false); // デフォルトはODOメーター値を表示
    }
});
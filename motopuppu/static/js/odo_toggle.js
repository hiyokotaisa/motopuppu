// motopuppu/static/js/odo_toggle.js
document.addEventListener('DOMContentLoaded', function() {
    const toggleSwitch = document.getElementById('odoDisplayToggle');
    const toggleLabel = document.getElementById('odoDisplayToggleLabel'); // ラベル要素は取得しますが、テキストは固定
    const distanceHeader = document.getElementById('distance_header');
    const distanceValueCells = document.querySelectorAll('.distance-value-cell');

    const ODO_READING_TEXT = 'ODO (km)';
    const ACTUAL_DISTANCE_TEXT = '実走行距離 (km)';
    const ODO_SORT_KEY = 'odo_reading';
    const ACTUAL_SORT_KEY = 'actual_distance';
    const FIXED_TOGGLE_LABEL_TEXT = '実走行距離を表示'; // 固定ラベルテキスト

    // LocalStorageから設定を読み込む (キー名は 'showActualDistance' のまま)
    let showActualDistance = localStorage.getItem('showActualDistance') === 'true';

    // ラベルテキストを固定で設定
    if (toggleLabel) {
        toggleLabel.textContent = FIXED_TOGGLE_LABEL_TEXT;
    }

    function updateDisplay(isActual) {
        // トグルスイッチ自体の状態は更新するが、ラベルテキストは変更しない

        if (distanceHeader) {
            const headerLink = distanceHeader.querySelector('a');
            const headerTextSpan = distanceHeader.querySelector('a .header-text');
            if (headerLink && headerTextSpan) {
                const currentSortKey = isActual ? ACTUAL_SORT_KEY : ODO_SORT_KEY;
                const currentHeaderText = isActual ? ACTUAL_DISTANCE_TEXT : ODO_READING_TEXT;

                headerTextSpan.textContent = currentHeaderText;

                const url = new URL(headerLink.href);
                url.searchParams.set('sort_by', currentSortKey);
                const currentOrder = url.searchParams.get('order') || 'desc';
                url.searchParams.set('order', currentOrder);
                headerLink.href = url.toString();

                const sortIconSpan = distanceHeader.querySelector('a .sort-icon');
                 if (sortIconSpan) {
                    const params = new URLSearchParams(window.location.search);
                    const pageSortBy = params.get('sort_by');
                    const pageOrder = params.get('order') || 'desc';

                    if (pageSortBy === currentSortKey) {
                        sortIconSpan.innerHTML = pageOrder === 'asc' ?
                            '<i class="fas fa-sort-up fa-fw ms-1"></i>' :
                            '<i class="fas fa-sort-down fa-fw ms-1"></i>';
                    } else {
                        sortIconSpan.innerHTML = '<i class="fas fa-sort fa-fw text-muted ms-1"></i>';
                    }
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
        toggleSwitch.checked = showActualDistance; // スイッチの状態はlocalStorageに基づいて設定
        updateDisplay(showActualDistance); // 表示を更新

        toggleSwitch.addEventListener('change', function() {
            showActualDistance = this.checked;
            localStorage.setItem('showActualDistance', showActualDistance);
            updateDisplay(showActualDistance);
        });
    } else {
        // スイッチがないページ（または要素が見つからない場合）のフォールバック
        // デフォルトではODOメーター値を表示する (isActual = false)
        updateDisplay(false); 
    }
});
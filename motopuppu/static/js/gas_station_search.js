// motopuppu/static/js/gas_station_search.js
document.addEventListener('DOMContentLoaded', function() {
    const searchButton = document.getElementById('search-gas-station-btn');
    const stationNameInput = document.getElementById('station_name');
    const resultsContainer = document.getElementById('gas-station-results');

    if (!searchButton || !stationNameInput || !resultsContainer) {
        console.warn('Gas station search elements not found.');
        return;
    }

    const searchGasStations = async () => {
        const query = stationNameInput.value.trim();
        if (query.length < 2) {
            // 2文字未満の場合は検索しない
            resultsContainer.innerHTML = '';
            return;
        }

        // ローディングスピナーを表示
        resultsContainer.innerHTML = `
            <div class="d-flex justify-content-center align-items-center p-3">
                <div class="spinner-border spinner-border-sm" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
                <span class="ms-2">検索中...</span>
            </div>`;

        try {
            const response = await fetch(`/fuel/search_gas_station?q=${encodeURIComponent(query)}`);
            
            // 結果コンテナをクリア
            resultsContainer.innerHTML = '';

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || '検索に失敗しました。');
            }

            const data = await response.json();

            if (data.results && data.results.length > 0) {
                data.results.forEach(place => {
                    const item = document.createElement('button');
                    item.type = 'button';
                    item.className = 'list-group-item list-group-item-action';
                    item.dataset.stationName = place.name; // 店名データを保持

                    // 店名と住所を表示
                    const nameElement = document.createElement('div');
                    nameElement.className = 'fw-bold';
                    nameElement.textContent = place.name;
                    
                    const addressElement = document.createElement('small');
                    addressElement.className = 'd-block text-muted';
                    addressElement.textContent = place.address;

                    item.appendChild(nameElement);
                    item.appendChild(addressElement);

                    // 候補をクリックした時の処理
                    item.addEventListener('click', () => {
                        stationNameInput.value = item.dataset.stationName; // 入力欄に店名を設定
                        resultsContainer.innerHTML = ''; // 候補リストをクリア
                    });

                    resultsContainer.appendChild(item);
                });
            } else {
                resultsContainer.innerHTML = '<div class="list-group-item text-muted">候補が見つかりませんでした。</div>';
            }
        } catch (error) {
            console.error('Gas station search error:', error);
            resultsContainer.innerHTML = `<div class="list-group-item text-danger">エラー: ${error.message}</div>`;
        }
    };

    // 検索ボタンクリックで検索実行
    searchButton.addEventListener('click', searchGasStations);

    // Enterキーでも検索できるように
    stationNameInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
            event.preventDefault(); // フォームの送信を防ぐ
            searchGasStations();
        }
    });

    // 入力欄の外側をクリックしたら結果を閉じる
    document.addEventListener('click', (event) => {
        if (!stationNameInput.contains(event.target) && !resultsContainer.contains(event.target)) {
            resultsContainer.innerHTML = '';
        }
    });
});
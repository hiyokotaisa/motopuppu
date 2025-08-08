// motopuppu/static/js/global_search.js

document.addEventListener('DOMContentLoaded', () => {
    const searchForm = document.getElementById('global-search-form');
    const searchInput = document.getElementById('global-search-input');
    const searchResultsContainer = document.getElementById('global-search-results');
    
    if (!searchInput || !searchResultsContainer || !searchForm) {
        console.warn('Global search elements not found.');
        return;
    }

    let debounceTimer;
    let currentRequestController = null;

    // --- メインの検索処理 ---
    const handleSearch = () => {
        const query = searchInput.value.trim();

        if (query.length < 1) {
            hideResults();
            return;
        }

        // 既存のリクエストがあればキャンセル
        if (currentRequestController) {
            currentRequestController.abort();
        }
        currentRequestController = new AbortController();
        const signal = currentRequestController.signal;

        fetch(`${window.location.origin}/search/?q=${encodeURIComponent(query)}`, { signal })
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(data => {
                renderResults(data.results);
            })
            .catch(error => {
                if (error.name !== 'AbortError') {
                    console.error('Search fetch error:', error);
                    renderError('検索中にエラーが発生しました。');
                }
            });
    };

    // --- 結果の描画 ---
    const renderResults = (results) => {
        searchResultsContainer.innerHTML = '';

        if (results.length === 0) {
            const noResultItem = document.createElement('div');
            noResultItem.className = 'dropdown-item disabled';
            noResultItem.textContent = '一致する結果が見つかりませんでした。';
            searchResultsContainer.appendChild(noResultItem);
            showResults();
            return;
        }

        const groupedResults = results.reduce((acc, result) => {
            (acc[result.category] = acc[result.category] || []).push(result);
            return acc;
        }, {});

        for (const category in groupedResults) {
            const header = document.createElement('h6');
            header.className = 'dropdown-header';
            header.textContent = category;
            searchResultsContainer.appendChild(header);

            groupedResults[category].forEach(item => {
                const link = document.createElement('a');
                link.href = item.url;
                link.className = 'dropdown-item search-result-item';
                
                const titleEl = document.createElement('div');
                titleEl.className = 'result-title';
                titleEl.textContent = item.title;
                
                const textEl = document.createElement('small');
                textEl.className = 'result-text';
                textEl.textContent = item.text;

                link.appendChild(titleEl);
                link.appendChild(textEl);
                searchResultsContainer.appendChild(link);
            });
        }
        showResults();
    };

    const renderError = (message) => {
        searchResultsContainer.innerHTML = '';
        const errorItem = document.createElement('div');
        errorItem.className = 'dropdown-item disabled text-danger';
        errorItem.textContent = message;
        searchResultsContainer.appendChild(errorItem);
        showResults();
    };


    // --- UI制御ヘルパー ---
    const showResults = () => searchResultsContainer.classList.add('show');
    const hideResults = () => searchResultsContainer.classList.remove('show');
    
    // --- イベントリスナー ---
    searchInput.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(handleSearch, 300); // 300msのデバウンス
    });

    searchInput.addEventListener('focus', handleSearch);
    
    // フォーム送信（Enterキー）で最初の検索結果に飛ぶ
    searchForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const firstResult = searchResultsContainer.querySelector('a.dropdown-item');
        if (firstResult) {
            window.location.href = firstResult.href;
        }
    });

    // 外側をクリックしたら結果を閉じる
    document.addEventListener('click', (e) => {
        if (!searchForm.contains(e.target)) {
            hideResults();
        }
    });
    
    // Escキーで結果を閉じる
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            hideResults();
        }
    });

    // Ctrl+K または / で検索ボックスにフォーカス
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey && e.key === 'k') || (e.key === '/' && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA')) {
            e.preventDefault();
            searchInput.focus();
            searchInput.select();
        }
    });
});
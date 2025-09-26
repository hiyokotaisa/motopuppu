// motopuppu/static/js/tutorial.js

/**
 * チュートリアル完了ステータスをサーバーに送信する
 * @param {string} csrfToken - CSRFトークン
 * @param {string} tutorialKey - 完了したチュートリアルのキー (例: 'initial_setup')
 */
function markTutorialAsComplete(csrfToken, tutorialKey) {
    fetch('/api/tutorial/complete', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ key: tutorialKey }) // 完了したキーを送信
    }).then(response => {
        if (!response.ok) {
            console.error(`Failed to mark tutorial '${tutorialKey}' as complete.`);
        }
    }).catch(error => {
        console.error('Error communicating with server:', error);
    });
}

/**
 * 新規ユーザー向けの初回チュートリアル（車両登録への誘導）を開始する
 * @param {string} csrfToken - CSRFトークン
 */
function startInitialSetupTutorial(csrfToken) {
    const intro = introJs();

    intro.setOptions({
        steps: [{
            title: '🏍️ もとぷっぷーへようこそ！',
            intro: 'これからあなたのバイクライフの記録をサポートします。<br><br>まずは、あなたの愛車を登録することから始めましょう！'
        }, {
            element: document.querySelector('#tutorial-start-add-vehicle'),
            title: '最初のステップ',
            intro: 'ここからあなたの最初のバイクを登録します。クリックして次に進みましょう。'
        }],
        nextLabel: '次へ →',
        prevLabel: '← 前へ',
        doneLabel: 'OK',
        skipLabel: 'スキップ',
        showProgress: true,
        exitOnOverlayClick: false,
    });

    intro.onexit(function() {
        markTutorialAsComplete(csrfToken, 'initial_setup');
    });

    intro.onbeforechange(function(targetElement) {
        if (this._currentStep === 1) {
            intro.exit(); 
            targetElement.click();
        }
    });

    intro.start();
}


/**
 * 車両登録ページのチュートリアルを開始する
 * @param {string} csrfToken - CSRFトークン
 */
function startVehicleFormTutorial(csrfToken) {
    const intro = introJs();

    intro.setOptions({
        steps: [
            {
                title: '車両情報の入力',
                intro: 'あなたの愛車を登録しましょう！<br><strong>「車両名」</strong>だけが必須項目です。他の項目は後からでも編集できます。'
            },
            {
                element: document.querySelector('#tutorial-vehicle-name'),
                title: '車両名 (必須)',
                intro: 'あなたのバイクの管理しやすい名前や型式などを入力してください。<br>例: CBR250RR, 通勤用カブ'
            },
            {
                element: document.querySelector('#is_racer_checkbox'),
                title: '重要な選択',
                intro: 'このバイクは公道走行しますか？<br><strong>レーサー車両</strong>に設定すると、走行距離(km)ではなく<strong>総稼働時間(h)</strong>で管理します。<br><strong class="text-danger">この設定は登録後に変更できません。</strong>',
                position: 'right'
            },
            {
                element: document.querySelector('#tutorial-initial-odometer'),
                title: '現在の走行距離',
                intro: 'もし現在のメーターの走行距離が分かれば入力してください。これが今後の燃費や整備記録の基準点になります。'
            },
            {
                element: document.querySelector('#tutorial-drivetrain-data'),
                title: '駆動系データ (任意)',
                intro: 'ここは、走行ログ機能の<strong>ギアレシオチャート</strong>で使用する専門的な情報を入力する項目です。<br><br>初めて使う場合や情報が不明な場合は、<strong>すべて空欄のままで問題ありません。</strong>'
            },
            {
                element: document.querySelector('#tutorial-vehicle-submit'),
                title: '登録の完了',
                intro: '入力が終わったら、このボタンで登録します。これで車両登録は完了です！',
                position: 'top'
            }
        ],
        nextLabel: '次へ →',
        prevLabel: '← 前へ',
        doneLabel: 'わかった！',
        skipLabel: 'スキップ',
        showProgress: true,
        exitOnOverlayClick: false,
    });

    intro.onexit(function() {
        markTutorialAsComplete(csrfToken, 'vehicle_form');
    });

    intro.start();
}


/**
 * ダッシュボード全体のツアーを開始する
 * @param {string} csrfToken - CSRFトークン
 */
function startDashboardTour(csrfToken) {
    const intro = introJs();

    intro.setOptions({
        steps: [
            {
                title: '🎉 車両登録が完了しました！',
                intro: `
                    <p>これであなたのガレージに最初の1台が追加されました。</p>
                    <p>もとぷっぷーには、バイクライフを記録するための様々な機能があります。さっそく使ってみましょう！</p>
                    <hr>
                    <div style="max-height: 200px; overflow-y: auto; text-align: left; padding-right: 15px;">
                        <ul class="list-unstyled small">
                            <li><strong><i class="fas fa-gas-pump fa-fw me-2"></i>給油記録:</strong> 燃費を自動で計算・グラフ化します。</li>
                            <li class="mt-2"><strong><i class="fas fa-tools fa-fw me-2"></i>整備記録:</strong> いつどんなメンテナンスをしたか記録できます。</li>
                            <li class="mt-2"><strong><i class="fas fa-sticky-note fa-fw me-2"></i>ノート:</strong> ツーリングの計画やカスタムメモなど、自由に記録できます。</li>
                            <li class="mt-2"><strong><i class="fas fa-flag-checkered fa-fw me-2"></i>走行ログ:</strong> サーキット走行のセッティングやタイムを記録・比較できます。</li>
                            <li class="mt-2"><strong><i class="fas fa-map-signs fa-fw me-2"></i>ツーリングログ:</strong> 旅の思い出を写真やメモと共に記録します。</li>
                            <li class="mt-2"><strong><i class="fas fa-id-card fa-fw me-2"></i>ガレージカード:</strong> あなたの愛車をカード形式で公開できます。</li>
                             <li class="mt-2"><strong><i class="fas fa-motorcycle fa-fw me-2"></i>車両管理:</strong> 登録した車両情報の編集や、リマインダー設定ができます。</li>
                        </ul>
                    </div>
                `
            },
            {
                element: document.querySelector('[data-widget-name="reminders"]'),
                title: 'メンテナンスリマインダー',
                intro: '交換時期が近づいている消耗品や、定期メンテナンスの予定がここに表示されます。'
            },
            {
                element: document.querySelector('[data-widget-name="stats"]'),
                title: '統計情報',
                intro: '期間内の総走行距離や消費した燃料、かかった費用などのサマリーを確認できます。'
            },
            {
                element: document.querySelector('[data-widget-name="vehicles"]'),
                title: '車両一覧',
                intro: 'あなたが登録した車両の一覧です。ここから各車両の詳細な記録ページへ移動できます。'
            },
            // ▼▼▼【ここから修正】タイムラインとカレンダーのステップを追加 ▼▼▼
            {
                element: document.querySelector('[data-widget-name="timeline"]'),
                title: '給油・整備タイムライン',
                intro: '給油や整備の記録が時系列で表示されます。最近の活動を振り返るのに便利です。'
            },
            {
                element: document.querySelector('[data-widget-name="calendar"]'),
                title: '記録カレンダー',
                intro: 'すべての記録がカレンダー形式で表示されます。いつ何をしたか一目でわかります。'
            },
            // ▲▲▲【修正はここまで】▲▲▲
            {
                element: document.querySelector('#main-navbar'),
                title: 'ナビゲーションバー',
                intro: '主な機能へは、画面上部のこのバーからいつでもアクセスできます。「マイガレージ」からは車両ごとの記録ページへ、「コミュニティ」からはチームやリーダーボードなどの機能へ移動できます。',
                position: 'bottom'
            },
            {
                title: 'チュートリアル完了！',
                intro: 'これで基本的な説明は終わりです。さっそく、あなたのバイクライフを記録してみましょう！'
            }
        ],
        nextLabel: '次へ →',
        prevLabel: '← 前へ',
        doneLabel: 'ツアーを終了',
        skipLabel: 'スキップ',
        showProgress: true
    });

    intro.onexit(function() {
        markTutorialAsComplete(csrfToken, 'dashboard_tour');
    });

    intro.start();
}
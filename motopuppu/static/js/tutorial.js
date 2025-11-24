// motopuppu/static/js/tutorial.js

/**
 * motopuppu/static/js/tutorial.js
 * にゃんぷっぷーによる対話型チュートリアル (V3: シンプルカード版 - 指定画像Ver)
 */

// キャラクター画像の定義（指定された安心・安全な画像のみ使用）
const NYAN_IMAGES = {
    // 基本: 真顔でじっと見つめる（説明用）
    'normal': '/static/images/nyanpuppu/blobcat.png',
    
    // 挨拶/可愛い: UwU顔（ウェルカム、完了時など）
    'cute': '/static/images/nyanpuppu/blobcat_uwu.png',
    
    // 応援/喜び: ペンライトを振る（開始、成功、ポジティブな機能紹介）
    'cheer': '/static/images/nyanpuppu/ablobcat_cheer.gif',
    
    // 快適/安心: 布団に入っている（リマインダー、補足説明など）
    'comfy': '/static/images/nyanpuppu/blobcatcomfy.png',
    
    // タコ/入力: タコblobcat（入力フォーム、作業中、アクセント）
    'taco': '/static/images/nyanpuppu/blobcataco.png'
};

/**
 * 感情キーと画像の内部マッピング
 * ロジック側で使いやすいキー(emotion)を、実際の画像キーに振り分けます
 */
function getBlobcatImage(emotion) {
    switch (emotion) {
        case 'wave':    // 手を振る -> UwUで可愛く
        case 'sad':     // 悲しい -> UwUでしんみりと
            return NYAN_IMAGES['cute'];
            
        case 'happy':   // 喜び -> 応援
        case 'excited': // 興奮 -> 応援
        case 'drive':   // 運転 -> 応援（動きがあるため）
            return NYAN_IMAGES['cheer'];
            
        case 'write':   // 書く -> タコ（作業感）
            return NYAN_IMAGES['taco'];
            
        case 'relax':   // リラックス -> 布団
            return NYAN_IMAGES['comfy'];
            
        case 'shock':   // 警告 -> 真顔（真剣さを出すためあえてnormal）
        case 'serious': // 真剣 -> 真顔
        case 'explain': // 説明 -> 真顔
        case 'normal':  // 通常 -> 真顔
        default:
            return NYAN_IMAGES['normal'];
    }
}

/**
 * チュートリアル用のHTMLコンテンツを生成するヘルパー
 * CSS側で .tutorial-card を制御するため、ここでは構造のみ定義
 * @param {string} title - タイトル
 * @param {string} text - 本文（HTML可）
 * @param {string} emotion - 感情キー ('normal', 'happy', 'shock' etc.)
 * @returns {string} HTML文字列
 */
function makeContent(title, text, emotion = 'normal') {
    const imgSrc = getBlobcatImage(emotion);
    
    // アイコンの決定 (警告や重要事項には注意アイコン、それ以外は肉球)
    const icon = (emotion === 'shock' || emotion === 'serious')
        ? '<i class="fas fa-exclamation-triangle text-warning"></i>' 
        : '<i class="fas fa-paw"></i>';

    // HTML構造: カードの中に画像を絶対配置で置くスタイル
    return `
        <div class="tutorial-card">
            <img src="${imgSrc}" class="tutorial-character-img" alt="Nyanpuppu">
            <div class="tutorial-content">
                <div class="tutorial-title">${icon} ${title}</div>
                <div class="tutorial-text">${text}</div>
            </div>
        </div>
    `;
}

/**
 * 共通オプション設定
 */
function getIntroOptions() {
    return {
        nextLabel: '次へ',
        prevLabel: '戻る',
        doneLabel: '完了',
        skipLabel: '×', // スキップは×ボタンにする
        showProgress: false, // プログレスバーは非表示（シンプル化）
        exitOnOverlayClick: false,
        showStepNumbers: false,
        scrollToElement: true,
        scrollPadding: 80, // キャラクターが被らないよう少し余白を多めに
        positionPrecedence: ['bottom', 'top', 'right', 'left'],
        disableInteraction: true, // チュートリアル中は対象要素をクリック不可にする（誤操作防止）
    };
}

/**
 * サーバーへ完了ステータスを送信
 */
function markTutorialAsComplete(csrfToken, tutorialKey) {
    fetch('/api/tutorial/complete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({ key: tutorialKey })
    }).catch(console.error);
}

/* ==========================================================================
   各チュートリアル定義
   ========================================================================== */

/** 1. 新規ユーザー向けの初回チュートリアル */
function startInitialSetupTutorial(csrfToken) {
    const intro = introJs();
    intro.setOptions({
        ...getIntroOptions(),
        steps: [
            {
                title: 'Welcome',
                intro: makeContent(
                    'ようこそ！',
                    'はじめましてだにゃ！<br>バイクライフの記録を全力でサポートするよ。<br>まずは<b>愛車の登録</b>から始めよう！',
                    'wave' // -> cute (uwu)
                )
            },
            {
                element: document.querySelector('#tutorial-start-add-vehicle'),
                title: 'Start',
                intro: makeContent(
                    '登録ボタン',
                    'このボタンを押して、最初のバイクを登録しに行くにゃ！',
                    'excited' // -> cheer
                )
            }
        ]
    });
    intro.onexit(() => markTutorialAsComplete(csrfToken, 'initial_setup'));
    intro.start();
}

/** 2. 車両登録ページ */
function startVehicleFormTutorial(csrfToken) {
    const intro = introJs();
    intro.setOptions({
        ...getIntroOptions(),
        steps: [
            {
                title: '車両登録',
                intro: makeContent(
                    '愛車の登録',
                    '新しい相棒を登録するんだね！<br><b>「車両名」</b>さえ入力すれば、他は後回しでもOKだよ。',
                    'write' // -> taco
                )
            },
            {
                element: document.querySelector('#tutorial-vehicle-name'),
                title: '車両名',
                intro: makeContent(
                    '名前を入力',
                    '呼びやすい名前や車種名を入力してね。',
                    'explain' // -> normal
                )
            },
            {
                element: document.querySelector('#is_racer_checkbox'),
                title: 'レーサー設定',
                intro: makeContent(
                    '【重要】レーサー？',
                    '公道を走らない<b>競技車両</b>の場合だけチェックしてね。<br>管理が「距離」じゃなくて<b>「時間」</b>になるよ！<br><span class="text-danger">※後から変更できないから注意！</span>',
                    'serious' // -> normal (真剣)
                ),
                position: 'bottom'
            },
            {
                element: document.querySelector('#tutorial-initial-odometer'),
                title: '現在の距離',
                intro: makeContent(
                    'メーター読み',
                    '今の走行距離を入れておくと、そこから燃費計算をスタートできるにゃ。',
                    'normal' // -> normal
                )
            },
            {
                element: document.querySelector('#tutorial-drivetrain-data'),
                title: '詳細設定',
                intro: makeContent(
                    'マニアック設定',
                    'ギア比などの詳しい設定もできるけど、<b>今は空っぽで大丈夫</b>だにゃ！',
                    'relax' // -> comfy
                )
            },
            {
                element: document.querySelector('#tutorial-vehicle-submit'),
                title: '完了',
                intro: makeContent(
                    '登録する！',
                    '入力おつかれさま！<br>ボタンを押して登録完了だにゃ！',
                    'happy' // -> cheer
                ),
                position: 'top'
            }
        ]
    });
    intro.onexit(() => markTutorialAsComplete(csrfToken, 'vehicle_form'));
    intro.start();
}

/** 3. ダッシュボードツアー */
function startDashboardTour(csrfToken) {
    const intro = introJs();
    intro.setOptions({
        ...getIntroOptions(),
        steps: [
            {
                title: '登録完了',
                intro: makeContent(
                    'やったにゃ！',
                    'ガレージにバイクが追加されたよ！<br>画面の見方を簡単に教えるね。',
                    'happy' // -> cheer
                )
            },
            {
                element: document.querySelector('#quickActionBtn'),
                title: '記録メニュー',
                intro: makeContent(
                    '記録をつける',
                    '給油や整備をしたら、右下の<b>＋ボタン</b>を押してね。<br>ここからすぐに記録できるよ！',
                    'explain' // -> normal
                ),
                position: 'left'
            },
            {
                element: document.querySelector('[data-widget-name="reminders"]'),
                title: 'リマインダー',
                intro: makeContent(
                    'お知らせ',
                    'オイル交換などの時期が近づくと、僕がここでお知らせするにゃ！<br>安心して任せてね。',
                    'relax' // -> comfy
                )
            },
            {
                element: document.querySelector('[data-widget-name="timeline"]'),
                title: 'タイムライン',
                intro: makeContent(
                    '思い出',
                    '君とバイクの記録はここに時系列で並ぶよ。<br>たくさん走って記録を埋めてね！',
                    'wave' // -> cute
                )
            },
            {
                element: document.querySelector('#main-navbar'),
                title: 'メニュー',
                intro: makeContent(
                    'その他の機能',
                    '<b>「活動ログ」</b>でサーキット走行の管理や、ツーリングの記録もできるから試してみてね！',
                    'drive' // -> cheer
                ),
                position: 'bottom'
            },
            {
                element: document.querySelector('#edit-layout-btn'),
                title: 'レイアウト',
                intro: makeContent(
                    'カスタマイズ',
                    'このボタンで画面の並び順を自由に変えられるにゃ。<br>使いやすいようにアレンジしてね！',
                    'write' // -> taco
                )
            },
            {
                title: '完了',
                intro: makeContent(
                    '準備OK！',
                    '説明は以上だにゃ！<br>さあ、安全運転で楽しんでいこう〜！',
                    'happy' // -> cheer
                )
            }
        ]
    });
    intro.onexit(() => markTutorialAsComplete(csrfToken, 'dashboard_tour'));
    intro.start();
}

/** 4. 給油記録ページ */
function startFuelFormTutorial(csrfToken) {
    const intro = introJs();
    intro.setOptions({
        ...getIntroOptions(),
        steps: [
            {
                title: '給油',
                intro: makeContent(
                    '給油記録',
                    'ガス欠？それともツーリング？<br>給油の記録をつけて燃費を計算しよう！',
                    'drive' // -> cheer
                )
            },
            {
                element: document.querySelector('#tutorial-entry-date'),
                title: '日付',
                intro: makeContent(
                    'いつ入れた？',
                    '給油した日付を選んでね。<br>デフォルトは今日になってるにゃ。',
                    'normal' // -> normal
                )
            },
            {
                element: document.querySelector('#tutorial-odo-input'),
                title: '距離',
                intro: makeContent(
                    '走行距離',
                    '給油した時点の<b>総走行距離(ODO)</b>を入力してね。',
                    'explain' // -> normal
                )
            },
            {
                element: document.querySelector('#tutorial-volume-input'),
                title: '給油量',
                intro: makeContent(
                    '何リットル？',
                    'レシートを見て、入れたガソリンの量を入力してね。',
                    'write' // -> taco
                )
            },
            {
                element: document.querySelector('#search-gas-station-btn'),
                title: '検索',
                intro: makeContent(
                    'スタンド検索',
                    '「ここどこだっけ？」って時はここ！<br>Googleマップから場所を検索して自動入力できるよ。',
                    'excited' // -> cheer
                ),
                position: 'bottom'
            },
            {
                element: document.querySelector('#tutorial-full-tank-check'),
                title: '満タン',
                intro: makeContent(
                    '満タン？',
                    'もし<b>満タン</b>入れたなら、必ずチェックしてね！<br>これがないと燃費が計算できないんだ。',
                    'serious' // -> normal
                ),
                position: 'right'
            },
            {
                element: document.querySelector('#tutorial-fuel-submit'),
                title: '保存',
                intro: makeContent(
                    '保存する',
                    '入力OK？<br>ボタンを押して記録完了だにゃ！',
                    'happy' // -> cheer
                ),
                position: 'top'
            }
        ]
    });
    intro.onexit(() => markTutorialAsComplete(csrfToken, 'fuel_form'));
    intro.start();
}
// 手動実行: NODE_PATH=<jsdomのインストール先>/node_modules node --test tests/test_circuit_frontend.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const scripts = name => fs.readFileSync(path.join(__dirname, '../motopuppu/static/js', name), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));
async function ready(dom) {
    if (dom.window.document.readyState === 'loading') {
        await new Promise(resolve => dom.window.document.addEventListener('DOMContentLoaded', resolve, {once: true}));
    }
}

async function importPage(beta = false) {
    const dom = new JSDOM(`<div class="modal"><form class="import-form" action="/import" method="post">
      <div class="import-form-fields"><input name="csrf_token" value="test"><input type="file" name="csv_file"></div>
      <div class="import-progress-display d-none"><span class="import-progress-stage-text"></span>
        <span class="import-progress-detail"></span><div class="progress-bar"></div></div>
      <div class="import-error-display d-none"><span class="import-error-text"></span></div>
      ${beta ? `<div class="import-success-display d-none"><span data-import-laps></span><span data-import-removed></span>
        <span data-import-gps></span><span data-import-best></span><a data-import-gps-link></a><a data-import-detail-link></a></div>` : ''}
      <input type="submit"><button class="import-cancel-btn" type="button"></button>
      <button class="import-close-btn" type="button"></button></form></div>`,
      {url: 'https://example.test/activity/1/detail', runScripts: 'outside-only'});
    const window = dom.window;
    const requests = [];
    window.confirm = () => true;
    const timers = [];
    window.setTimeout = callback => { timers.push(callback); return 1; };
    window.XMLHttpRequest = class {
        constructor() { this.upload = {}; this.responseText = ''; this.status = 0; requests.push(this); }
        open() {}
        setRequestHeader() {}
        send(data) { this.data = data; }
    };
    window.eval(scripts('lap_import.js'));
    await ready(dom);
    const document = window.document;
    const form = document.querySelector('form');
    const submit = () => form.dispatchEvent(new window.Event('submit', {bubbles: true, cancelable: true}));
    const respond = (status, text) => {
        const xhr = requests.at(-1);
        Object.assign(xhr, {status, responseText: text, readyState: 3});
        xhr.onreadystatechange();
        xhr.onprogress();
        xhr.readyState = 4;
        xhr.onreadystatechange();
        xhr.onload();
    };
    return {dom, document, requests, timers, submit, respond};
}

test('Beta CSV: 結果とGPSへのリンクを残し、自動遷移・再送信しない', async () => {
    const page = await importPage(true);
    try {
        page.submit();
        page.respond(200, JSON.stringify({stage: 'done', summary: {
            imported_laps: 203, removed_laps: 2, gps_laps: 203, best_lap: '0:42.000',
        }, redirect_url: '/activity/1/detail?session_id=2#session-2', gps_url: '/activity/1/detail?session_id=2&gps=1'}));
        const result = page.document.querySelector('.import-success-display');
        assert.equal(result.classList.contains('d-none'), false);
        assert.equal(result.querySelector('[data-import-laps]').textContent, '203');
        assert.equal(result.querySelector('[data-import-removed]').textContent, '2');
        assert.equal(result.querySelector('[data-import-best]').textContent, '0:42.000');
        assert.equal(new URL(result.querySelector('[data-import-gps-link]').href).searchParams.get('gps'), '1');
        assert.equal(new URL(result.querySelector('[data-import-detail-link]').href).hash, '#session-2');
        assert.equal(page.timers.length, 0);
        assert.equal(page.document.querySelector('.import-close-btn').disabled, false);
        page.submit();
        assert.equal(page.requests.length, 1);
    } finally { page.dom.window.close(); }
});

test('Beta CSV: GPSのない取り込み結果では走行ラインへのリンクを隠す', async () => {
    const page = await importPage(true);
    try {
        page.submit();
        page.respond(200, JSON.stringify({stage: 'done', summary: {imported_laps: 2, gps_laps: 0}, gps_url: null}));
        assert.equal(page.document.querySelector('[data-import-gps-link]').hidden, true);
    } finally { page.dom.window.close(); }
});

test('CSV: 処理中のEsc・背景クリックで閉じるのを防ぎ、失敗後は閉じられる', async () => {
    const page = await importPage(true);
    try {
        const modal = page.document.querySelector('.modal');
        page.submit();
        const closing = new page.dom.window.Event('hide.bs.modal', {cancelable: true});
        modal.dispatchEvent(closing);
        assert.equal(closing.defaultPrevented, true);
        page.respond(400, '{"stage":"error","message":"形式エラー"}');
        const afterError = new page.dom.window.Event('hide.bs.modal', {cancelable: true});
        modal.dispatchEvent(afterError);
        assert.equal(afterError.defaultPrevented, false);
    } finally { page.dom.window.close(); }
});

for (const [name, status, body, expected] of [
    ['HTMLの413', 413, '<html>too large</html>\n', 'HTTP 413'],
    ['HTMLの502', 502, '<html>bad gateway</html>\n', 'HTTP 502'],
    ['空の503', 503, '', 'HTTP 503'],
    ['JSONの400', 400, '{"stage":"error","message":"ファイルを選択してください"}\n', 'ファイルを選択'],
]) {
    test(`CSV: ${name}でもエラーを表示し操作を復帰する`, async () => {
        const page = await importPage();
        try {
            page.submit();
            assert.equal(page.document.querySelector('input[type=submit]').disabled, true);
            page.respond(status, body);
            assert.equal(page.document.querySelector('.import-error-display').classList.contains('d-none'), false);
            assert.match(page.document.querySelector('.import-error-text').textContent, new RegExp(expected));
            assert.equal(page.document.querySelector('input[type=submit]').disabled, false);
            assert.equal(page.document.querySelector('.import-close-btn').disabled, false);
        } finally { page.dom.window.close(); }
    });
}

test('CSV: 完了通知なし・ログイン画面へのリダイレクトでも処理中に残らない', async () => {
    for (const body of ['{"stage":"parsing","message":"解析中"}\n', '<html>login</html>\n', 'null\n']) {
        const page = await importPage();
        try {
            page.submit();
            page.respond(200, body);
            assert.match(page.document.querySelector('.import-error-text').textContent, /完了を確認/);
            assert.equal(page.document.querySelector('input[type=submit]').disabled, false);
        } finally { page.dom.window.close(); }
    }
});

test('CSV: 末尾改行なしのdoneイベントを受信して成功表示する', async () => {
    const page = await importPage();
    try {
        page.submit();
        const xhr = page.requests[0];
        Object.assign(xhr, {status: 200, readyState: 3, responseText: '{"stage":"parsing"}\n'});
        xhr.onprogress();
        page.respond(200, xhr.responseText + '{"stage":"done","message":"203周を取り込みました"}');
        assert.equal(page.document.querySelector('.progress-bar').textContent, '100%');
        assert.equal(page.document.querySelector('.progress-bar').classList.contains('bg-success'), true);
        assert.match(page.document.querySelector('.import-progress-detail').textContent, /203周/);
        assert.equal(page.document.querySelector('.import-error-display').classList.contains('d-none'), true);
    } finally { page.dom.window.close(); }
});

test('CSV: 不確定な処理進捗を100%と表示せず二重送信を防ぐ', async () => {
    const page = await importPage();
    try {
        page.submit(); page.submit();
        assert.equal(page.requests.length, 1);
        page.requests[0].upload.onload();
        assert.equal(page.document.querySelector('.progress-bar').hasAttribute('aria-valuenow'), false);
        assert.equal(page.document.querySelector('.progress-bar').textContent, '');
        page.requests[0].onerror();
        assert.match(page.document.querySelector('.import-error-text').textContent, /通信エラー/);
        page.submit();
        assert.equal(page.requests.length, 2);
    } finally { page.dom.window.close(); }
});

const mapHtml = `<div id="mapModal"><div class="modal-dialog modal-xl">
  <span id="telemetrySessionName"></span><div id="lapSelectorContainer"></div><div id="map"></div>
  <div id="hud-overlay" class="d-none"><span id="hud-speed"></span><span id="hud-gear"></span>
    <span id="hud-rpm-val"></span><div id="hud-rpm-bar"></div><div class="hud-divider"></div>
    <div class="hud-gear-container"></div><div class="hud-rpm-container"></div></div>
  <div id="gear-display-container"><span id="currentGearDisplay"></span></div>
  <div id="playback-controls" class="d-none"><button id="playPauseBtn"></button>
    <span id="playbackTime"></span><input id="timelineScrubber" type="range" min="0" max="1000" value="0"></div>
  <div id="telemetry-graphs" class="d-none">
    ${['speedChart', 'rpmChart', 'throttleChart', 'gearChart'].map(id => `<div><canvas id="${id}"></canvas></div>`).join('')}
  </div><button id="toggleTelemetryBtn"></button>
  <input id="toggleBrakingPoints" type="checkbox" checked><input id="toggleAccelPoints" type="checkbox" checked>
</div></div>`;
const summary = {lap_times: ['1:00.000', '1:01.000', '1:02.000', '1:03.000'],
                 laps: [{lap_number: 3}, {lap_number: 4}], vehicle_specs: {}};
function lapData(number) {
    return {laps: [{lap_number: number, track: [0, 1, 2].map(i => ({
        lat: 35 + i / 1000, lng: 139 + i / 1000, runtime: 100 + i,
        speed: (number === 3 ? 30 : 80) + i,
        ...(number === 3 ? {rpm: 8000, throttle: 50} : {}),
    }))}]};
}
async function mapPage(fetchOverride, beta = false) {
    const betaControls = `<button id="previousLapBtn"></button><button id="nextLapBtn"></button><button id="bestLapBtn"></button>
      <div id="telemetry-metrics" hidden>${['speedChart','rpmChart','throttleChart','gearChart'].map(key => `<button data-metric="${key}"></button>`).join('')}</div>`;
    const dom = new JSDOM(beta ? mapHtml.replace('<div id="mapModal">', `<div id="mapModal" data-prefer-best="true">${betaControls}`) : mapHtml,
      {url: 'https://example.test/activity/1/detail', runScripts: 'outside-only'});
    const window = dom.window;
    const requests = [], charts = new Map(), frames = new Map(), maps = [], overlays = [];
    let frameId = 0;
    window.HTMLCanvasElement.prototype.getContext = function() { return {canvas: this}; };
    window.Chart = class {
        constructor(ctx, config) {
            assert.equal(charts.has(ctx.canvas.id), false, '古いグラフのCanvasを再利用している');
            this.id = ctx.canvas.id; this.data = config.data; this.options = config.options;
            charts.set(this.id, this);
        }
        update() { assert.equal(this.destroyed, undefined, '破棄済みグラフを更新している'); }
        destroy() { this.destroyed = true; charts.delete(this.id); }
    };
    window.requestAnimationFrame = callback => { frames.set(++frameId, callback); return frameId; };
    window.cancelAnimationFrame = id => frames.delete(id);
    class Overlay {
        constructor(options) { this.map = options.map; overlays.push(this); }
        setMap(map) { this.map = map; }
        setPosition(position) { this.position = position; }
        setVisible(visible) { this.visible = visible; }
    }
    window.google = {maps: {
        Map: class { constructor() { maps.push(this); } fitBounds() {} },
        Polyline: Overlay, Marker: Overlay, Point: class {}, SymbolPath: {CIRCLE: 'circle'},
        LatLngBounds: class { extend() {} isEmpty() { return false; } },
        event: {clearInstanceListeners(map) { map.cleared = true; }, trigger() {}},
    }};
    window.fetch = async (input, options) => {
        const url = new URL(input);
        requests.push({url, options});
        if (fetchOverride) {
            const result = fetchOverride(url, options);
            if (result) return result;
        }
        const data = url.searchParams.has('summary') ? summary : lapData(Number(url.searchParams.get('lap_number')));
        return {ok: true, json: async () => structuredClone(data)};
    };
    window.eval(scripts('map_viewer.js'));
    await ready(dom);
    const document = window.document;
    const init = options => window.motopuppuMapViewer.init({sessionId: 1, sessionName: '試験走行',
        dataUrl: '/activity/session/1/gps_data', ...options});
    const select = number => {
        const select = document.querySelector('#lapSelectorContainer select');
        select.value = number;
        select.dispatchEvent(new window.Event('change'));
    };
    return {dom, window, document, requests, charts, frames, maps, overlays, init, select};
}

test('Beta GPS: 指定した周・前後・GPS付きのベスト周を表示し、データのある指標だけ切り替える', async () => {
    const page = await mapPage(null, true);
    try {
        await page.init({lapNumber: 4});
        const byId = id => page.document.getElementById(id);
        const metric = id => page.document.querySelector(`[data-metric="${id}"]`);
        assert.equal(page.document.querySelector('select').value, '4');
        assert.equal(byId('nextLapBtn').disabled, true);
        assert.equal(metric('rpmChart').hidden, true);
        byId('previousLapBtn').click(); await settle();
        assert.equal(page.document.querySelector('select').value, '3');
        assert.equal(byId('previousLapBtn').disabled, true, 'GPSのないLap 1/2を選ばない');
        assert.equal(byId('bestLapBtn').disabled, true);
        assert.equal(metric('rpmChart').hidden, false);
        metric('rpmChart').click();
        assert.equal(metric('rpmChart').getAttribute('aria-pressed'), 'true');
        assert.equal(byId('speedChart').parentElement.style.display, 'none');
        assert.equal(byId('rpmChart').parentElement.style.display, 'block');
        const speed = page.charts.get('speedChart');
        assert.equal(speed.options.scales.x.type, 'linear');
        assert.deepEqual(Array.from(speed.data.datasets[0].data, point => point.x), [0, 1, 2]);
        byId('nextLapBtn').click(); await settle();
        assert.equal(metric('rpmChart').hidden, true);
        assert.equal(metric('speedChart').getAttribute('aria-pressed'), 'true');
        byId('bestLapBtn').click(); await settle();
        assert.equal(page.document.querySelector('select').value, '3');
    } finally { page.window.motopuppuMapViewer.destroy(page.document.querySelector('#mapModal')); page.dom.window.close(); }
});

test('Beta GPS: GPSのない周を指定したら理由を表示し、別の周を自動表示しない', async () => {
    const page = await mapPage(null, true);
    try {
        await page.init({lapNumber: 2});
        assert.equal(page.requests.length, 1, '別ラップを取得しない');
        assert.match(page.document.querySelector('[role="status"]').textContent, /Lap 2にはGPSがありません/);
        assert.equal(page.document.querySelector('select').value, '2');
        page.document.getElementById('nextLapBtn').click(); await settle();
        assert.equal(page.document.querySelector('select').value, '3');
        assert.equal(page.document.getElementById('toggleTelemetryBtn').disabled, false);
    } finally { page.window.motopuppuMapViewer.destroy(page.document.querySelector('#mapModal')); page.dom.window.close(); }
});

test('GPS: GPSなしの周を無効化し、ラップ番号で取得・表示・切り替えする', async () => {
    const page = await mapPage();
    try {
        await page.init();
        const options = [...page.document.querySelectorAll('option')];
        assert.equal(options[0].disabled, true);
        assert.equal(options[1].disabled, true);
        assert.match(options[0].textContent, /GPSなし/);
        assert.equal(page.requests[0].url.searchParams.get('summary'), '1');
        assert.equal(page.requests[1].url.searchParams.get('lap_number'), '3');
        assert.equal(page.document.querySelector('#hud-speed').textContent, '30');
        assert.equal(page.charts.size, 3);
        page.select(4); await settle();
        assert.equal(page.requests.at(-1).url.searchParams.get('lap_number'), '4');
        assert.equal(page.document.querySelector('#hud-speed').textContent, '80');
        assert.equal(page.charts.size, 1);
        page.select(3); await settle();
        assert.equal(page.document.querySelector('#hud-speed').textContent, '30');
        assert.equal(page.charts.size, 3);
        assert.equal(page.requests.length, 3, '直近ラップの再表示ではキャッシュを使う');
    } finally { page.dom.window.motopuppuMapViewer.destroy(page.document.querySelector('#mapModal')); page.dom.window.close(); }
});

test('GPS: モーダル終了で再生・グラフを解放し、再表示でイベントが重複しない', async () => {
    const page = await mapPage();
    try {
        const modal = page.document.querySelector('#mapModal');
        for (let i = 0; i < 2; i++) {
            await page.init();
            page.document.querySelector('#playPauseBtn').click();
            assert.equal(page.frames.size, 1);
            page.document.querySelector('#toggleTelemetryBtn').click();
            assert.equal(page.document.querySelector('.modal-dialog').classList.contains('modal-fullscreen'), true);
            modal.dispatchEvent(new page.window.Event('hidden.bs.modal'));
            assert.equal(page.frames.size, 0);
            assert.equal(page.charts.size, 0);
        }
        assert.equal(page.maps.every(map => map.cleared), true);
        assert.equal(page.overlays.every(overlay => overlay.map === null), true);
    } finally { page.dom.window.close(); }
});

test('GPS: 閉じた後に到着した一覧応答を描画しない', async () => {
    let resolve;
    const pending = new Promise(done => { resolve = done; });
    const page = await mapPage(url => url.searchParams.has('summary') ? pending : null);
    try {
        const loading = page.init();
        page.document.querySelector('#mapModal').dispatchEvent(new page.window.Event('hidden.bs.modal'));
        assert.equal(page.requests[0].options.signal.aborted, true);
        resolve({ok: true, json: async () => summary});
        await loading;
        assert.equal(page.requests.length, 1);
        assert.equal(page.charts.size, 0);
    } finally { page.dom.window.close(); }
});

test('GPS: 遅れて届いた別ラップの応答で現在の選択を上書きしない', async () => {
    let resolve;
    const pending = new Promise(done => { resolve = done; });
    const page = await mapPage(url => url.searchParams.get('lap_number') === '4' ? pending : null);
    try {
        await page.init();
        page.select(4);
        page.select(3); await settle();
        resolve({ok: true, json: async () => lapData(4)});
        await settle();
        assert.equal(page.requests.at(-1).options.signal.aborted, true);
        assert.equal(page.document.querySelector('#hud-speed').textContent, '30');
        assert.equal(page.document.querySelector('select').value, '3');
    } finally { page.window.motopuppuMapViewer.destroy(page.document.querySelector('#mapModal')); page.dom.window.close(); }
});

test('GPS: 公開共有ページでもトークン付きURLから選択した周を取得する', async () => {
    const page = await mapPage();
    try {
        await page.init({isPublicPage: true, dataUrl: '/activity/share/session/test-token/gps_data'});
        page.select(4); await settle();
        assert.equal(page.requests.at(-1).url.pathname, '/activity/share/session/test-token/gps_data');
        assert.equal(page.requests.at(-1).url.searchParams.get('lap_number'), '4');
        assert.equal(page.document.querySelector('#hud-speed').textContent, '80');
    } finally { page.window.motopuppuMapViewer.destroy(page.document.body); page.dom.window.close(); }
});

test('GPS: 戻る操作用のページ保存では地図を維持し、ページ終了時は破棄する', async () => {
    const page = await mapPage();
    try {
        await page.init();
        page.window.dispatchEvent(new page.window.PageTransitionEvent('pagehide', {persisted: true}));
        assert.equal(page.charts.size, 3);
        page.window.dispatchEvent(new page.window.PageTransitionEvent('pagehide', {persisted: false}));
        assert.equal(page.charts.size, 0);
        assert.equal(page.maps[0].cleared, true);
    } finally { page.dom.window.close(); }
});

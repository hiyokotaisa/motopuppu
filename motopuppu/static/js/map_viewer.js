// motopuppu/static/js/map_viewer.js
// ▼▼▼【ここから全体を修正】▼▼▼

// グローバルスコープに関数を公開するためのオブジェクト
window.motopuppuMapViewer = {
    init: async function(options) {
        // オプションから設定を取得
        const sessionId = options.sessionId;
        const sessionName = options.sessionName;
        const dataUrl = options.dataUrl;
        const isPublicPage = options.isPublicPage || false;

        // 実行コンテナ（モーダルか、通常のページか）
        const container = isPublicPage ? document.body : document.getElementById('mapModal');
        if (!container) return;
        
        // --- グローバル変数定義 ---
        let map;
        let polylines = [];
        let brakingMarkers = [];
        let accelMarkers = [];
        let bikeMarker = null; // バイクの現在位置を示すマーカー
        let bounds;
        let charts = { speed: null, rpm: null, throttle: null };
        let currentLapData = null;
        let animationFrameId = null;
        let isPlaying = false;
        let playbackStartTime = 0; // 再生開始時刻 (Unixタイムスタンプ)
        let playbackStartOffset = 0; // 一時停止からの再開時のオフセット(秒)
        let lapStartTime = 0; // ★【追加】現在のラップの開始時間を記録する変数

        // --- 関数定義 (内部ヘルパー) ---
        function initializeMap(containerId) {
            const mapContainer = document.getElementById(containerId);
            if (!mapContainer || typeof google === 'undefined') return null;
            mapContainer.innerHTML = ''; // スピナーをクリア
            return new google.maps.Map(mapContainer, {
                mapTypeId: 'satellite', streetViewControl: false, mapTypeControl: false, fullscreenControl: false,
            });
        }
        function setupChart(canvasId, label, color) {
            if (charts[canvasId]) {
                charts[canvasId].destroy();
            }
            const ctx = document.getElementById(canvasId).getContext('2d');
            return new Chart(ctx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: label,
                        data: [],
                        borderColor: color,
                        borderWidth: 2,
                        pointRadius: 0,
                        tension: 0.1,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: { enabled: false },
                        // 縦線カーソル用のプラグイン設定
                        annotation: {
                            annotations: {
                                line1: {
                                    type: 'line',
                                    scaleID: 'x',
                                    value: 0,
                                    borderColor: 'rgba(255, 99, 132, 0.8)',
                                    borderWidth: 1,
                                    display: false, // 初期状態は非表示
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            ticks: { display: false },
                            grid: { display: false }
                        },
                        y: {
                            beginAtZero: true,
                            ticks: {
                                font: { size: 10 }
                            },
                            title: {
                                display: true,
                                text: label,
                                font: { size: 12 }
                            }
                        }
                    }
                }
            });
        }
        function getColorForSpeed(speed, minSpeed, maxSpeed) {
            if (speed < minSpeed) speed = minSpeed;
            if (speed > maxSpeed) speed = maxSpeed;
            const range = maxSpeed - minSpeed;
            if (range === 0) return '#00FF00';
            const ratio = (speed - minSpeed) / range;
            let r, g, b;
            if (ratio < 0.5) {
                r = 255;
                g = Math.round(255 * (ratio * 2));
                b = 0;
            } else {
                r = Math.round(255 * (1 - (ratio - 0.5) * 2));
                g = 255;
                b = Math.round(255 * ((ratio - 0.5) * 2));
            }
            return `rgb(${r},${g},${b})`;
        }
        function drawLapPolyline(track, minSpeed, maxSpeed, mapInstance) {
            const lapPolylines = [];
            for (let i = 0; i < track.length - 1; i++) {
                const startPoint = track[i];
                const endPoint = track[i + 1];
                const avgSpeed = ((startPoint.speed || 0) + (endPoint.speed || 0)) / 2;
                const color = getColorForSpeed(avgSpeed, minSpeed, maxSpeed);
                const segment = new google.maps.Polyline({
                    path: [startPoint, endPoint],
                    geodesic: true,
                    strokeColor: color,
                    strokeOpacity: 1.0,
                    strokeWeight: 4,
                });
                if (mapInstance) segment.setMap(mapInstance);
                lapPolylines.push(segment);
            }
            return lapPolylines;
        }
        function findSignificantPoints(track, options = {}) {
            const {
                lookahead = 25,
                speedChangeThreshold = 4.0,
                cooldown = 30,
            } = options;
    
            const brakingPoints = [];
            const accelPoints = [];
            
            if (track.length < lookahead + 1) return { brakingPoints, accelPoints };
    
            let lastBrakeIndex = -cooldown;
            let lastAccelIndex = -cooldown;
    
            for (let i = 0; i < track.length - lookahead; i++) {
                const currentPoint = track[i];
                const futurePoint = track[i + lookahead];
    
                if (currentPoint.speed === undefined || futurePoint.speed === undefined) continue;
    
                const speedDiff = currentPoint.speed - futurePoint.speed;
    
                if (speedDiff > speedChangeThreshold && i > lastBrakeIndex + cooldown) {
                    brakingPoints.push(currentPoint);
                    lastBrakeIndex = i;
                }
                else if (-speedDiff > speedChangeThreshold && i > lastAccelIndex + cooldown) {
                    accelPoints.push(currentPoint);
                    lastAccelIndex = i;
                }
            }
            return { brakingPoints, accelPoints };
        }
        function createMarker(point, icon, mapInstance) {
            return new google.maps.Marker({
                position: point,
                icon: icon,
                map: mapInstance,
                title: `Speed: ${point.speed.toFixed(1)} km/h`
            });
        }
        
        // 時間をフォーマットするヘルパー関数
        function formatRuntime(totalSeconds) {
            if (isNaN(totalSeconds) || totalSeconds < 0) totalSeconds = 0;
            const minutes = Math.floor(totalSeconds / 60);
            const seconds = Math.floor(totalSeconds % 60);
            const milliseconds = Math.floor((totalSeconds * 1000) % 1000);
            return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(milliseconds).padStart(3, '0')}`;
        }
        
        function updateDashboard(index) {
            if (!currentLapData || index < 0 || index >= currentLapData.track.length) return;
            const point = currentLapData.track[index];
            if (bikeMarker) { bikeMarker.setPosition({ lat: point.lat, lng: point.lng }); }
            Object.values(charts).forEach(chart => {
                if (chart) {
                    chart.options.plugins.annotation.annotations.line1.value = index;
                    chart.options.plugins.annotation.annotations.line1.display = true;
                    chart.update('none');
                }
            });
            const scrubber = container.querySelector('#timelineScrubber');
            if (scrubber) { scrubber.value = index; }

            // ★【修正】時間表示を更新 (ラップ内経過時間)
            const timeDisplay = container.querySelector('#playbackTime');
            if (timeDisplay) {
                const intraLapTime = (point.runtime || 0) - lapStartTime;
                timeDisplay.textContent = formatRuntime(intraLapTime);
            }
        }

        // 新しいタイムベースの再生ループ
        function playLoop() {
            if (!isPlaying) return;

            const elapsedTime = (Date.now() - playbackStartTime) / 1000 + playbackStartOffset;
            const totalDuration = currentLapData.track[currentLapData.track.length - 1].runtime || 0;

            if (elapsedTime >= totalDuration) {
                updateDashboard(currentLapData.track.length - 1);
                stopPlayback();
                return;
            }

            // 経過時間に最も近いデータ点を探す
            let currentIndex = 0;
            for (let i = 0; i < currentLapData.track.length; i++) {
                if (currentLapData.track[i].runtime >= elapsedTime) {
                    currentIndex = i;
                    break;
                }
            }
            
            updateDashboard(currentIndex);
            animationFrameId = requestAnimationFrame(playLoop);
        }

        function startPlayback() {
            if (isPlaying || !currentLapData) return;
            isPlaying = true;

            // スクラバーの現在位置から再生オフセットを決定
            const scrubber = container.querySelector('#timelineScrubber');
            const currentIndex = parseInt(scrubber.value, 10);
            playbackStartOffset = currentLapData.track[currentIndex]?.runtime || 0;

            playbackStartTime = Date.now();
            container.querySelector('#playPauseBtn').innerHTML = '<i class="fas fa-pause"></i>';
            playLoop();
        }

        function stopPlayback() {
            if (!isPlaying) return;
            isPlaying = false;
            cancelAnimationFrame(animationFrameId);
            const playBtn = container.querySelector('#playPauseBtn');
            if(playBtn) playBtn.innerHTML = '<i class="fas fa-play"></i>';
            
            // 再生オフセットを更新
            const scrubber = container.querySelector('#timelineScrubber');
            const currentIndex = parseInt(scrubber.value, 10);
            if (currentLapData) {
                playbackStartOffset = currentLapData.track[currentIndex]?.runtime || 0;
            }
        }

        // --- メイン処理 ---
        const telemetrySessionName = container.querySelector('#telemetrySessionName');
        if (telemetrySessionName) telemetrySessionName.textContent = sessionName;

        const mapContainer = container.querySelector('#mapContainer');
        const lapSelectorContainer = container.querySelector('#lapSelectorContainer');
        mapContainer.innerHTML = `<div class="d-flex justify-content-center align-items-center h-100"><div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div></div>`;
        lapSelectorContainer.innerHTML = `<p class="text-muted">走行データを読み込んでいます...</p>`;

        if (!map) { map = initializeMap('mapContainer'); }
        
        try {
            const response = await fetch(dataUrl);
            if (!response.ok) throw new Error('Failed to load GPS data.');
            const data = await response.json();
            
            if (!data.laps || data.laps.length === 0 || !data.lap_times || data.lap_times.length === 0) {
                mapContainer.innerHTML = '';
                lapSelectorContainer.innerHTML = `<div class="alert alert-warning">データがありません。</div>`;
                return;
            }

            const parseTimeToSeconds = (timeStr) => {
                if (!timeStr || typeof timeStr !== 'string') return Infinity;
                const parts = timeStr.split(':');
                try {
                    if (parts.length === 2) return parseFloat(parts[0]) * 60 + parseFloat(parts[1]);
                    if (parts.length === 1) return parseFloat(parts[0]);
                } catch (e) { return Infinity; }
                return Infinity;
            };
            let bestLapIndex = -1;
            let minTime = Infinity;
            data.lap_times.map(parseTimeToSeconds).forEach((time, index) => {
                if (time < minTime) { minTime = time; bestLapIndex = index; }
            });

            lapSelectorContainer.innerHTML = '';
            const lapSelect = document.createElement('select');
            lapSelect.className = 'form-select';
            data.lap_times.forEach((lapTime, index) => {
                const option = document.createElement('option');
                option.value = index;
                const isBest = index === bestLapIndex;
                option.textContent = `${isBest ? '👑 ' : ''}Lap ${index + 1} (${lapTime})`;
                lapSelect.appendChild(option);
            });
            lapSelectorContainer.appendChild(lapSelect);

            const loadLapData = (lapIndex) => {
                stopPlayback();
                currentLapData = data.laps[lapIndex];
                if (!currentLapData || !currentLapData.track || currentLapData.track.length < 2) return;
                
                // ★【追加】ラップの開始時間を記録
                lapStartTime = currentLapData.track[0]?.runtime || 0;

                polylines.flat().forEach(p => p.setMap(null));
                brakingMarkers.flat().forEach(m => m.setMap(null));
                accelMarkers.flat().forEach(m => m.setMap(null));
                if (bikeMarker) bikeMarker.setMap(null);
                polylines = []; brakingMarkers = []; accelMarkers = [];

                const speeds = currentLapData.track.map(p => p.speed).filter(s => s > 0);
                const minSpeed = speeds.length > 0 ? Math.min(...speeds) : 0;
                const maxSpeed = currentLapData.track.map(p => p.speed).reduce((max, s) => Math.max(max, s || 0), 0);

                bounds = new google.maps.LatLngBounds();
                currentLapData.track.forEach(p => bounds.extend(p));
                if (map && !bounds.isEmpty()) { map.fitBounds(bounds); }
                
                polylines = drawLapPolyline(currentLapData.track, minSpeed, maxSpeed, map);
                const { brakingPoints, accelPoints } = findSignificantPoints(currentLapData.track);
                const brakingIcon = { path: 'M0,-5 L5,5 L-5,5 Z', fillColor: 'red', fillOpacity: 1.0, strokeWeight: 0, rotation: 180, scale: 0.8, anchor: new google.maps.Point(0, 0) };
                const accelIcon = { path: 'M0,-5 L5,5 L-5,5 Z', fillColor: 'limegreen', fillOpacity: 1.0, strokeWeight: 0, scale: 0.8, anchor: new google.maps.Point(0, 0) };
                brakingMarkers = brakingPoints.map(p => createMarker(p, brakingIcon, map));
                accelMarkers = accelPoints.map(p => createMarker(p, accelIcon, map));
                const bikeIcon = { path: google.maps.SymbolPath.CIRCLE, scale: 5, fillColor: 'yellow', strokeColor: 'black', strokeWeight: 1 };
                bikeMarker = new google.maps.Marker({ position: currentLapData.track[0], icon: bikeIcon, map: map, zIndex: 100 });
                
                // ★【修正】X軸のラベルをラップ内経過時間に変更
                const labels = currentLapData.track.map(p => ((p.runtime || 0) - lapStartTime).toFixed(2));
                charts.speed = setupChart('speedChart', '速度 (km/h)', 'rgba(54, 162, 235, 1)');
                charts.rpm = setupChart('rpmChart', 'エンジン回転数 (rpm)', 'rgba(255, 99, 132, 1)');
                charts.throttle = setupChart('throttleChart', 'スロットル開度 (%)', 'rgba(75, 192, 192, 1)');
                charts.speed.data.labels = labels;
                charts.speed.data.datasets[0].data = currentLapData.track.map(p => p.speed);
                charts.rpm.data.labels = labels;
                charts.rpm.data.datasets[0].data = currentLapData.track.map(p => p.rpm);
                charts.throttle.data.labels = labels;
                charts.throttle.data.datasets[0].data = currentLapData.track.map(p => p.throttle);
                Object.values(charts).forEach(chart => chart.update());

                const scrubber = container.querySelector('#timelineScrubber');
                scrubber.max = currentLapData.track.length - 1;
                updateDashboard(0);
                // 再生オフセットをリセット
                playbackStartOffset = 0;
            };

            lapSelect.addEventListener('change', (e) => loadLapData(parseInt(e.target.value, 10)));
            container.querySelector('#timelineScrubber').addEventListener('input', (e) => {
                stopPlayback(); 
                const newIndex = parseInt(e.target.value, 10);
                updateDashboard(newIndex);
                // 新しいオフセットを設定
                playbackStartOffset = currentLapData.track[newIndex]?.runtime || 0;
            });
            container.querySelector('#playPauseBtn').addEventListener('click', () => {
                if (isPlaying) stopPlayback(); else startPlayback();
            });
            container.querySelector('#toggleBrakingPoints').addEventListener('change', (e) => {
                brakingMarkers.forEach(m => m.setVisible(e.target.checked));
            });
            container.querySelector('#toggleAccelPoints').addEventListener('change', (e) => {
                accelMarkers.forEach(m => m.setVisible(e.target.checked));
            });
            
            // モーダル専用の処理
            if (!isPublicPage) {
                container.querySelector('#toggleTelemetryBtn').addEventListener('click', (e) => {
                    const btn = e.currentTarget;
                    const modalDialog = container.querySelector('.modal-dialog');
                    const playbackControls = container.querySelector('#playback-controls');
                    const graphsContainer = container.querySelector('#telemetry-graphs');
                    const isTelemetryVisible = !graphsContainer.classList.contains('d-none');
                    if (isTelemetryVisible) {
                        modalDialog.classList.remove('modal-fullscreen'); modalDialog.classList.add('modal-xl');
                        playbackControls.classList.add('d-none'); graphsContainer.classList.add('d-none');
                        btn.innerHTML = '<i class="fas fa-chart-line me-1"></i> テレメトリを表示';
                        btn.classList.remove('btn-success'); btn.classList.add('btn-outline-primary');
                    } else {
                        modalDialog.classList.remove('modal-xl'); modalDialog.classList.add('modal-fullscreen');
                        playbackControls.classList.remove('d-none'); graphsContainer.classList.remove('d-none');
                        btn.innerHTML = '<i class="fas fa-map-marked-alt me-1"></i> シンプル表示に戻す';
                        btn.classList.remove('btn-outline-primary'); btn.classList.add('btn-success');
                    }
                    setTimeout(() => { if(map && bounds && !bounds.isEmpty()){ google.maps.event.trigger(map, 'resize'); map.fitBounds(bounds); } }, 200);
                });
            }

            loadLapData(0);

        } catch (error) {
            console.error('Error:', error);
            mapContainer.innerHTML = '';
            lapSelectorContainer.innerHTML = `<div class="alert alert-danger">データの読み込みに失敗しました。</div>`;
        }
    }
};

// 元のイベントリスナーは、新しいグローバル関数を呼び出すだけのシンプルな形にする
document.addEventListener('DOMContentLoaded', () => {
    const mapModalElement = document.getElementById('mapModal');
    if (!mapModalElement) return;

    mapModalElement.addEventListener('show.bs.modal', (event) => {
        const button = event.relatedTarget;
        const sessionId = button.dataset.sessionId;
        
        window.motopuppuMapViewer.init({
            sessionId: sessionId,
            sessionName: button.dataset.sessionName,
            dataUrl: `/activity/session/${sessionId}/gps_data`,
            isPublicPage: false
        });
    });

    mapModalElement.addEventListener('hidden.bs.modal', () => {
        // stopPlayback に相当する処理が必要だが、スコープ外なので一旦保留
        // 必要であれば、init関数が状態をリセットする口を持つようにする
    });
});
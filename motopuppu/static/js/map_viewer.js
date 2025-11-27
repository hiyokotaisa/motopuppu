// motopuppu/static/js/map_viewer.js
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
        let charts = { speed: null, rpm: null, throttle: null, gear: null };
        let currentLapData = null;
        let smoothedGears = [];
        let animationFrameId = null;
        let isPlaying = false;
        let playbackStartTime = 0; 
        let playbackStartOffset = 0;
        let lapStartTime = 0;
        
        // パフォーマンス最適化用変数
        let lastPlaybackIndex = 0;
        
        // ▼▼▼ 追加: チャート更新間引き用の時間管理変数 ▼▼▼
        let lastChartUpdateTime = 0;
        const CHART_UPDATE_INTERVAL = 100; // ミリ秒 (0.1秒に1回更新)
        // ▲▲▲ 追加ここまで ▲▲▲

        // --- 関数定義 (内部ヘルパー) ---
        function initializeMap(containerId) {
            const mapContainer = document.getElementById(containerId);
            if (!mapContainer || typeof google === 'undefined') return null;
            
            return new google.maps.Map(mapContainer, {
                mapTypeId: 'satellite', streetViewControl: false, mapTypeControl: false, fullscreenControl: false,
            });
        }
        function setupChart(canvasId, label, color, chartType = 'line', yAxisOptions = {}) {
            if (charts[canvasId]) {
                charts[canvasId].destroy();
            }
            const canvasEl = document.getElementById(canvasId);
            if (!canvasEl) {
                // console.error(`Chart canvas element with ID "${canvasId}" not found.`); // エラー抑制
                return null;
            }
            const ctx = canvasEl.getContext('2d');
            const defaultYAxisOptions = {
                beginAtZero: true,
                ticks: { font: { size: 10 } },
                title: { display: true, text: label, font: { size: 12 } }
            };
            return new Chart(ctx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: label,
                        data: [],
                        borderColor: color,
                        backgroundColor: color, // ギアチャート用
                        borderWidth: 2,
                        pointRadius: 0,
                        tension: chartType === 'line' ? 0.1 : 0,
                        stepped: chartType === 'step'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: { enabled: false },
                        annotation: {
                            annotations: {
                                line1: {
                                    type: 'line',
                                    scaleID: 'x',
                                    value: 0,
                                    borderColor: 'rgba(255, 99, 132, 0.8)',
                                    borderWidth: 1,
                                    display: false,
                                }
                            }
                        }
                    },
                    scales: {
                        x: { ticks: { display: false }, grid: { display: false } },
                        y: { ...defaultYAxisOptions, ...yAxisOptions }
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
                b = 0;
            }
            return `rgb(${r},${g},${b})`;
        }

        // ▼▼▼ 修正: 速度バケットを使ってPolylineを統合し、描画オブジェクト数を削減する ▼▼▼
        function drawLapPolyline(track, minSpeed, maxSpeed, mapInstance) {
            const lapPolylines = [];
            if (!track || track.length < 2) return lapPolylines;

            let currentPath = [track[0]];
            
            // 速度の「バケツ（階級）」を作る関数
            const getSpeedBucketColor = (speed) => {
                const range = maxSpeed - minSpeed || 1;
                const step = range / 20; // 20段階
                const bucketSpeed = Math.floor((speed - minSpeed) / step) * step + minSpeed;
                return getColorForSpeed(bucketSpeed, minSpeed, maxSpeed);
            };
            
            let currentColor = getSpeedBucketColor(track[0].speed || 0);

            for (let i = 1; i < track.length; i++) {
                const point = track[i];
                const nextColor = getSpeedBucketColor(point.speed || 0);

                // 色が変わったら、ここまでのパスでPolylineを作成してリセット
                if (nextColor !== currentColor) {
                    currentPath.push(point); // つなぎ目を滑らかにするため点を含める

                    const segment = new google.maps.Polyline({
                        path: currentPath,
                        geodesic: true,
                        strokeColor: currentColor,
                        strokeOpacity: 1.0,
                        strokeWeight: 4,
                        zIndex: 1 // マーカーより下
                    });
                    if (mapInstance) segment.setMap(mapInstance);
                    lapPolylines.push(segment);

                    currentPath = [point];
                    currentColor = nextColor;
                } else {
                    currentPath.push(point);
                }
            }

            if (currentPath.length > 1) {
                const segment = new google.maps.Polyline({
                    path: currentPath,
                    geodesic: true,
                    strokeColor: currentColor,
                    strokeOpacity: 1.0,
                    strokeWeight: 4,
                    zIndex: 1
                });
                if (mapInstance) segment.setMap(mapInstance);
                lapPolylines.push(segment);
            }

            return lapPolylines;
        }
        // ▲▲▲ 修正ここまで ▲▲▲

        function findSignificantPoints(track, options = {}) {
            const { lookahead = 25, speedChangeThreshold = 4.0, cooldown = 30 } = options;
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
            return new google.maps.Marker({ position: point, icon: icon, map: mapInstance, title: `Speed: ${point.speed.toFixed(1)} km/h` });
        }
        function formatRuntime(totalSeconds) {
            if (isNaN(totalSeconds) || totalSeconds < 0) totalSeconds = 0;
            const minutes = Math.floor(totalSeconds / 60);
            const seconds = Math.floor(totalSeconds % 60);
            const milliseconds = Math.floor((totalSeconds * 1000) % 1000);
            return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(milliseconds).padStart(3, '0')}`;
        }
        
        function parseTireSize(sizeString) {
            if (!sizeString) return null;
            const regex = /(\d+)\s*\/\s*(\d+)\s*[A-Z-]*\s*(\d+)/;
            const match = sizeString.match(regex);
            if (match && match.length === 4) {
                return [parseInt(match[1], 10), parseInt(match[2], 10), parseInt(match[3], 10)];
            }
            return null;
        }

        function calculateTireCircumference(width, aspectRatio, rimDiameter) {
            const rimDiameterMm = rimDiameter * 25.4;
            const sidewallHeightMm = width * (aspectRatio / 100);
            const totalDiameterMm = rimDiameterMm + (2 * sidewallHeightMm);
            return (totalDiameterMm * Math.PI) / 1000;
        }
        
        function estimateGear(point, specs) {
            if (!specs || !specs.primary_ratio || !specs.gear_ratios || !specs.front_sprocket || !specs.rear_sprocket || !specs.rear_tyre_size || !point.rpm || !point.speed) {
                return null;
            }
            const parsedTire = parseTireSize(specs.rear_tyre_size);
            if (!parsedTire) return null;
            const tireCircumferenceM = calculateTireCircumference(...parsedTire);

            const secondary_ratio = specs.rear_sprocket / specs.front_sprocket;
            let best_gear = null;
            let min_diff = Infinity;

            for (const [gear, gear_ratio] of Object.entries(specs.gear_ratios)) {
                if (point.rpm === 0) continue;
                
                const total_ratio = specs.primary_ratio * secondary_ratio * gear_ratio;
                const calculated_speed = (point.rpm / total_ratio) * tireCircumferenceM * 60 / 1000;
                
                const diff = Math.abs(calculated_speed - point.speed);

                if (diff < min_diff) {
                    min_diff = diff;
                    best_gear = parseInt(gear, 10);
                }
            }
            
            if (min_diff > (point.speed * 0.2 + 5)) {
                return null;
            }
            return best_gear;
        }

        function applySmoothingFilter(data, windowSize) {
            const smoothed = [];
            const halfWindow = Math.floor(windowSize / 2);

            for (let i = 0; i < data.length; i++) {
                const start = Math.max(0, i - halfWindow);
                const end = Math.min(data.length, i + halfWindow + 1);
                const window = data.slice(start, end).filter(val => val !== null);

                if (window.length === 0) {
                    smoothed.push(data[i]);
                    continue;
                }

                const counts = window.reduce((acc, val) => {
                    acc[val] = (acc[val] || 0) + 1;
                    return acc;
                }, {});

                const mode = Object.keys(counts).reduce((a, b) => counts[a] > counts[b] ? a : b);
                smoothed.push(parseInt(mode, 10));
            }
            return smoothed;
        }


        // ▼▼▼ 修正: indexとratioを受け取り、チャート更新を間引くロジックを追加 ▼▼▼
        function updateDashboard(index, ratio = 0) {
            if (!currentLapData || index < 0 || index >= currentLapData.track.length) return;
            
            // --- 1. マーカー位置の計算（補間あり：毎フレーム実行） ---
            const p1 = currentLapData.track[index];
            const p2 = currentLapData.track[index + 1] || p1; 

            // 緯度経度の線形補間 (Linear Interpolation)
            const lat = p1.lat + (p2.lat - p1.lat) * ratio;
            const lng = p1.lng + (p2.lng - p1.lng) * ratio;

            if (bikeMarker) { 
                bikeMarker.setPosition({ lat: lat, lng: lng }); 
            }
            
            // --- 2. HUD表示の計算（補間あり：毎フレーム実行） ---
            const speed = (p1.speed || 0) + ((p2.speed || 0) - (p1.speed || 0)) * ratio;
            const rpm = (p1.rpm || 0) + ((p2.rpm || 0) - (p1.rpm || 0)) * ratio;

            // HUDオーバーレイの更新
            const hudOverlay = container.querySelector('#hud-overlay');
            if (hudOverlay) {
                hudOverlay.classList.remove('d-none');
                
                const currentGear = smoothedGears[index];
                const hudGearEl = container.querySelector('#hud-gear');
                if (hudGearEl) hudGearEl.textContent = currentGear !== null ? currentGear : '-';
                
                const hudSpeedEl = container.querySelector('#hud-speed');
                if (hudSpeedEl) hudSpeedEl.textContent = Math.round(speed);
                
                const hudRpmEl = container.querySelector('#hud-rpm-val');
                const hudRpmBar = container.querySelector('#hud-rpm-bar');
                if (hudRpmEl && hudRpmBar) {
                    const rpmVal = Math.round(rpm);
                    hudRpmEl.textContent = rpmVal;
                    
                    const maxRpm = 14000; 
                    const percentage = Math.min((rpmVal / maxRpm) * 100, 100);
                    hudRpmBar.style.width = `${percentage}%`;
                    
                    if (percentage > 85) {
                        hudRpmBar.className = 'progress-bar bg-danger';
                    } else {
                        hudRpmBar.className = 'progress-bar bg-warning';
                    }
                }
            }
            
            const gearDisplay = container.querySelector('#currentGearDisplay');
            if (gearDisplay) {
                const currentGear = smoothedGears[index];
                gearDisplay.textContent = currentGear !== null ? currentGear : 'N';
            }

            // --- 3. チャート・スクラバーの更新（時間間引きあり） ---
            // 現在時刻を取得
            const now = Date.now();
            
            // 前回の更新から一定時間（100ms）経過しているか、または再生停止中（強制更新）の場合のみ実行
            if (now - lastChartUpdateTime > CHART_UPDATE_INTERVAL || !isPlaying) {
                
                Object.values(charts).forEach(chart => {
                    if (chart) {
                        chart.options.plugins.annotation.annotations.line1.value = index + ratio; // 補間位置も反映
                        chart.options.plugins.annotation.annotations.line1.display = true;
                        chart.update('none'); // アニメーションなしで高速更新
                    }
                });
                
                const scrubber = container.querySelector('#timelineScrubber');
                if (scrubber) { 
                    scrubber.value = index; 
                }
                
                const timeDisplay = container.querySelector('#playbackTime');
                if (timeDisplay) {
                    const currentRuntime = (p1.runtime || 0) + ((p2.runtime || 0) - (p1.runtime || 0)) * ratio;
                    const intraLapTime = currentRuntime - lapStartTime;
                    timeDisplay.textContent = formatRuntime(intraLapTime);
                }

                // 更新時刻を記録
                lastChartUpdateTime = now;
            }
        }
        // ▲▲▲ 修正ここまで ▲▲▲

        function playLoop() {
            if (!isPlaying) return;
            const elapsedTime = (Date.now() - playbackStartTime) / 1000 + playbackStartOffset;
            const totalDuration = currentLapData.track[currentLapData.track.length - 1].runtime || 0;
            
            if (elapsedTime >= totalDuration) {
                updateDashboard(currentLapData.track.length - 1);
                stopPlayback();
                return;
            }

            // ▼▼▼ 修正: 検索ロジックを「区間探索」に変更し、ratioを計算する ▼▼▼
            let currentIndex = lastPlaybackIndex;
            
            // 安全策: インデックスが範囲外や、時間が戻った場合はリセット
            if (currentIndex >= currentLapData.track.length - 1 || (currentLapData.track[currentIndex] && currentLapData.track[currentIndex].runtime > elapsedTime)) {
                currentIndex = 0;
            }

            // elapsedTime が含まれる区間 [i, i+1] を探す
            for (let i = currentIndex; i < currentLapData.track.length - 1; i++) {
                const pNow = currentLapData.track[i];
                const pNext = currentLapData.track[i + 1];
                
                if (pNow.runtime <= elapsedTime && elapsedTime < pNext.runtime) {
                    currentIndex = i;
                    break;
                }
            }
            
            lastPlaybackIndex = currentIndex; // 次回のために保存

            // 補間係数 (ratio) の計算: 0.0 〜 1.0
            const p1 = currentLapData.track[currentIndex];
            const p2 = currentLapData.track[currentIndex + 1];
            let ratio = 0;
            
            if (p1 && p2 && (p2.runtime - p1.runtime) > 0) {
                ratio = (elapsedTime - p1.runtime) / (p2.runtime - p1.runtime);
            }
            
            if (ratio < 0) ratio = 0;
            if (ratio > 1) ratio = 1;

            updateDashboard(currentIndex, ratio); // 補間係数を渡す
            animationFrameId = requestAnimationFrame(playLoop);
            // ▲▲▲ 修正ここまで ▲▲▲
        }

        function startPlayback() {
            if (isPlaying || !currentLapData) return;
            isPlaying = true;
            const scrubber = container.querySelector('#timelineScrubber');
            const currentIndex = parseInt(scrubber.value, 10);
            
            lastPlaybackIndex = currentIndex;
            
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
            const scrubber = container.querySelector('#timelineScrubber');
            const currentIndex = parseInt(scrubber.value, 10);
            
            lastPlaybackIndex = currentIndex;
            
            if (currentLapData) { playbackStartOffset = currentLapData.track[currentIndex]?.runtime || 0; }
            
            // 停止時は即座に画面更新（間引きを無視して最終位置を表示）
            updateDashboard(currentIndex);
        }

        // --- メイン処理 ---
        const telemetrySessionName = container.querySelector('#telemetrySessionName');
        if (telemetrySessionName) telemetrySessionName.textContent = sessionName;
        
        const mapContainerEl = container.querySelector('#map');
        
        const lapSelectorContainer = container.querySelector('#lapSelectorContainer');
        
        if (lapSelectorContainer) lapSelectorContainer.innerHTML = `<p class="text-muted">走行データを読み込んでいます...</p>`;
        
        if (!map) { map = initializeMap('map'); }
        
        try {
            const response = await fetch(dataUrl);
            if (!response.ok) throw new Error('Failed to load GPS data.');
            const data = await response.json();
            
            if (!data.laps || data.laps.length === 0 || !data.lap_times || data.lap_times.length === 0) {
                if(mapContainerEl) mapContainerEl.innerHTML = '';
                if(lapSelectorContainer) lapSelectorContainer.innerHTML = `<div class="alert alert-warning">データがありません。</div>`;
                return;
            }

            const vehicleSpecs = data.vehicle_specs;
            const canEstimateGear = vehicleSpecs && vehicleSpecs.primary_ratio && vehicleSpecs.gear_ratios && vehicleSpecs.front_sprocket && vehicleSpecs.rear_sprocket && vehicleSpecs.rear_tyre_size;

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

            if (lapSelectorContainer) {
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
            }

            const loadLapData = (lapIndex) => {
                stopPlayback();
                
                // 変数リセット
                lastPlaybackIndex = 0;
                lastChartUpdateTime = 0;
                lastChartUpdateIndex = -1;

                currentLapData = data.laps[lapIndex];
                if (!currentLapData || !currentLapData.track || currentLapData.track.length < 2) return;
                
                const mapTrackData = currentLapData.map_track || currentLapData.track;

                lapStartTime = currentLapData.track[0]?.runtime || 0;
                polylines.flat().forEach(p => p.setMap(null));
                brakingMarkers.flat().forEach(m => m.setMap(null));
                accelMarkers.flat().forEach(m => m.setMap(null));
                if (bikeMarker) bikeMarker.setMap(null);
                polylines = []; brakingMarkers = []; accelMarkers = [];

                const speeds = mapTrackData.map(p => p.speed).filter(s => s > 0);
                const minSpeed = speeds.length > 0 ? Math.min(...speeds) : 0;
                const maxSpeed = mapTrackData.map(p => p.speed).reduce((max, s) => Math.max(max, s || 0), 0);
                
                bounds = new google.maps.LatLngBounds();
                mapTrackData.forEach(p => bounds.extend(p));
                if (map && !bounds.isEmpty()) { map.fitBounds(bounds); }
                
                polylines = drawLapPolyline(mapTrackData, minSpeed, maxSpeed, map);
                
                const { brakingPoints, accelPoints } = findSignificantPoints(currentLapData.track);
                const brakingIcon = { path: 'M0,-5 L5,5 L-5,5 Z', fillColor: 'red', fillOpacity: 1.0, strokeWeight: 0, rotation: 180, scale: 0.8, anchor: new google.maps.Point(0, 0) };
                const accelIcon = { path: 'M0,-5 L5,5 L-5,5 Z', fillColor: 'limegreen', fillOpacity: 1.0, strokeWeight: 0, scale: 0.8, anchor: new google.maps.Point(0, 0) };
                brakingMarkers = brakingPoints.map(p => createMarker(p, brakingIcon, map));
                accelMarkers = accelPoints.map(p => createMarker(p, accelIcon, map));
                
                const bikeIcon = { path: google.maps.SymbolPath.CIRCLE, scale: 5, fillColor: 'yellow', strokeColor: 'black', strokeWeight: 1 };
                bikeMarker = new google.maps.Marker({ position: currentLapData.track[0], icon: bikeIcon, map: map, zIndex: 100 });
                
                const labels = currentLapData.track.map(p => ((p.runtime || 0) - lapStartTime).toFixed(2));
                
                const gearDisplayContainer = container.querySelector('#gear-display-container');
                const gearChartCanvas = document.getElementById('gearChart');

                if (canEstimateGear) {
                    const gearKeys = Object.keys(vehicleSpecs.gear_ratios);
                    const maxGear = gearKeys.length > 0
                        ? Math.max(...gearKeys.map(Number))
                        : 6; 
                    
                    charts.gear = setupChart('gearChart', '使用ギア', 'rgba(255, 159, 64, 1)', 'step', {
                         ticks: { stepSize: 1, callback: function(value) { if (Number.isInteger(value)) { return value; } } },
                         suggestedMin: 1,
                         suggestedMax: maxGear
                    });
                    
                    const estimatedGears = currentLapData.track.map(p => estimateGear(p, vehicleSpecs));
                    smoothedGears = applySmoothingFilter(estimatedGears, 5);

                    if (charts.gear) {
                        charts.gear.data.labels = labels;
                        charts.gear.data.datasets[0].data = smoothedGears;
                    }
                    if (gearDisplayContainer) gearDisplayContainer.classList.remove('d-none');
                    if (gearChartCanvas) gearChartCanvas.parentElement.style.display = 'block';
                } else {
                    smoothedGears = [];
                    if (charts.gear) charts.gear.destroy();
                    if (gearDisplayContainer) gearDisplayContainer.classList.add('d-none');
                    if (gearChartCanvas) gearChartCanvas.parentElement.style.display = 'none';
                }
                
                charts.speed = setupChart('speedChart', '速度 (km/h)', 'rgba(54, 162, 235, 1)');
                charts.rpm = setupChart('rpmChart', 'エンジン回転数 (rpm)', 'rgba(255, 99, 132, 1)');
                charts.throttle = setupChart('throttleChart', 'スロットル開度 (%)', 'rgba(75, 192, 192, 1)');
                
                if(charts.speed) {
                    charts.speed.data.labels = labels;
                    charts.speed.data.datasets[0].data = currentLapData.track.map(p => p.speed);
                }
                if(charts.rpm) {
                    charts.rpm.data.labels = labels;
                    charts.rpm.data.datasets[0].data = currentLapData.track.map(p => p.rpm);
                }
                if(charts.throttle) {
                    charts.throttle.data.labels = labels;
                    charts.throttle.data.datasets[0].data = currentLapData.track.map(p => p.throttle);
                }
                Object.values(charts).forEach(chart => { if (chart) chart.update(); });

                const scrubber = container.querySelector('#timelineScrubber');
                if (scrubber) scrubber.max = currentLapData.track.length - 1;
                updateDashboard(0);
                playbackStartOffset = 0;
            };

            const lapSelect = container.querySelector('#lapSelectorContainer select');
            if (lapSelect) {
                lapSelect.addEventListener('change', (e) => loadLapData(parseInt(e.target.value, 10)));
            }

            const scrubber = container.querySelector('#timelineScrubber');
            if (scrubber) {
                scrubber.addEventListener('input', (e) => {
                    stopPlayback(); 
                    const newIndex = parseInt(e.target.value, 10);
                    lastPlaybackIndex = newIndex;
                    updateDashboard(newIndex);
                    playbackStartOffset = currentLapData.track[newIndex]?.runtime || 0;
                });
            }

            const playPauseBtn = container.querySelector('#playPauseBtn');
            if (playPauseBtn) {
                playPauseBtn.addEventListener('click', () => {
                    if (isPlaying) stopPlayback(); else startPlayback();
                });
            }
            
            const toggleBrakingPoints = container.querySelector('#toggleBrakingPoints');
            if (toggleBrakingPoints) {
                toggleBrakingPoints.addEventListener('change', (e) => {
                    brakingMarkers.forEach(m => m.setVisible(e.target.checked));
                });
            }
            const toggleAccelPoints = container.querySelector('#toggleAccelPoints');
            if (toggleAccelPoints) {
                toggleAccelPoints.addEventListener('change', (e) => {
                    accelMarkers.forEach(m => m.setVisible(e.target.checked));
                });
            }

            if (!isPublicPage) {
                const toggleTelemetryBtn = container.querySelector('#toggleTelemetryBtn');
                if (toggleTelemetryBtn) {
                    toggleTelemetryBtn.addEventListener('click', (e) => {
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
            }

            loadLapData(0);

        } catch (error) {
            console.error('Error:', error);
            if(mapContainerEl) mapContainerEl.innerHTML = '';
            if(lapSelectorContainer) lapSelectorContainer.innerHTML = `<div class="alert alert-danger">データの読み込みに失敗しました。</div>`;
        }
    }
};

document.addEventListener('DOMContentLoaded', () => {
    const mapModalElement = document.getElementById('mapModal');
    if (!mapModalElement) return;

    mapModalElement.addEventListener('shown.bs.modal', (event) => {
        const button = event.relatedTarget;
        const sessionId = button.dataset.sessionId;
        
        window.motopuppuMapViewer.init({
            sessionId: sessionId,
            sessionName: button.dataset.sessionName,
            dataUrl: `/activity/session/${sessionId}/gps_data`,
            isPublicPage: false
        });
    });
});
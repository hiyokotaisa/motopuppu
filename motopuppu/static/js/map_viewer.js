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
        // ▼▼▼【ここから追記】平滑化後のギアデータを保持する変数を追加 ▼▼▼
        let smoothedGears = [];
        // ▲▲▲【追記はここまで】▲▲▲
        let animationFrameId = null;
        let isPlaying = false;
        let playbackStartTime = 0; 
        let playbackStartOffset = 0;
        let lapStartTime = 0; 

        // --- 関数定義 (内部ヘルパー) ---
        function initializeMap(containerId) {
            const mapContainer = document.getElementById(containerId);
            if (!mapContainer || typeof google === 'undefined') return null;
            mapContainer.innerHTML = '';
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
                console.error(`Chart canvas element with ID "${canvasId}" not found.`);
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


        function updateDashboard(index) {
            if (!currentLapData || index < 0 || index >= currentLapData.track.length) return;
            const point = currentLapData.track[index];
            if (bikeMarker) { bikeMarker.setPosition({ lat: point.lat, lng: point.lng }); }
            
            const gearDisplay = container.querySelector('#currentGearDisplay');
            if (gearDisplay) {
                const currentGear = smoothedGears[index];
                gearDisplay.textContent = currentGear !== null ? currentGear : 'N';
            }

            Object.values(charts).forEach(chart => {
                if (chart) {
                    chart.options.plugins.annotation.annotations.line1.value = index;
                    chart.options.plugins.annotation.annotations.line1.display = true;
                    chart.update('none');
                }
            });
            const scrubber = container.querySelector('#timelineScrubber');
            if (scrubber) { scrubber.value = index; }
            const timeDisplay = container.querySelector('#playbackTime');
            if (timeDisplay) {
                const intraLapTime = (point.runtime || 0) - lapStartTime;
                timeDisplay.textContent = formatRuntime(intraLapTime);
            }
        }
        function playLoop() {
            if (!isPlaying) return;
            const elapsedTime = (Date.now() - playbackStartTime) / 1000 + playbackStartOffset;
            const totalDuration = currentLapData.track[currentLapData.track.length - 1].runtime || 0;
            if (elapsedTime >= totalDuration) {
                updateDashboard(currentLapData.track.length - 1);
                stopPlayback();
                return;
            }
            let currentIndex = 0;
            for (let i = 0; i < currentLapData.track.length; i++) {
                if (currentLapData.track[i].runtime >= elapsedTime) { currentIndex = i; break; }
            }
            updateDashboard(currentIndex);
            animationFrameId = requestAnimationFrame(playLoop);
        }
        function startPlayback() {
            if (isPlaying || !currentLapData) return;
            isPlaying = true;
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
            const scrubber = container.querySelector('#timelineScrubber');
            const currentIndex = parseInt(scrubber.value, 10);
            if (currentLapData) { playbackStartOffset = currentLapData.track[currentIndex]?.runtime || 0; }
        }

        // --- メイン処理 ---
        const telemetrySessionName = container.querySelector('#telemetrySessionName');
        if (telemetrySessionName) telemetrySessionName.textContent = sessionName;
        const mapContainerEl = container.querySelector('#mapContainer');
        const lapSelectorContainer = container.querySelector('#lapSelectorContainer');
        mapContainerEl.innerHTML = `<div class="d-flex justify-content-center align-items-center h-100"><div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div></div>`;
        if (lapSelectorContainer) lapSelectorContainer.innerHTML = `<p class="text-muted">走行データを読み込んでいます...</p>`;
        if (!map) { map = initializeMap('mapContainer'); }
        
        try {
            const response = await fetch(dataUrl);
            if (!response.ok) throw new Error('Failed to load GPS data.');
            const data = await response.json();
            
            if (!data.laps || data.laps.length === 0 || !data.lap_times || data.lap_times.length === 0) {
                mapContainerEl.innerHTML = '';
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
                currentLapData = data.laps[lapIndex];
                if (!currentLapData || !currentLapData.track || currentLapData.track.length < 2) return;
                
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
                
                const labels = currentLapData.track.map(p => ((p.runtime || 0) - lapStartTime).toFixed(2));
                
                // ▼▼▼【ここからが今回の修正箇所です】▼▼▼
                const gearDisplayContainer = container.querySelector('#gear-display-container');
                const gearChartCanvas = document.getElementById('gearChart');

                if (canEstimateGear) {
                    charts.gear = setupChart('gearChart', '使用ギア', 'rgba(255, 159, 64, 1)', 'step', {
                         ticks: { stepSize: 1, callback: function(value) { if (Number.isInteger(value)) { return value; } } },
                         suggestedMin: 1,
                         suggestedMax: 6
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
                // ▲▲▲【修正はここまで】▲▲▲
                
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
            
            // ▼▼▼【ここからが今回の修正箇所です】▼▼▼
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
            // ▲▲▲【修正はここまで】▲▲▲

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
            mapContainerEl.innerHTML = '';
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
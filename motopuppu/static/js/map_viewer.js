// motopuppu/static/js/map_viewer.js
window.motopuppuMapViewer = {
    instances: new WeakMap(),
    destroy: function(container) {
        const instance = container && this.instances.get(container);
        if (instance) {
            this.instances.delete(container);
            instance.destroy();
        }
    },
    init: async function(options) {
        // オプションから設定を取得
        const sessionId = options.sessionId;
        const sessionName = options.sessionName;
        const dataUrl = options.dataUrl;
        const isPublicPage = options.isPublicPage || false;

        // 実行コンテナ
        const container = isPublicPage ? document.body : document.getElementById('mapModal');
        if (!container) return;
        this.destroy(container);
        const requestController = new AbortController();
        let lapController = null;
        let disposed = false;
        let lapRequestId = 0;
        let resizeTimer = null;
        const listeners = [];
        const lapCache = new Map();
        
        // --- グローバル変数 ---
        let map;
        let polylines = [];
        let brakingMarkers = [];
        let accelMarkers = [];
        let bikeMarker = null;
        let bounds;
        const charts = { speedChart: null, rpmChart: null, throttleChart: null, gearChart: null };
        let currentLapData = null;
        let smoothedGears = [];
        let animationFrameId = null;
        let isPlaying = false;
        let playbackStartTime = 0; 
        let playbackStartOffset = 0;
        let lapStartTime = 0;
        
        let lastPlaybackIndex = 0;
        let lastChartUpdateTime = 0;
        const CHART_UPDATE_INTERVAL = 100;

        function listen(target, event, handler) {
            if (!target) return;
            target.addEventListener(event, handler);
            listeners.push(() => target.removeEventListener(event, handler));
        }
        function destroyChart(id) {
            if (charts[id]) charts[id].destroy();
            charts[id] = null;
        }
        function clearTrack() {
            polylines.flat().forEach(line => line.setMap(null));
            brakingMarkers.flat().forEach(marker => marker.setMap(null));
            accelMarkers.flat().forEach(marker => marker.setMap(null));
            if (bikeMarker) bikeMarker.setMap(null);
            polylines = []; brakingMarkers = []; accelMarkers = [];
            bikeMarker = null;
        }
        function setPlaybackEnabled(enabled) {
            for (const id of ['playPauseBtn', 'timelineScrubber']) {
                const element = container.querySelector('#' + id);
                if (element) element.disabled = !enabled;
            }
        }
        function resetTelemetry() {
            const playButton = container.querySelector('#playPauseBtn');
            if (playButton) playButton.innerHTML = '<i class="fas fa-play"></i>';
            const scrubber = container.querySelector('#timelineScrubber');
            if (scrubber) scrubber.value = 0;
            const hud = container.querySelector('#hud-overlay');
            if (hud) hud.classList.add('d-none');
            if (!isPublicPage) {
                const dialog = container.querySelector('.modal-dialog');
                dialog?.classList.remove('modal-fullscreen');
                dialog?.classList.add('modal-xl');
                container.querySelector('#playback-controls')?.classList.add('d-none');
                container.querySelector('#telemetry-graphs')?.classList.add('d-none');
                const toggle = container.querySelector('#toggleTelemetryBtn');
                if (toggle) {
                    toggle.innerHTML = '<i class="fas fa-chart-line me-1"></i> テレメトリを表示';
                    toggle.classList.remove('btn-success');
                    toggle.classList.add('btn-outline-primary');
                }
            }
        }
        this.instances.set(container, { destroy: () => {
            disposed = true;
            isPlaying = false;
            cancelAnimationFrame(animationFrameId);
            clearTimeout(resizeTimer);
            requestController.abort();
            lapController?.abort();
            listeners.forEach(remove => remove());
            Object.keys(charts).forEach(destroyChart);
            clearTrack();
            lapCache.clear();
            currentLapData = null;
            if (map) google.maps.event.clearInstanceListeners(map);
            map = null;
            container.querySelector('#map')?.replaceChildren();
            resetTelemetry();
            setPlaybackEnabled(false);
        }});
        resetTelemetry();
        setPlaybackEnabled(false);


        // --- ヘルパー関数 ---
        function initializeMap(containerId) {
            const mapContainer = document.getElementById(containerId);
            if (!mapContainer || typeof google === 'undefined') return null;
            return new google.maps.Map(mapContainer, {
                mapTypeId: 'satellite', streetViewControl: false, mapTypeControl: false, fullscreenControl: false,
            });
        }
        function setupChart(canvasId, label, color, chartType = 'line', yAxisOptions = {}) {
            destroyChart(canvasId);
            const canvasEl = document.getElementById(canvasId);
            if (!canvasEl) return null;
            const ctx = canvasEl.getContext('2d');
            const defaultYAxisOptions = {
                beginAtZero: true,
                ticks: { font: { size: 10 } },
                title: { display: true, text: label, font: { size: 12 } }
            };
            const chart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: label, data: [], borderColor: color, backgroundColor: color,
                        borderWidth: 2, pointRadius: 0, tension: chartType === 'line' ? 0.1 : 0, stepped: chartType === 'step'
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false, animation: false,
                    plugins: { legend: { display: false }, tooltip: { enabled: false }, annotation: { annotations: { line1: { type: 'line', scaleID: 'x', value: 0, borderColor: 'rgba(255, 99, 132, 0.8)', borderWidth: 1, display: false } } } },
                    scales: { x: { ticks: { display: false }, grid: { display: false } }, y: { ...defaultYAxisOptions, ...yAxisOptions } }
                }
            });
            charts[canvasId] = chart;
            return chart;
        }
        function getColorForSpeed(speed, minSpeed, maxSpeed) {
            if (speed < minSpeed) speed = minSpeed;
            if (speed > maxSpeed) speed = maxSpeed;
            const range = maxSpeed - minSpeed;
            if (range === 0) return '#00FF00';
            const ratio = (speed - minSpeed) / range;
            let r, g, b;
            if (ratio < 0.5) { r = 255; g = Math.round(255 * (ratio * 2)); b = 0; }
            else { r = Math.round(255 * (1 - (ratio - 0.5) * 2)); g = 255; b = 0; }
            return `rgb(${r},${g},${b})`;
        }
        function drawLapPolyline(track, minSpeed, maxSpeed, mapInstance) {
            const lapPolylines = [];
            if (!track || track.length < 2) return lapPolylines;
            let currentPath = [track[0]];
            const getSpeedBucketColor = (speed) => {
                const range = maxSpeed - minSpeed || 1;
                const step = range / 20;
                const bucketSpeed = Math.floor((speed - minSpeed) / step) * step + minSpeed;
                return getColorForSpeed(bucketSpeed, minSpeed, maxSpeed);
            };
            let currentColor = getSpeedBucketColor(track[0].speed || 0);
            for (let i = 1; i < track.length; i++) {
                const point = track[i];
                const nextColor = getSpeedBucketColor(point.speed || 0);
                if (nextColor !== currentColor) {
                    currentPath.push(point);
                    const segment = new google.maps.Polyline({
                        path: currentPath, geodesic: true, strokeColor: currentColor, strokeOpacity: 1.0, strokeWeight: 4, zIndex: 1
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
                    path: currentPath, geodesic: true, strokeColor: currentColor, strokeOpacity: 1.0, strokeWeight: 4, zIndex: 1
                });
                if (mapInstance) segment.setMap(mapInstance);
                lapPolylines.push(segment);
            }
            return lapPolylines;
        }
        function findSignificantPoints(track, options = {}) {
            const { lookahead = 25, speedChangeThreshold = 4.0, cooldown = 30 } = options;
            const brakingPoints = []; const accelPoints = [];
            if (track.length < lookahead + 1) return { brakingPoints, accelPoints };
            let lastBrakeIndex = -cooldown; let lastAccelIndex = -cooldown;
            for (let i = 0; i < track.length - lookahead; i++) {
                const currentPoint = track[i];
                const futurePoint = track[i + lookahead];
                if (currentPoint.speed === undefined || futurePoint.speed === undefined) continue;
                const speedDiff = currentPoint.speed - futurePoint.speed;
                if (speedDiff > speedChangeThreshold && i > lastBrakeIndex + cooldown) {
                    brakingPoints.push(currentPoint); lastBrakeIndex = i;
                } else if (-speedDiff > speedChangeThreshold && i > lastAccelIndex + cooldown) {
                    accelPoints.push(currentPoint); lastAccelIndex = i;
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
            if (match && match.length === 4) return [parseInt(match[1], 10), parseInt(match[2], 10), parseInt(match[3], 10)];
            return null;
        }
        function calculateTireCircumference(width, aspectRatio, rimDiameter) {
            const rimDiameterMm = rimDiameter * 25.4;
            const sidewallHeightMm = width * (aspectRatio / 100);
            const totalDiameterMm = rimDiameterMm + (2 * sidewallHeightMm);
            return (totalDiameterMm * Math.PI) / 1000;
        }
        function estimateGear(point, specs) {
            if (!specs || !specs.primary_ratio || !specs.gear_ratios || !specs.front_sprocket || !specs.rear_sprocket || !specs.rear_tyre_size || !point.rpm || !point.speed) return null;
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
                if (diff < min_diff) { min_diff = diff; best_gear = parseInt(gear, 10); }
            }
            if (min_diff > (point.speed * 0.2 + 5)) return null;
            return best_gear;
        }
        function applySmoothingFilter(data, windowSize) {
            const smoothed = [];
            const halfWindow = Math.floor(windowSize / 2);
            for (let i = 0; i < data.length; i++) {
                const start = Math.max(0, i - halfWindow);
                const end = Math.min(data.length, i + halfWindow + 1);
                const window = data.slice(start, end).filter(val => val !== null);
                if (window.length === 0) { smoothed.push(data[i]); continue; }
                const counts = window.reduce((acc, val) => { acc[val] = (acc[val] || 0) + 1; return acc; }, {});
                const mode = Object.keys(counts).reduce((a, b) => counts[a] > counts[b] ? a : b);
                smoothed.push(parseInt(mode, 10));
            }
            return smoothed;
        }

        function updateDashboard(index, ratio = 0) {
            if (disposed || !currentLapData || index < 0 || index >= currentLapData.track.length) return;
            
            const p1 = currentLapData.track[index];
            const p2 = currentLapData.track[index + 1] || p1; 

            const lat = p1.lat + (p2.lat - p1.lat) * ratio;
            const lng = p1.lng + (p2.lng - p1.lng) * ratio;

            if (bikeMarker) { 
                bikeMarker.setPosition({ lat: lat, lng: lng }); 
            }
            
            const speed = (p1.speed || 0) + ((p2.speed || 0) - (p1.speed || 0)) * ratio;
            const rpm = (p1.rpm || 0) + ((p2.rpm || 0) - (p1.rpm || 0)) * ratio;

            const hudOverlay = container.querySelector('#hud-overlay');
            if (hudOverlay) {
                // HUD自体の表示/非表示はloadLapDataで制御されるが、d-noneが残っていたら外す
                hudOverlay.classList.remove('d-none');
                
                const currentGear = smoothedGears[index];
                const hudGearEl = container.querySelector('#hud-gear');
                if (hudGearEl) hudGearEl.textContent = currentGear ?? '-';
                
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
                    if (percentage > 85) hudRpmBar.className = 'progress-bar bg-danger';
                    else hudRpmBar.className = 'progress-bar bg-warning';
                }
            }
            
            const gearDisplay = container.querySelector('#currentGearDisplay');
            if (gearDisplay) {
                const currentGear = smoothedGears[index];
                gearDisplay.textContent = currentGear ?? '-';
            }

            const now = Date.now();
            if (now - lastChartUpdateTime > CHART_UPDATE_INTERVAL || !isPlaying) {
                Object.values(charts).forEach(chart => {
                    if (chart) {
                        chart.options.plugins.annotation.annotations.line1.value = index + ratio;
                        chart.options.plugins.annotation.annotations.line1.display = true;
                        chart.update('none');
                    }
                });
                const scrubber = container.querySelector('#timelineScrubber');
                if (scrubber) scrubber.value = index; 
                const timeDisplay = container.querySelector('#playbackTime');
                if (timeDisplay) {
                    const currentRuntime = (p1.runtime || 0) + ((p2.runtime || 0) - (p1.runtime || 0)) * ratio;
                    const intraLapTime = currentRuntime - lapStartTime;
                    timeDisplay.textContent = formatRuntime(intraLapTime);
                }
                lastChartUpdateTime = now;
            }
        }

        function playLoop() {
            if (disposed || !isPlaying) return;
            const elapsedTime = (Date.now() - playbackStartTime) / 1000 + playbackStartOffset;
            const totalDuration = currentLapData.track[currentLapData.track.length - 1].runtime || 0;
            
            if (elapsedTime >= totalDuration) {
                updateDashboard(currentLapData.track.length - 1);
                stopPlayback();
                return;
            }

            let currentIndex = lastPlaybackIndex;
            if (currentIndex >= currentLapData.track.length - 1 || (currentLapData.track[currentIndex] && currentLapData.track[currentIndex].runtime > elapsedTime)) {
                currentIndex = 0;
            }

            for (let i = currentIndex; i < currentLapData.track.length - 1; i++) {
                const pNow = currentLapData.track[i];
                const pNext = currentLapData.track[i + 1];
                if (pNow.runtime <= elapsedTime && elapsedTime < pNext.runtime) {
                    currentIndex = i;
                    break;
                }
            }
            
            lastPlaybackIndex = currentIndex;

            const p1 = currentLapData.track[currentIndex];
            const p2 = currentLapData.track[currentIndex + 1];
            let ratio = 0;
            if (p1 && p2 && (p2.runtime - p1.runtime) > 0) {
                ratio = (elapsedTime - p1.runtime) / (p2.runtime - p1.runtime);
            }
            if (ratio < 0) ratio = 0;
            if (ratio > 1) ratio = 1;

            updateDashboard(currentIndex, ratio);
            animationFrameId = requestAnimationFrame(playLoop);
        }

        function startPlayback() {
            if (disposed || isPlaying || !currentLapData) return;
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
            updateDashboard(currentIndex);
        }

        const telemetrySessionName = container.querySelector('#telemetrySessionName');
        if (telemetrySessionName) telemetrySessionName.textContent = sessionName;
        const mapContainerEl = container.querySelector('#map');
        const lapSelectorContainer = container.querySelector('#lapSelectorContainer');
        if (lapSelectorContainer) lapSelectorContainer.innerHTML = `<p class="text-muted">走行データを読み込んでいます...</p>`;
        if (!map) { map = initializeMap('map'); }
        
        try {
            const summaryUrl = new URL(dataUrl, window.location.href);
            summaryUrl.searchParams.set('summary', '1');
            const response = await fetch(summaryUrl, { signal: requestController.signal, cache: 'no-store' });
            if (!response.ok) throw new Error('Failed to load GPS data.');
            const data = await response.json();
            if (disposed) return;
            
            if (!data.laps || data.laps.length === 0 || !data.lap_times || data.lap_times.length === 0) {
                if(mapContainerEl) mapContainerEl.innerHTML = '';
                if(lapSelectorContainer) lapSelectorContainer.innerHTML = `<div class="alert alert-warning">データがありません。</div>`;
                return;
            }

            const vehicleSpecs = data.vehicle_specs;
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

            const availableLaps = new Set(data.laps.map(lap => Number(lap.lap_number)));
            const lapStatus = document.createElement('p');
            lapStatus.className = 'small text-muted mt-2';
            lapStatus.setAttribute('role', 'status');
            if (lapSelectorContainer) {
                lapSelectorContainer.innerHTML = '';
                const lapSelect = document.createElement('select');
                lapSelect.className = 'form-select';
                data.lap_times.forEach((lapTime, index) => {
                    const option = document.createElement('option');
                    const lapNumber = index + 1;
                    option.value = lapNumber;
                    option.disabled = !availableLaps.has(lapNumber);
                    const isBest = index === bestLapIndex;
                    option.textContent = `${isBest ? '👑 ' : ''}Lap ${lapNumber} (${lapTime})${option.disabled ? ' — GPSなし' : ''}`;
                    lapSelect.appendChild(option);
                });
                lapSelectorContainer.append(lapSelect, lapStatus);
            }

            const renderLapData = (lap) => {
                lastPlaybackIndex = 0;
                lastChartUpdateTime = 0;
                currentLapData = lap;
                if (!currentLapData || !currentLapData.track || currentLapData.track.length < 2) return;
                
                const mapTrackData = currentLapData.map_track || currentLapData.track;

                const maxRpm = mapTrackData.reduce((max, p) => Math.max(max, p.rpm || 0), 0);
                const hasRpm = maxRpm > 0;
                const maxThrottle = mapTrackData.reduce((max, p) => Math.max(max, p.throttle || 0), 0);
                const hasThrottle = maxThrottle > 0;

                const canEstimateGear = hasRpm && vehicleSpecs && vehicleSpecs.primary_ratio && vehicleSpecs.gear_ratios && vehicleSpecs.front_sprocket && vehicleSpecs.rear_sprocket && vehicleSpecs.rear_tyre_size;

                const hudOverlay = container.querySelector('#hud-overlay');
                const hudGearContainer = container.querySelector('.hud-gear-container');
                const hudRpmContainer = container.querySelector('.hud-rpm-container');
                const hudRpmBar = container.querySelector('#hud-rpm-bar');
                const hudDivider = container.querySelector('.hud-divider');

                // HUD自体の表示を確実に有効化
                if(hudOverlay) hudOverlay.classList.remove('d-none');

                if (hasRpm) {
                    if(hudGearContainer) hudGearContainer.classList.remove('d-none');
                    if(hudRpmContainer) hudRpmContainer.classList.remove('d-none');
                    if(hudRpmBar) hudRpmBar.classList.remove('d-none');
                    if(hudDivider) hudDivider.classList.remove('d-none');
                    if(hudOverlay) hudOverlay.style.minWidth = ""; 
                } else {
                    if(hudGearContainer) hudGearContainer.classList.add('d-none');
                    if(hudRpmContainer) hudRpmContainer.classList.add('d-none');
                    if(hudRpmBar) hudRpmBar.classList.add('d-none');
                    if(hudDivider) hudDivider.classList.add('d-none');
                    if(hudOverlay) hudOverlay.style.minWidth = "120px"; 
                }

                lapStartTime = currentLapData.track[0]?.runtime || 0;
                clearTrack();

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
                    const maxGear = gearKeys.length > 0 ? Math.max(...gearKeys.map(Number)) : 6; 
                    
                    charts.gearChart = setupChart('gearChart', '使用ギア', 'rgba(255, 159, 64, 1)', 'step', {
                         ticks: { stepSize: 1, callback: function(value) { if (Number.isInteger(value)) { return value; } } },
                         suggestedMin: 1, suggestedMax: maxGear
                    });
                    const estimatedGears = currentLapData.track.map(p => estimateGear(p, vehicleSpecs));
                    smoothedGears = applySmoothingFilter(estimatedGears, 5);
                    if (charts.gearChart) {
                        charts.gearChart.data.labels = labels;
                        charts.gearChart.data.datasets[0].data = smoothedGears;
                    }
                    if (gearDisplayContainer) gearDisplayContainer.classList.remove('d-none');
                    if (gearChartCanvas) gearChartCanvas.parentElement.style.display = 'block';
                } else {
                    smoothedGears = [];
                    destroyChart('gearChart');
                    if (gearDisplayContainer) gearDisplayContainer.classList.add('d-none');
                    if (gearChartCanvas) gearChartCanvas.parentElement.style.display = 'none';
                }
                
                charts.speedChart = setupChart('speedChart', '速度 (km/h)', 'rgba(54, 162, 235, 1)');
                
                const rpmChartCanvas = document.getElementById('rpmChart');
                if (hasRpm) {
                    charts.rpmChart = setupChart('rpmChart', 'エンジン回転数 (rpm)', 'rgba(255, 99, 132, 1)');
                    if (rpmChartCanvas) rpmChartCanvas.parentElement.style.display = 'block';
                } else {
                    destroyChart('rpmChart');
                    if (rpmChartCanvas) rpmChartCanvas.parentElement.style.display = 'none';
                }

                const throttleChartCanvas = document.getElementById('throttleChart');
                if (hasThrottle) {
                    charts.throttleChart = setupChart('throttleChart', 'スロットル開度 (%)', 'rgba(75, 192, 192, 1)');
                    if (throttleChartCanvas) throttleChartCanvas.parentElement.style.display = 'block';
                } else {
                    destroyChart('throttleChart');
                    if (throttleChartCanvas) throttleChartCanvas.parentElement.style.display = 'none';
                }
                
                if(charts.speedChart) {
                    charts.speedChart.data.labels = labels;
                    charts.speedChart.data.datasets[0].data = currentLapData.track.map(p => p.speed);
                }
                if(charts.rpmChart && hasRpm) {
                    charts.rpmChart.data.labels = labels;
                    charts.rpmChart.data.datasets[0].data = currentLapData.track.map(p => p.rpm);
                }
                if(charts.throttleChart && hasThrottle) {
                    charts.throttleChart.data.labels = labels;
                    charts.throttleChart.data.datasets[0].data = currentLapData.track.map(p => p.throttle);
                }
                Object.values(charts).forEach(chart => { if (chart) chart.update(); });

                const scrubber = container.querySelector('#timelineScrubber');
                if (scrubber) scrubber.max = currentLapData.track.length - 1;
                if (scrubber) scrubber.value = 0;
                setPlaybackEnabled(true);
                brakingMarkers.forEach(marker => marker.setVisible(container.querySelector('#toggleBrakingPoints')?.checked ?? true));
                accelMarkers.forEach(marker => marker.setVisible(container.querySelector('#toggleAccelPoints')?.checked ?? true));
                updateDashboard(0);
                playbackStartOffset = 0;
            };

            const loadLapData = async (lapNumber) => {
                const requestId = ++lapRequestId;
                lapController?.abort();
                lapController = new AbortController();
                stopPlayback();
                Object.keys(charts).forEach(destroyChart);
                clearTrack();
                currentLapData = null;
                setPlaybackEnabled(false);
                container.querySelector('#hud-overlay')?.classList.add('d-none');
                lapStatus.textContent = `Lap ${lapNumber}のGPSを読み込んでいます...`;
                try {
                    let lap = lapCache.get(lapNumber);
                    if (!lap) {
                        const lapUrl = new URL(dataUrl, window.location.href);
                        lapUrl.searchParams.delete('summary');
                        lapUrl.searchParams.set('lap_number', lapNumber);
                        const response = await fetch(lapUrl, { signal: lapController.signal, cache: 'no-store' });
                        if (!response.ok) throw new Error('Failed to load lap GPS data.');
                        const payload = await response.json();
                        if (disposed || requestId !== lapRequestId) return;
                        lap = payload.laps?.find(item => Number(item.lap_number) === lapNumber);
                        if (!lap?.track || lap.track.length < 2) throw new Error('No usable GPS data.');
                        lapCache.set(lapNumber, lap);
                        if (lapCache.size > 3) lapCache.delete(lapCache.keys().next().value);
                    }
                    if (disposed || requestId !== lapRequestId) return;
                    renderLapData(lap);
                    lapStatus.textContent = '';
                } catch (error) {
                    if (disposed || requestId !== lapRequestId || error.name === 'AbortError') return;
                    Object.keys(charts).forEach(destroyChart);
                    clearTrack();
                    currentLapData = null;
                    setPlaybackEnabled(false);
                    container.querySelector('#hud-overlay')?.classList.add('d-none');
                    lapStatus.textContent = 'このラップのGPSを読み込めませんでした。別のラップを選択してください。';
                    console.error(error);
                }
            };

            const lapSelect = container.querySelector('#lapSelectorContainer select');
            if (lapSelect) {
                listen(lapSelect, 'change', (e) => loadLapData(parseInt(e.target.value, 10)));
            }

            const scrubber = container.querySelector('#timelineScrubber');
            if (scrubber) {
                listen(scrubber, 'input', (e) => {
                    stopPlayback(); 
                    const newIndex = parseInt(e.target.value, 10);
                    lastPlaybackIndex = newIndex;
                    updateDashboard(newIndex);
                    playbackStartOffset = currentLapData.track[newIndex]?.runtime || 0;
                });
            }

            const playPauseBtn = container.querySelector('#playPauseBtn');
            if (playPauseBtn) {
                listen(playPauseBtn, 'click', () => {
                    if (isPlaying) stopPlayback(); else startPlayback();
                });
            }
            
            const toggleBrakingPoints = container.querySelector('#toggleBrakingPoints');
            if (toggleBrakingPoints) {
                listen(toggleBrakingPoints, 'change', (e) => {
                    brakingMarkers.forEach(m => m.setVisible(e.target.checked));
                });
            }
            const toggleAccelPoints = container.querySelector('#toggleAccelPoints');
            if (toggleAccelPoints) {
                listen(toggleAccelPoints, 'change', (e) => {
                    accelMarkers.forEach(m => m.setVisible(e.target.checked));
                });
            }

            if (!isPublicPage) {
                const toggleTelemetryBtn = container.querySelector('#toggleTelemetryBtn');
                if (toggleTelemetryBtn) {
                    listen(toggleTelemetryBtn, 'click', (e) => {
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
                        clearTimeout(resizeTimer);
                        resizeTimer = setTimeout(() => { if(!disposed && map && bounds && !bounds.isEmpty()){ google.maps.event.trigger(map, 'resize'); map.fitBounds(bounds); } }, 200);
                    });
                }
            }

            const firstLap = data.lap_times.findIndex((_, index) => availableLaps.has(index + 1)) + 1;
            if (firstLap) {
                if (lapSelect) lapSelect.value = firstLap;
                await loadLapData(firstLap);
            } else {
                lapStatus.textContent = '対応するラップのGPSデータがありません。';
            }

        } catch (error) {
            if (disposed || error.name === 'AbortError') return;
            console.error('Error:', error);
            if(mapContainerEl) mapContainerEl.innerHTML = '';
            if(lapSelectorContainer) lapSelectorContainer.innerHTML = `<div class="alert alert-danger">データの読み込みに失敗しました。</div>`;
        }
    }
};

document.addEventListener('DOMContentLoaded', () => {
    const mapModalElement = document.getElementById('mapModal');
    if (!mapModalElement) return;

    mapModalElement.addEventListener('hidden.bs.modal', () => window.motopuppuMapViewer.destroy(mapModalElement));
    mapModalElement.addEventListener('shown.bs.modal', (event) => {
        const button = event.relatedTarget;
        if (!button) return;
        const sessionId = button.dataset.sessionId;
        
        window.motopuppuMapViewer.init({
            sessionId: sessionId,
            sessionName: button.dataset.sessionName,
            dataUrl: `/activity/session/${sessionId}/gps_data`,
            isPublicPage: false
        });
    });
});
window.addEventListener('pagehide', (event) => {
    // 戻る操作で復元されるページの地図は維持する。
    if (event.persisted) return;
    window.motopuppuMapViewer.destroy(document.getElementById('mapModal') || document.body);
});

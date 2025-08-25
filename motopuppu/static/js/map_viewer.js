// motopuppu/static/js/map_viewer.js
document.addEventListener('DOMContentLoaded', () => {
    const mapModalElement = document.getElementById('mapModal');
    if (!mapModalElement) return;

    let map;
    let polylines = [];
    let brakingMarkers = [];
    let accelMarkers = [];
    let bounds;
    
    function initializeMap(containerId, center, zoom) {
        const mapContainer = document.getElementById(containerId);
        if (!mapContainer || typeof google === 'undefined' || !google.maps) {
            console.error('Google Maps API not loaded.');
            return null;
        }
        mapContainer.innerHTML = '';
        return new google.maps.Map(mapContainer, {
            center: center,
            zoom: zoom,
            mapTypeId: 'satellite',
            streetViewControl: false,
            mapTypeControl: false,
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

    // ▼▼▼【ここからが最終修正コードです】▼▼▼

    // 加速・減速ポイントを見つける関数（未来予測アルゴリズム）
    function findSignificantPoints(track, options = {}) {
        const {
            // 比較対象とする未来のデータ点（Droggerは約50Hzなので25点で約0.5秒先）
            lookahead = 25,
            // この速度差以上を「意味のある変化」とみなす
            speedChangeThreshold = 4.0, // 4.0 km/h
            // マーカーの密集を防ぐためのクールダウン
            cooldown = 30, // 30点 (約0.6秒)
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

            // 減速ポイントの検出
            if (speedDiff > speedChangeThreshold && i > lastBrakeIndex + cooldown) {
                brakingPoints.push(currentPoint);
                lastBrakeIndex = i;
            }
            // 加速ポイントの検出
            else if (-speedDiff > speedChangeThreshold && i > lastAccelIndex + cooldown) {
                accelPoints.push(currentPoint);
                lastAccelIndex = i;
            }
        }
        return { brakingPoints, accelPoints };
    }
    
    // ▲▲▲【最終修正コードはここまで】▲▲▲
    
    // マーカーを作成する関数
    function createMarker(point, icon, mapInstance) {
        const marker = new google.maps.Marker({
            position: point,
            icon: icon,
            map: mapInstance,
            title: `Speed: ${point.speed.toFixed(1)} km/h`
        });
        return marker;
    }

    mapModalElement.addEventListener('show.bs.modal', async (event) => {
        const button = event.relatedTarget;
        const sessionId = button.dataset.sessionId;
        const sessionName = button.dataset.sessionName;

        const modalTitle = mapModalElement.querySelector('.modal-title');
        modalTitle.textContent = `走行ライン - ${sessionName}`;

        const mapContainer = document.getElementById('mapContainer');
        const lapSelectorContainer = document.getElementById('lapSelectorContainer');
        mapContainer.innerHTML = `<div class="d-flex justify-content-center align-items-center h-100"><div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div></div>`;
        lapSelectorContainer.innerHTML = `<p class="text-muted">走行データを読み込んでいます...</p>`;
        
        polylines.flat().forEach(p => { if (p) p.setMap(null); });
        polylines = [];
        brakingMarkers.flat().forEach(m => m.setMap(null));
        accelMarkers.flat().forEach(m => m.setMap(null));
        brakingMarkers = [];
        accelMarkers = [];
        
        try {
            const response = await fetch(`/activity/session/${sessionId}/gps_data`);
            if (!response.ok) throw new Error('Failed to load GPS data.');
            const data = await response.json();
            
            if (!data.laps || data.laps.length === 0 || !data.lap_times || data.lap_times.length === 0) {
                mapContainer.innerHTML = '';
                lapSelectorContainer.innerHTML = `<div class="alert alert-warning">このセッションには表示できるGPSデータまたはラップタイムがありません。</div>`;
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
                if (time < minTime) {
                    minTime = time;
                    bestLapIndex = index;
                }
            });

            let minSessionSpeed = Infinity;
            let maxSessionSpeed = 0;
            const nonZeroSpeeds = data.laps.flatMap(lap => lap.track.map(p => p.speed)).filter(s => s > 0);
            minSessionSpeed = nonZeroSpeeds.length > 0 ? Math.min(...nonZeroSpeeds) : 0;
            maxSessionSpeed = data.laps.flatMap(lap => lap.track.map(p => p.speed)).reduce((max, s) => Math.max(max, s || 0), 0);

            bounds = new google.maps.LatLngBounds();
            
            lapSelectorContainer.innerHTML = '';
            const lapList = document.createElement('ul');
            lapList.className = 'list-group';
            
            map = initializeMap('mapContainer', {lat: 0, lng: 0}, 15);

            data.laps.forEach((lapData, index) => {
                const lapTime = data.lap_times[index] || 'N/A';
                const isBest = index === bestLapIndex;
                
                if (!lapData.track || lapData.track.length < 2) {
                    polylines.push([]);
                    brakingMarkers.push([]);
                    accelMarkers.push([]);
                    return;
                }
                
                lapData.track.forEach(p => bounds.extend(p));
                
                const lapPolylines = drawLapPolyline(lapData.track, minSessionSpeed, maxSessionSpeed, null);
                polylines.push(lapPolylines);

                const { brakingPoints, accelPoints } = findSignificantPoints(lapData.track);

                const brakingIcon = {
                    path: 'M0,-5 L5,5 L-5,5 Z',
                    fillColor: 'red',
                    fillOpacity: 1.0,
                    strokeWeight: 0,
                    rotation: 180,
                    scale: 0.8,
                    anchor: new google.maps.Point(0, 0)
                };
                const accelIcon = {
                    path: 'M0,-5 L5,5 L-5,5 Z',
                    fillColor: 'limegreen',
                    fillOpacity: 1.0,
                    strokeWeight: 0,
                    scale: 0.8,
                    anchor: new google.maps.Point(0, 0)
                };
                
                brakingMarkers.push(brakingPoints.map(p => createMarker(p, brakingIcon, null)));
                accelMarkers.push(accelPoints.map(p => createMarker(p, accelIcon, null)));
                
                const listItem = document.createElement('li');
                listItem.className = 'list-group-item';
                listItem.innerHTML = `
                    <div class="form-check">
                        <input class="form-check-input lap-checkbox" type="checkbox" value="${index}" id="lapCheck${index}" checked>
                        <label class="form-check-label ${isBest ? 'fw-bold text-warning' : ''}" for="lapCheck${index}">
                            Lap ${lapData.lap_number} (${lapTime}) ${isBest ? '<i class="fas fa-crown ms-1"></i>' : ''}
                        </label>
                    </div>
                `;
                lapList.appendChild(listItem);
            });
            lapSelectorContainer.appendChild(lapList);

            if (map && !bounds.isEmpty()) {
                map.fitBounds(bounds);
                // 初期表示
                document.querySelectorAll('.lap-checkbox:checked').forEach(cb => {
                    const index = parseInt(cb.value);
                    if(polylines[index]) polylines[index].forEach(segment => segment.setMap(map));
                    if(brakingMarkers[index]) brakingMarkers[index].forEach(marker => marker.setMap(map));
                    if(accelMarkers[index]) accelMarkers[index].forEach(marker => marker.setMap(map));
                });
            }

            // ラップ表示切替
            document.querySelectorAll('.lap-checkbox').forEach(checkbox => {
                checkbox.addEventListener('change', (e) => {
                    const index = parseInt(e.target.value);
                    const isChecked = e.target.checked;
                    const targetMap = isChecked ? map : null;
                    if (polylines[index]) polylines[index].forEach(segment => segment.setMap(targetMap));

                    const showBraking = document.getElementById('toggleBrakingPoints').checked;
                    const showAccel = document.getElementById('toggleAccelPoints').checked;

                    if (brakingMarkers[index]) brakingMarkers[index].forEach(marker => marker.setMap(isChecked && showBraking ? map : null));
                    if (accelMarkers[index]) accelMarkers[index].forEach(marker => marker.setMap(isChecked && showAccel ? map : null));
                });
            });

            // マーカーオプションの表示切替
            document.getElementById('toggleBrakingPoints').addEventListener('change', (e) => {
                const isVisible = e.target.checked;
                document.querySelectorAll('.lap-checkbox:checked').forEach(cb => {
                    const index = parseInt(cb.value);
                    if(brakingMarkers[index]) brakingMarkers[index].forEach(marker => marker.setVisible(isVisible));
                });
            });
            document.getElementById('toggleAccelPoints').addEventListener('change', (e) => {
                const isVisible = e.target.checked;
                 document.querySelectorAll('.lap-checkbox:checked').forEach(cb => {
                    const index = parseInt(cb.value);
                    if(accelMarkers[index]) accelMarkers[index].forEach(marker => marker.setVisible(isVisible));
                });
            });

        } catch (error) {
            console.error('Error:', error);
            mapContainer.innerHTML = '';
            lapSelectorContainer.innerHTML = `<div class="alert alert-danger">データの読み込みに失敗しました。</div>`;
        }
    });

    document.getElementById('selectAllLaps')?.addEventListener('click', () => toggleAllLaps(true));
    document.getElementById('deselectAllLaps')?.addEventListener('click', () => toggleAllLaps(false));
    
    function toggleAllLaps(checked) {
        document.querySelectorAll('.lap-checkbox').forEach(cb => {
            if(cb.checked !== checked) {
                cb.checked = checked;
                cb.dispatchEvent(new Event('change'));
            }
        });
    }
});
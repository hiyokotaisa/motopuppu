// motopuppu/static/js/drivetrain_simulator.js
// 駆動系シミュレーター: スプロケット・チェーン変更シミュレーション

document.addEventListener('DOMContentLoaded', function () {
    // --- DOM参照 ---
    const specContainer = document.getElementById('spec-data');
    if (!specContainer) return;

    // 基本スペック入力
    const primaryRatioInput = document.getElementById('sim-primary-ratio');
    const tireSizeInput = document.getElementById('sim-tire-size');
    const tireCircDisplay = document.getElementById('tire-circ-display');

    // スプロケット: 現在
    const currentFrontInput = document.getElementById('current-front');
    const currentRearInput = document.getElementById('current-rear');
    const currentRatioDisplay = document.getElementById('current-ratio-display');

    // スプロケット: シミュレーション
    const simFrontInput = document.getElementById('sim-front');
    const simRearInput = document.getElementById('sim-rear');
    const simRatioDisplay = document.getElementById('sim-ratio-display');
    const ratioChangeDisplay = document.getElementById('ratio-change-display');

    // チェーン
    const chainSizeInput = document.getElementById('chain-size');
    const chainLinksInput = document.getElementById('chain-links');
    const chainResultDisplay = document.getElementById('chain-result');

    // RPM設定
    const rpmMaxInput = document.getElementById('rpm-max');
    const shiftRpmInput = document.getElementById('shift-rpm');

    // チャート＆テーブル
    const chartCanvas = document.getElementById('speed-chart');
    const shiftDataContainer = document.getElementById('shift-data-container');
    const ratioTableContainer = document.getElementById('ratio-table-container');

    let speedChartInstance = null;

    // --- ヘルパー関数 ---
    function parseTireSize(sizeString) {
        if (!sizeString) return null;
        const regex = /(\d+)\s*\/\s*(\d+)\s*[A-Za-z-]*\s*(\d+)/;
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
        return totalDiameterMm * Math.PI; // mm
    }

    function getGearRatios() {
        const ratios = {};
        document.querySelectorAll('.gear-ratio-input').forEach(input => {
            const gear = input.dataset.gear;
            const val = parseFloat(input.value);
            if (!isNaN(val) && val > 0) {
                ratios[gear] = val;
            }
        });
        return ratios;
    }

    function calculateSpeed(rpm, primaryRatio, gearRatio, secondaryRatio, tireCircM) {
        if (rpm === 0 || tireCircM === 0) return 0;
        const totalRatio = primaryRatio * gearRatio * secondaryRatio;
        return (rpm / totalRatio) * tireCircM * 60 / 1000;
    }

    function calculateRpmForSpeed(speed, primaryRatio, gearRatio, secondaryRatio, tireCircM) {
        if (speed === 0 || tireCircM === 0) return 0;
        return (speed * 1000 / 60) * (primaryRatio * gearRatio * secondaryRatio) / tireCircM;
    }

    // --- 表示更新関数 ---
    function updateTireCircumference() {
        const parsed = parseTireSize(tireSizeInput.value);
        if (parsed) {
            const circ = Math.round(calculateTireCircumference(...parsed));
            tireCircDisplay.textContent = `外周長: ${circ} mm`;
            tireCircDisplay.classList.remove('text-muted');
            tireCircDisplay.classList.add('text-success');
        } else {
            tireCircDisplay.textContent = tireSizeInput.value ? '形式エラー (例: 150/60R17)' : '未入力';
            tireCircDisplay.classList.remove('text-success');
            tireCircDisplay.classList.add('text-muted');
        }
    }

    function updateSecondaryRatios() {
        const cF = parseInt(currentFrontInput.value, 10);
        const cR = parseInt(currentRearInput.value, 10);
        const sF = parseInt(simFrontInput.value, 10);
        const sR = parseInt(simRearInput.value, 10);

        if (cF > 0 && cR > 0) {
            currentRatioDisplay.textContent = (cR / cF).toFixed(3);
        } else {
            currentRatioDisplay.textContent = '-.---';
        }

        if (sF > 0 && sR > 0) {
            const simRatio = sR / sF;
            simRatioDisplay.textContent = simRatio.toFixed(3);

            if (cF > 0 && cR > 0) {
                const currentRatio = cR / cF;
                const changePercent = ((simRatio - currentRatio) / currentRatio * 100).toFixed(1);
                const sign = changePercent > 0 ? '+' : '';
                const colorClass = changePercent > 0 ? 'text-danger' : (changePercent < 0 ? 'text-primary' : 'text-muted');
                const direction = changePercent > 0 ? '加速重視 ↑' : (changePercent < 0 ? '最高速重視 ↓' : '変化なし');
                ratioChangeDisplay.innerHTML = `<span class="${colorClass} fw-bold">${sign}${changePercent}%</span> <small class="text-muted">(${direction})</small>`;
            } else {
                ratioChangeDisplay.textContent = '';
            }
        } else {
            simRatioDisplay.textContent = '-.---';
            ratioChangeDisplay.textContent = '';
        }
    }

    function updateChainSimulation() {
        const currentLinks = parseInt(chainLinksInput.value, 10);
        const cF = parseInt(currentFrontInput.value, 10);
        const cR = parseInt(currentRearInput.value, 10);
        const sF = parseInt(simFrontInput.value, 10);
        const sR = parseInt(simRearInput.value, 10);

        if (!currentLinks || !cF || !cR || !sF || !sR) {
            chainResultDisplay.innerHTML = '<span class="text-muted">現在のスプロケット・チェーン情報とシミュレーション値を入力すると計算されます。</span>';
            return;
        }

        const deltaFront = sF - cF;
        const deltaRear = sR - cR;
        const requiredLinks = currentLinks + (deltaFront / 2) + (deltaRear / 2);
        const finalLinks = Math.ceil(requiredLinks / 2) * 2;
        const diff = finalLinks - currentLinks;

        let badgeClass = 'bg-success';
        let diffText = '変更なし';
        if (diff > 0) {
            badgeClass = 'bg-danger';
            diffText = `+${diff}L`;
        } else if (diff < 0) {
            badgeClass = 'bg-primary';
            diffText = `${diff}L`;
        }

        chainResultDisplay.innerHTML = `
            <div class="d-flex align-items-center gap-3">
                <div>
                    <span class="fs-4 fw-bold">${finalLinks}</span><span class="text-muted ms-1">L</span>
                </div>
                <span class="badge ${badgeClass}">${diffText}</span>
            </div>
            <div class="form-text mt-1">F: ${cF}→${sF} (${deltaFront >= 0 ? '+' : ''}${deltaFront}), R: ${cR}→${sR} (${deltaRear >= 0 ? '+' : ''}${deltaRear})</div>
            <div class="form-text text-warning"><i class="fas fa-exclamation-triangle me-1"></i>概算値です。最終的には実車での確認が必要です。</div>
        `;
    }

    // --- チャート ---
    function initChart() {
        if (speedChartInstance) {
            speedChartInstance.destroy();
        }
        const vehicleName = specContainer.dataset.vehicleName || '';
        speedChartInstance = new Chart(chartCanvas, {
            type: 'line',
            data: { datasets: [] },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: { display: true, text: `ギアレシオチャート - ${vehicleName}`, font: { size: 14 } },
                    tooltip: {
                        mode: 'index', intersect: false,
                        callbacks: {
                            label: function (context) {
                                let label = context.dataset.label || '';
                                if (label) label += ': ';
                                if (context.parsed.y !== null) {
                                    label += `${context.parsed.y} km/h @ ${context.parsed.x.toLocaleString()} RPM`;
                                }
                                return label;
                            }
                        }
                    },
                    legend: { position: 'top', labels: { usePointStyle: true, font: { size: 11 } } },
                    annotation: { annotations: {} }
                },
                scales: {
                    x: {
                        type: 'linear',
                        title: { display: true, text: 'エンジン回転数 (RPM)' },
                        min: 0,
                        ticks: { callback: v => v.toLocaleString() }
                    },
                    y: { title: { display: true, text: '理論速度 (km/h)' }, beginAtZero: true }
                }
            }
        });
    }

    function updateChart() {
        if (!speedChartInstance) initChart();

        const primaryRatio = parseFloat(primaryRatioInput.value);
        const gearRatios = getGearRatios();
        const rearTireParsed = parseTireSize(tireSizeInput.value);

        if (!primaryRatio || Object.keys(gearRatios).length === 0 || !rearTireParsed) {
            speedChartInstance.data.datasets = [];
            speedChartInstance.update();

            const noDataMsg = document.getElementById('chart-no-data');
            if (noDataMsg) noDataMsg.style.display = 'flex';
            return;
        }

        const noDataMsg = document.getElementById('chart-no-data');
        if (noDataMsg) noDataMsg.style.display = 'none';

        const tireCircM = calculateTireCircumference(...rearTireParsed) / 1000;
        const rpmMax = parseInt(rpmMaxInput.value, 10) || 14000;
        const shiftRpm = parseInt(shiftRpmInput.value, 10) || 13000;
        const rpmStep = 500;

        const cF = parseInt(currentFrontInput.value, 10);
        const cR = parseInt(currentRearInput.value, 10);
        const sF = parseInt(simFrontInput.value, 10);
        const sR = parseInt(simRearInput.value, 10);

        const hasCurrentSet = cF > 0 && cR > 0;
        const hasSimSet = sF > 0 && sR > 0;
        const isDifferentSet = hasCurrentSet && hasSimSet && (cF !== sF || cR !== sR);

        const gearColors = ['#0d6efd', '#6610f2', '#6f42c1', '#d63384', '#dc3545', '#fd7e14', '#ffc107'];
        const gearKeys = Object.keys(gearRatios).sort((a, b) => parseInt(a) - parseInt(b));
        const datasets = [];
        const annotations = {};

        // --- 現在のセットのライン ---
        if (hasCurrentSet) {
            const currentSecondary = cR / cF;
            for (const gearNum of gearKeys) {
                const gearRatio = gearRatios[gearNum];
                const data = [];
                for (let rpm = 0; rpm <= rpmMax; rpm += rpmStep) {
                    data.push({
                        x: rpm,
                        y: parseFloat(calculateSpeed(rpm, primaryRatio, gearRatio, currentSecondary, tireCircM).toFixed(1))
                    });
                }
                datasets.push({
                    label: isDifferentSet ? `現在 ${gearNum}速 (${cF}-${cR})` : `${gearNum}速`,
                    data: data,
                    borderColor: gearColors[parseInt(gearNum, 10) - 1] || '#6c757d',
                    fill: false, tension: 0.1, borderWidth: isDifferentSet ? 2 : 2.5,
                    borderDash: isDifferentSet ? [6, 3] : [],
                    pointRadius: 0,
                });
            }
        }

        // --- シミュレーションのライン ---
        if (hasSimSet) {
            const simSecondary = sR / sF;
            const shiftDataTable = [];

            for (const gearNum of gearKeys) {
                const gearRatio = gearRatios[gearNum];
                const data = [];
                for (let rpm = 0; rpm <= rpmMax; rpm += rpmStep) {
                    data.push({
                        x: rpm,
                        y: parseFloat(calculateSpeed(rpm, primaryRatio, gearRatio, simSecondary, tireCircM).toFixed(1))
                    });
                }
                datasets.push({
                    label: isDifferentSet ? `SIM ${gearNum}速 (${sF}-${sR})` : `${gearNum}速`,
                    data: data,
                    borderColor: isDifferentSet ? gearColors[parseInt(gearNum, 10) - 1] || '#6c757d' : gearColors[parseInt(gearNum, 10) - 1] || '#6c757d',
                    fill: false, tension: 0.1, borderWidth: 2.5,
                    borderDash: [],
                    pointRadius: 0,
                });
            }

            // 変速データ
            if (shiftRpm && shiftRpm <= rpmMax) {
                for (let i = 0; i < gearKeys.length - 1; i++) {
                    const currentGearNum = gearKeys[i];
                    const nextGearNum = gearKeys[i + 1];
                    const currentGearRatio = gearRatios[currentGearNum];
                    const nextGearRatio = gearRatios[nextGearNum];
                    const speedAtShift = calculateSpeed(shiftRpm, primaryRatio, currentGearRatio, simSecondary, tireCircM);
                    const rpmAfterShift = calculateRpmForSpeed(speedAtShift, primaryRatio, nextGearRatio, simSecondary, tireCircM);

                    if (rpmAfterShift < rpmMax) {
                        const rpmDrop = shiftRpm - rpmAfterShift;
                        shiftDataTable.push({
                            shift: `${currentGearNum}速 → ${nextGearNum}速`,
                            speed: speedAtShift.toFixed(1),
                            rpmAfter: Math.round(rpmAfterShift),
                            rpmDrop: Math.round(rpmDrop)
                        });
                        annotations[`shift${i}`] = {
                            type: 'line',
                            xMin: rpmAfterShift, xMax: shiftRpm,
                            yMin: speedAtShift, yMax: speedAtShift,
                            borderColor: 'rgba(220, 53, 69, 0.5)',
                            borderWidth: 1, borderDash: [3, 3],
                            label: {
                                content: `${Math.round(rpmDrop).toLocaleString()} RPM`,
                                display: true, position: 'center',
                                font: { size: 9 },
                                backgroundColor: 'rgba(255,255,255,0.8)',
                                color: '#333'
                            }
                        };
                    }
                }
            }
            generateShiftDataTable(shiftDataTable, shiftRpm);
        } else {
            if (shiftDataContainer) shiftDataContainer.innerHTML = '';
        }

        // 重複ライン除去（現在とシミュが同じ場合は現在セットのみ表示済み）
        if (!isDifferentSet && hasCurrentSet && hasSimSet) {
            // 同じセット: シミュレーションライン（後半）を除去
            datasets.splice(gearKeys.length);
        }

        speedChartInstance.data.datasets = datasets;
        speedChartInstance.options.scales.x.max = rpmMax;
        speedChartInstance.options.plugins.annotation = { annotations };
        speedChartInstance.update();
    }

    function generateShiftDataTable(data, shiftRpm) {
        if (!shiftDataContainer) return;
        if (!data || data.length === 0 || !shiftRpm) {
            shiftDataContainer.innerHTML = '';
            return;
        }
        let html = `
            <h6 class="mt-3"><i class="fas fa-exchange-alt me-1"></i>変速時データ <span class="badge bg-secondary fw-normal">@${shiftRpm.toLocaleString()} RPM</span></h6>
            <div class="table-responsive">
                <table class="table table-sm table-bordered mb-0" style="font-size: 0.85rem;">
                    <thead class="table-light"><tr><th>変速</th><th>速度 (km/h)</th><th>変速後RPM</th><th>回転落差</th></tr></thead>
                    <tbody>`;
        data.forEach(row => {
            html += `<tr><td>${row.shift}</td><td>${row.speed}</td><td>${row.rpmAfter.toLocaleString()}</td><td>${row.rpmDrop.toLocaleString()}</td></tr>`;
        });
        html += '</tbody></table></div>';
        shiftDataContainer.innerHTML = html;
    }

    // --- 減速比マトリックステーブル ---
    function updateRatioTable() {
        if (!ratioTableContainer) return;

        const sF = parseInt(simFrontInput.value, 10) || parseInt(currentFrontInput.value, 10);
        const sR = parseInt(simRearInput.value, 10) || parseInt(currentRearInput.value, 10);
        const cF = parseInt(currentFrontInput.value, 10);
        const cR = parseInt(currentRearInput.value, 10);

        if (!sF || !sR) {
            ratioTableContainer.innerHTML = '<p class="text-muted small">スプロケットの値を入力するとテーブルが表示されます。</p>';
            return;
        }

        const frontRange = Array.from({ length: 5 }, (_, i) => sF - 2 + i).filter(n => n > 0);
        const rearRange = Array.from({ length: 11 }, (_, i) => sR - 5 + i).filter(n => n > 0);

        let html = '<div class="table-responsive"><table class="table table-bordered table-sm text-center mb-0" style="font-size: 0.8rem;"><thead><tr><th class="table-light">R ＼ F</th>';
        frontRange.forEach(f => { html += `<th class="table-light">${f}T</th>`; });
        html += '</tr></thead><tbody>';
        rearRange.forEach(r => {
            html += `<tr><th class="table-light">${r}T</th>`;
            frontRange.forEach(f => {
                const isCurrent = (r === cR && f === cF);
                const isSim = (r === sR && f === sF);
                let cellClass = '';
                if (isCurrent && isSim) cellClass = 'table-primary';
                else if (isCurrent) cellClass = 'table-info';
                else if (isSim) cellClass = 'table-warning';
                html += `<td class="${cellClass}">${(r / f).toFixed(3)}</td>`;
            });
            html += '</tr>';
        });
        html += '</tbody></table></div>';
        html += '<div class="d-flex gap-3 mt-1"><small><span class="badge bg-info">■</span> 現在</small><small><span class="badge bg-warning">■</span> シミュレーション</small></div>';
        ratioTableContainer.innerHTML = html;
    }

    // --- イベントリスナー ---
    tireSizeInput.addEventListener('input', () => {
        updateTireCircumference();
        updateChart();
    });

    [currentFrontInput, currentRearInput].forEach(el => {
        el.addEventListener('input', () => {
            updateSecondaryRatios();
            updateChart();
            updateChainSimulation();
            updateRatioTable();
        });
    });

    [simFrontInput, simRearInput].forEach(el => {
        el.addEventListener('input', () => {
            updateSecondaryRatios();
            updateChart();
            updateChainSimulation();
            updateRatioTable();
        });
    });

    chainLinksInput.addEventListener('input', updateChainSimulation);

    [rpmMaxInput, shiftRpmInput].forEach(el => {
        el.addEventListener('input', updateChart);
    });

    document.querySelectorAll('.gear-ratio-input').forEach(el => {
        el.addEventListener('input', updateChart);
    });

    primaryRatioInput.addEventListener('input', updateChart);

    // +/- ボタン
    document.addEventListener('click', function (e) {
        const btn = e.target.closest('.btn-number');
        if (!btn) return;
        const type = btn.dataset.type;
        const fieldId = btn.dataset.field;
        const input = document.getElementById(fieldId);
        if (!input) return;
        const currentVal = parseFloat(input.value) || 0;
        const step = parseFloat(input.getAttribute('step')) || 1;
        const min = parseFloat(input.getAttribute('min'));

        if (type === 'minus') {
            if (isNaN(min) || currentVal > min) {
                input.value = currentVal - step;
                input.dispatchEvent(new Event('input', { bubbles: true }));
            }
        } else if (type === 'plus') {
            input.value = currentVal + step;
            input.dispatchEvent(new Event('input', { bubbles: true }));
        }
    });

    // 「現在値をコピー」ボタン
    const copyToSimBtn = document.getElementById('copy-current-to-sim');
    if (copyToSimBtn) {
        copyToSimBtn.addEventListener('click', () => {
            simFrontInput.value = currentFrontInput.value;
            simRearInput.value = currentRearInput.value;
            updateSecondaryRatios();
            updateChart();
            updateChainSimulation();
            updateRatioTable();
        });
    }

    // --- 初期化 ---
    updateTireCircumference();
    updateSecondaryRatios();
    updateChainSimulation();
    initChart();
    updateChart();
    updateRatioTable();
});

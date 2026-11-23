// 走行日のBeta UI: CSVの取り込み先、セッションへの移動、GPSへの直行。
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-activity-import]').forEach(form => {
        const target = form.querySelector('[name="target_session"]');
        const update = () => {
            const isNew = target.value === 'new';
            form.querySelector('[data-new-session-fields]').hidden = !isNew;
            form.querySelector('[data-import-mode]').hidden = isNew;
        };
        target.addEventListener('change', update);
        update();
    });
    document.querySelectorAll('.session-card .accordion-button[role="button"]').forEach(header => {
        header.addEventListener('keydown', event => {
            if (event.target !== header || !['Enter', ' '].includes(event.key)) return;
            event.preventDefault();
            bootstrap.Collapse.getOrCreateInstance(document.querySelector(header.dataset.bsTarget), {toggle: false}).toggle();
        });
    });
    const params = new URLSearchParams(window.location.search);
    if (params.get('import_csv') === '1') {
        const modal = document.getElementById('activityCsvImportModal');
        if (modal) bootstrap.Modal.getOrCreateInstance(modal).show();
    }
    if (params.get('gps') === '1') {
        let opened = false;
        const open = () => {
            if (opened || !window.google?.maps || !window.motopuppuMapViewer) return;
            const sessionId = Number(params.get('session_id'));
            const trigger = document.querySelector(`.session-actions .view-track-btn[data-session-id="${sessionId}"]`);
            const modal = document.getElementById('mapModal');
            if (!trigger || !modal) return;
            if (params.has('lap_number')) trigger.dataset.lapNumber = Number(params.get('lap_number'));
            opened = true;
            bootstrap.Modal.getOrCreateInstance(modal).show(trigger);
        };
        window.addEventListener('motopuppu:maps-ready', open, {once: true});
        open();
    }
});

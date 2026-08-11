/* Страница карты конкурентов.
 *
 * Данные и адреса приходят из шаблона через window.MAP_CONFIG — здесь нет
 * ничего, что зависит от Jinja, поэтому файл отдаётся статикой и кэшируется.
 */
(function () {
    'use strict';

    const CFG = window.MAP_CONFIG || {};
    const T = CFG.i18n || {};
    const CACHE_NAME = 'map-tiles-v2';

    // Выбор режима хранения переживает перезагрузку, метка сессии — нет.
    // На этой разнице и держится вкладочный режим: метки нет, значит вкладку
    // закрывали, значит накопленное надо выбросить.
    const LS_MODE = 'mapCache.mode';          // 'persist' | 'session'
    const LS_LIMIT = 'mapCache.maxBytes';
    const LS_BUFFER = 'mapCache.bufferTiles';
    const SS_ALIVE = 'mapCache.sessionAlive';

    const DEFAULTS = {
        mode: 'session',
        maxBytes: 2 * 1024 * 1024 * 1024,
        bufferTiles: 2
    };

    const settings = {
        get mode() { return localStorage.getItem(LS_MODE) || DEFAULTS.mode; },
        set mode(v) { localStorage.setItem(LS_MODE, v); },
        get maxBytes() { return parseInt(localStorage.getItem(LS_LIMIT), 10) || DEFAULTS.maxBytes; },
        set maxBytes(v) { localStorage.setItem(LS_LIMIT, String(v)); },
        get bufferTiles() {
            const v = parseInt(localStorage.getItem(LS_BUFFER), 10);
            return Number.isFinite(v) ? v : DEFAULTS.bufferTiles;
        },
        set bufferTiles(v) { localStorage.setItem(LS_BUFFER, String(v)); }
    };

    const fmtBytes = b => {
        if (!b) return '0 МБ';
        const gb = b / 1073741824;
        return gb >= 1 ? gb.toFixed(2) + ' ГБ' : Math.round(b / 1048576) + ' МБ';
    };

    // ================================================================
    // Раскладка: карта занимает всё, что осталось под шапкой
    // ================================================================
    document.body.classList.add('map-fullscreen');

    function syncTopOffset() {
        const header = document.querySelector('header.header');
        const h = header ? header.getBoundingClientRect().height : 0;
        document.documentElement.style.setProperty('--map-top-offset', h + 'px');
        return h;
    }
    syncTopOffset();

    // ================================================================
    // Карта
    // ================================================================
    const isDark = document.documentElement.getAttribute('data-bs-theme') === 'dark';
    const tileUrl = CFG.tileUrlTemplate.replace('__STYLE__', isDark ? 'dark' : 'light');

    const map = L.map('competitorMap', {
        zoomControl: false,
        center: CFG.center || [41.31, 69.24],
        zoom: CFG.zoom || 12
    });
    L.control.zoom({ position: 'bottomright' }).addTo(map);

    L.tileLayer(tileUrl, {
        maxZoom: 19,
        maxNativeZoom: CFG.maxNativeZoom,
        updateWhenZooming: false,
        updateWhenIdle: true,
        keepBuffer: 4,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(map);

    // Текущий масштаб — видно сразу при открытии, а не только после зума.
    const ZoomBadge = L.Control.extend({
        options: { position: 'bottomleft' },
        onAdd: function () {
            const el = L.DomUtil.create('div', 'map-zoom-badge');
            const render = () => {
                el.innerHTML = '<i class="bi bi-search"></i> ' + (T.zoom || 'Масштаб') +
                               ': <strong>' + map.getZoom() + '</strong>';
            };
            map.on('zoomend', render);
            render();
            return el;
        }
    });
    map.addControl(new ZoomBadge());

    // Высота шапки меняется при переносе меню, а Leaflet считает размеры один
    // раз при создании — после смены раскладки ему нужно пересчитать.
    let resizeTimer;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => { syncTopOffset(); map.invalidateSize(); }, 150);
    });
    // Панели выезжают поверх карты; после закрытия размеры тоже стоит освежить.
    document.addEventListener('hidden.bs.offcanvas', () => map.invalidateSize());

    // ================================================================
    // Отметки
    // ================================================================
    function makeIcon(file, size) {
        return new L.Icon({
            iconUrl: CFG.iconBase + file,
            shadowUrl: CFG.iconBase + 'marker-shadow.png',
            iconSize: size, iconAnchor: [size[0] / 2, size[1]],
            popupAnchor: [1, -34], shadowSize: [41, 41]
        });
    }
    const goldIcon = makeIcon('marker-icon-2x-gold.png', [25, 41]);
    const blueIcon = makeIcon('marker-icon-2x-blue.png', [25, 41]);
    const redIcon = makeIcon('marker-icon-2x-red.png', [30, 48]);

    const clusterGroup = L.markerClusterGroup({
        disableClusteringAtZoom: CFG.disableClusteringAtZoom,
        chunkedLoading: true,
        showCoverageOnHover: false,
        maxClusterRadius: 60,
        animate: false,
        animateAddingMarkers: false
    });
    map.addLayer(clusterGroup);

    const $ = id => document.getElementById(id);

    function updateMarkers() {
        const term = ($('searchName').value || '').trim().toLowerCase();
        const classFilter = $('filterClass').value;
        const ourProject = $('ourProject') ? $('ourProject').value : '';
        const selectedNorm = ourProject.trim().toLowerCase();

        clusterGroup.clearLayers();
        const batch = [];

        (CFG.competitors || []).forEach(c => {
            if (c.lat === 0 || c.lng === 0) return;
            const nameNorm = (c.name || '').trim().toLowerCase();
            const dCompNorm = (c.directComp || '').trim().toLowerCase();
            if (!nameNorm.includes(term)) return;
            if (classFilter && c.class !== classFilter) return;

            let icon = c.isInternal ? goldIcon : blueIcon;
            if (nameNorm === selectedNorm || dCompNorm === selectedNorm) icon = redIcon;

            const marker = L.marker([c.lat, c.lng], { icon: icon })
                .bindPopup(
                    '<div class="p-1"><h6 class="mb-1 fw-bold"></h6>' +
                    '<div class="small mb-2 text-muted"></div>' +
                    '<div class="d-grid"><a class="btn btn-xs btn-golden">' +
                    '<i class="bi bi-info-circle"></i> ' + (T.details || 'Подробнее') +
                    '</a></div></div>'
                )
                .on('popupopen', e => {
                    // Значения проставляем через textContent: имя ЖК приходит
                    // из внешней базы и в разметку его подставлять нельзя.
                    const root = e.popup.getElement();
                    root.querySelector('h6').textContent = c.name || '';
                    root.querySelector('.text-muted').textContent = c.class || '';
                    root.querySelector('a').href = CFG.prefix + '/competitors/' + c.id;
                })
                .on('click', () => loadComparison(c.id, ourProject));
            batch.push(marker);
        });

        clusterGroup.addLayers(batch);
        const counter = $('visibleCount');
        if (counter) counter.textContent = batch.length;
    }

    function loadComparison(compId, projectName) {
        const box = $('comparisonDetails');
        if (!box) return;
        box.innerHTML = '<div class="text-center p-3"><div class="spinner-border spinner-border-sm text-golden"></div></div>';
        fetch(CFG.prefix + '/competitors/compare/' + compId +
              '?our_project=' + encodeURIComponent(projectName))
            .then(r => r.text())
            .then(html => { box.innerHTML = html; openPanel('comparisonPanel'); });
    }

    ['searchName', 'filterClass', 'ourProject'].forEach(id => {
        const el = $(id);
        if (el) el.addEventListener(id === 'searchName' ? 'input' : 'change', updateMarkers);
    });

    // ================================================================
    // Панели: одинаково работают на телефоне и на большом экране
    // ================================================================
    function openPanel(id) {
        const el = $(id);
        if (!el) return;
        bootstrap.Offcanvas.getOrCreateInstance(el).show();
    }
    document.querySelectorAll('[data-open-panel]').forEach(btn => {
        btn.addEventListener('click', () => openPanel(btn.dataset.openPanel));
    });

    // ================================================================
    // Кэш карты
    // ================================================================
    const offline = {
        supported: 'serviceWorker' in navigator && !!window.caches,
        registration: null
    };

    function send(type, payload) {
        return new Promise((resolve, reject) => {
            navigator.serviceWorker.ready.then(reg => {
                const worker = reg.active;
                if (!worker) return reject(new Error('worker inactive'));
                const channel = new MessageChannel();
                channel.port1.onmessage = e => resolve(e.data);
                worker.postMessage(Object.assign({ type: type }, payload || {}),
                                   [channel.port2]);
            }, reject);
        });
    }

    function sendWithProgress(type, payload, onProgress) {
        return new Promise((resolve, reject) => {
            navigator.serviceWorker.ready.then(reg => {
                const worker = reg.active;
                if (!worker) return reject(new Error('worker inactive'));
                const channel = new MessageChannel();
                channel.port1.onmessage = e => {
                    if (e.data && e.data.type === 'PROGRESS') onProgress(e.data);
                    else resolve(e.data);
                };
                worker.postMessage(Object.assign({ type: type }, payload || {}),
                                   [channel.port2]);
            }, reject);
        });
    }

    function lonLatToTile(lat, lon, z) {
        const n = Math.pow(2, z);
        const x = Math.floor((lon + 180) / 360 * n);
        const latRad = lat * Math.PI / 180;
        const y = Math.floor((1 - Math.asinh(Math.tan(latRad)) / Math.PI) / 2 * n);
        return [Math.max(0, Math.min(n - 1, x)), Math.max(0, Math.min(n - 1, y))];
    }

    // Берём видимую область плюс поля с каждой стороны: при сдвиге карты
    // соседние плитки уже лежат в кэше, и обновление успевает за жестом.
    function collectUrls() {
        const bounds = map.getBounds();
        const buffer = settings.bufferTiles;
        const minZoom = Math.max(0, Math.round(map.getZoom()));
        const urls = [];
        for (let z = minZoom; z <= CFG.maxNativeZoom; z++) {
            const n = Math.pow(2, z);
            const [x1, y1] = lonLatToTile(bounds.getNorth(), bounds.getWest(), z);
            const [x2, y2] = lonLatToTile(bounds.getSouth(), bounds.getEast(), z);
            const xa = Math.max(0, Math.min(x1, x2) - buffer);
            const xb = Math.min(n - 1, Math.max(x1, x2) + buffer);
            const ya = Math.max(0, Math.min(y1, y2) - buffer);
            const yb = Math.min(n - 1, Math.max(y1, y2) + buffer);
            for (let x = xa; x <= xb; x++) {
                for (let y = ya; y <= yb; y++) {
                    urls.push(tileUrl.replace('{z}', z).replace('{x}', x).replace('{y}', y));
                }
            }
        }
        return urls;
    }

    // Точного пути к хранилищу браузер странице не даёт — доступа к файловой
    // системе у неё нет. Отдаём типовое расположение профиля для платформы.
    function guessCachePath() {
        const ua = navigator.userAgent;
        const isEdge = /Edg\//.test(ua);
        const isChrome = /Chrome\//.test(ua) && !isEdge;
        const isFirefox = /Firefox\//.test(ua);
        if (/Windows/.test(ua)) {
            if (isEdge) return '%LOCALAPPDATA%\\Microsoft\\Edge\\User Data\\Default\\Service Worker\\CacheStorage';
            if (isChrome) return '%LOCALAPPDATA%\\Google\\Chrome\\User Data\\Default\\Service Worker\\CacheStorage';
            if (isFirefox) return '%APPDATA%\\Mozilla\\Firefox\\Profiles\\<профиль>\\storage\\default';
        }
        if (/Android/.test(ua)) return '/data/data/<браузер>/app_webview/Service Worker/CacheStorage';
        if (/Mac OS X/.test(ua)) return '~/Library/Application Support/Google/Chrome/Default/Service Worker/CacheStorage';
        if (/Linux/.test(ua)) return '~/.config/google-chrome/Default/Service Worker/CacheStorage';
        return null;
    }

    async function refreshStats() {
        if (!offline.supported) return;
        let stats;
        try { stats = (await send('GET_STATS')).stats; } catch (e) { return; }
        const usage = $('cacheUsage');
        if (usage) {
            usage.textContent = fmtBytes(stats.bytes) +
                (stats.tiles ? ' · ' + stats.tiles.toLocaleString() + ' ' + (T.tiles || 'плиток') : '');
        }
        const bar = $('cacheUsageBar');
        if (bar && stats.maxBytes) {
            const pct = Math.min(100, Math.round((stats.bytes || 0) / stats.maxBytes * 100));
            bar.style.width = pct + '%';
            bar.classList.toggle('bg-danger', pct >= 90);
        }
    }

    async function applyStorageMode() {
        const persist = settings.mode === 'persist';
        const details = $('persistDetails');
        if (details) details.classList.toggle('d-none', !persist);

        if (persist) {
            if (navigator.storage && navigator.storage.persist) {
                try {
                    const granted = await navigator.storage.persisted() ||
                                    await navigator.storage.persist();
                    const note = $('persistState');
                    if (note) {
                        note.textContent = granted
                            ? (T.persistGranted || 'Браузер сохранит данные')
                            : (T.persistDenied || 'Браузер может очистить при нехватке места');
                    }
                } catch (e) { /* не критично */ }
            }
            sessionStorage.removeItem(SS_ALIVE);
        } else {
            sessionStorage.setItem(SS_ALIVE, '1');
        }
        refreshStats();
    }

    // Вкладочный режим: метка сессии живёт только внутри вкладки, поэтому её
    // отсутствие означает, что прошлую вкладку закрыли и кэш пора выбросить.
    async function dropCacheIfSessionEnded() {
        if (settings.mode === 'persist') return;
        if (sessionStorage.getItem(SS_ALIVE)) return;
        try { await caches.delete(CACHE_NAME); } catch (e) { /* уже нет */ }
        sessionStorage.setItem(SS_ALIVE, '1');
    }

    // Чистить по событию ухода со страницы нельзя: pagehide срабатывает и на
    // обычном переходе в другой раздел, а вкладка при этом жива. Признаком
    // служит только пропажа метки сессии, что и проверяется при загрузке.

    function bindSettingsUi() {
        const modeInputs = document.querySelectorAll('input[name="cacheMode"]');
        modeInputs.forEach(input => {
            input.checked = input.value === settings.mode;
            input.addEventListener('change', () => {
                if (!input.checked) return;
                settings.mode = input.value;
                applyStorageMode();
            });
        });

        const limitSel = $('cacheLimit');
        if (limitSel) {
            limitSel.value = String(settings.maxBytes);
            limitSel.addEventListener('change', async () => {
                settings.maxBytes = parseInt(limitSel.value, 10);
                try { await send('SET_CONFIG', { config: { maxBytes: settings.maxBytes } }); }
                catch (e) { /* воркер поднимется позже и прочитает настройки сам */ }
                refreshStats();
            });
        }

        const bufferSel = $('cacheBuffer');
        if (bufferSel) {
            bufferSel.value = String(settings.bufferTiles);
            bufferSel.addEventListener('change', () => {
                settings.bufferTiles = parseInt(bufferSel.value, 10);
            });
        }

        const copyBtn = $('copyPathBtn');
        if (copyBtn) {
            const path = guessCachePath();
            if (!path) copyBtn.classList.add('d-none');
            copyBtn.addEventListener('click', async () => {
                try {
                    await navigator.clipboard.writeText(path);
                    copyBtn.innerHTML = '<i class="bi bi-check2"></i> ' + (T.copied || 'Скопировано');
                    setTimeout(() => {
                        copyBtn.innerHTML = '<i class="bi bi-clipboard"></i> ' + (T.copyPath || 'Скопировать путь');
                    }, 1500);
                } catch (e) {
                    window.prompt(T.copyManually || 'Скопируйте путь вручную:', path);
                }
            });
        }

        const saveBtn = $('offlineSaveBtn');
        if (saveBtn) saveBtn.addEventListener('click', onSave);

        const clearBtn = $('offlineClearBtn');
        if (clearBtn) {
            clearBtn.addEventListener('click', async () => {
                if (!confirm(T.confirmClear || 'Удалить сохранённые плитки карты?')) return;
                try { await send('CLEAR_CACHE'); } catch (e) { await caches.delete(CACHE_NAME); }
                refreshStats();
            });
        }
    }

    async function onSave() {
        const saveBtn = $('offlineSaveBtn');
        const urls = collectUrls();
        const mb = Math.round(urls.length * 25 / 1024);
        const ok = confirm(
            (T.confirmSave || 'Сохранить видимый участок карты?') + '\n\n' +
            (T.tiles || 'Плиток') + ': ' + urls.length.toLocaleString() + '\n' +
            (T.approxSize || 'Примерный объём') + ': ~' + mb + ' МБ'
        );
        if (!ok) return;

        saveBtn.disabled = true;
        const box = $('offlineProgress');
        const bar = box.querySelector('.progress-bar');
        box.classList.remove('d-none');
        bar.style.width = '0%';

        try {
            const result = await sendWithProgress('PREFETCH_TILES',
                { urls: urls, total: urls.length, concurrency: 6 },
                d => {
                    bar.style.width = Math.round(d.done / d.total * 100) + '%';
                    $('offlineStatus').textContent = d.done.toLocaleString() + ' / ' +
                                                     d.total.toLocaleString();
                });
            $('offlineStatus').textContent = result && result.limitReached
                ? (T.limitReached || 'Достигнут лимит объёма — загрузка остановлена')
                : (T.saveDone || 'Готово');
        } catch (e) {
            $('offlineStatus').textContent = (T.workerInactive ||
                'Воркер ещё не активен, обновите страницу');
        } finally {
            saveBtn.disabled = false;
            box.classList.add('d-none');
            refreshStats();
        }
    }

    if (offline.supported) {
        navigator.serviceWorker.register(CFG.swUrl, { scope: CFG.swScope })
            .then(async reg => {
                offline.registration = reg;
                await dropCacheIfSessionEnded();
                bindSettingsUi();
                await applyStorageMode();
                try { await send('SET_CONFIG', { config: { maxBytes: settings.maxBytes } }); }
                catch (e) { /* активируется при следующем заходе */ }
                refreshStats();
            })
            .catch(err => {
                const box = $('offlineUnsupported');
                if (box) {
                    box.classList.remove('d-none');
                    box.textContent = (T.offlineUnavailable || 'Офлайн-режим недоступен') +
                                      ': ' + err.message;
                }
                const panel = $('offlineControls');
                if (panel) panel.classList.add('d-none');
            });
    } else {
        const box = $('offlineUnsupported');
        if (box) box.classList.remove('d-none');
        const panel = $('offlineControls');
        if (panel) panel.classList.add('d-none');
    }

    updateMarkers();
})();
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

    // Префикс «Leaflet» (вместе с флагом, который библиотека дописывает от
    // себя) убираем — он необязателен. Ссылка на OpenStreetMap остаётся:
    // данные под ODbL, и указание авторства это условие лицензии.
    // Опции карты сюда не доходят: Leaflet создаёт контрол без аргументов.
    if (map.attributionControl) map.attributionControl.setPrefix('');
    L.control.zoom({ position: 'bottomright' }).addTo(map);

    // Декодирование PNG по умолчанию происходит в главном потоке и на пачке
    // плиток даёт заметные паузы. decoding="async" отдаёт его браузеру,
    // который делает это параллельно и отрисовывает готовое.
    const FastTileLayer = L.TileLayer.extend({
        createTile: function (coords, done) {
            const tile = L.TileLayer.prototype.createTile.call(this, coords, done);
            tile.decoding = 'async';
            tile.fetchPriority = 'high';   // плитки важнее прочей мелочи
            return tile;
        }
    });

    new FastTileLayer(tileUrl, {
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

    // Загрузка идёт здесь, а не в Service Worker: воркер живёт, пока браузер
    // считает нужным, и на десятках тысяч плиток его успевают выгрузить
    // посреди работы — тогда обещание на странице не разрешается никогда,
    // и загрузка обрывается без единого сообщения. Страница живёт, пока
    // открыта вкладка.
    async function prefetchOnPage(urls, maxBytes, onProgress) {
        const cache = await caches.open(CACHE_NAME);
        const queue = await filterMissing(cache, urls);

        const stats = { done: 0, stored: 0, cached: urls.length - queue.length,
                        failed: 0, total: urls.length, limitReached: false };
        let index = 0;
        let used = await currentUsage();
        let sinceCheck = 0;

        async function worker() {
            while (index < queue.length && !stats.limitReached) {
                const url = queue[index++];
                try {
                    if (used !== null && used >= maxBytes) {
                        stats.limitReached = true;
                        return;
                    }
                    const res = await fetch(url, { credentials: 'same-origin' });
                    if (res.ok &&
                        (res.headers.get('Content-Type') || '').startsWith('image/') &&
                        !(res.headers.get('Cache-Control') || '').includes('no-store')) {
                        await cache.put(url, res.clone());
                        stats.stored++;
                        // Точный замер дорог, поэтому между сверками считаем
                        // приблизительно, а раз в сотню плиток уточняем.
                        if (used !== null) used += 25 * 1024;
                        if (++sinceCheck >= 100) {
                            sinceCheck = 0;
                            used = await currentUsage();
                        }
                    } else {
                        stats.failed++;
                    }
                } catch (e) {
                    stats.failed++;
                }
                stats.done++;
                if (onProgress && stats.done % 50 === 0) onProgress(stats);
            }
        }

        await Promise.all(Array.from({ length: 6 }, worker));
        if (onProgress) onProgress(stats);
        return stats;
    }

    async function currentUsage() {
        if (!navigator.storage || !navigator.storage.estimate) return null;
        try {
            const { usage } = await navigator.storage.estimate();
            return usage || 0;
        } catch (e) {
            return null;
        }
    }

    function lonLatToTile(lat, lon, z) {
        const n = Math.pow(2, z);
        const x = Math.floor((lon + 180) / 360 * n);
        const latRad = lat * Math.PI / 180;
        const y = Math.floor((1 - Math.asinh(Math.tan(latRad)) / Math.PI) / 2 * n);
        return [Math.max(0, Math.min(n - 1, x)), Math.max(0, Math.min(n - 1, y))];
    }

    // Плитки прямоугольника с полями по краям: при сдвиге карты соседние
    // уже лежат в кэше, и обновление успевает за жестом.
    function tilesForBox(bbox, z0, z1, buffer) {
        const [south, west, north, east] = bbox;
        const urls = [];
        for (let z = z0; z <= z1; z++) {
            const n = Math.pow(2, z);
            const [x1, y1] = lonLatToTile(north, west, z);
            const [x2, y2] = lonLatToTile(south, east, z);
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

    function collectUrls() {
        const b = map.getBounds();
        return tilesForBox([b.getSouth(), b.getWest(), b.getNorth(), b.getEast()],
                           Math.max(0, Math.round(map.getZoom())),
                           CFG.maxNativeZoom, settings.bufferTiles);
    }

    // У региона своя нарезка: чем дальше от центра, тем грубее уровень.
    // Поля по краям здесь не нужны — границы уже с запасом.
    function regionUrls(region) {
        const urls = [];
        region.layers.forEach(layer => {
            urls.push.apply(urls, tilesForBox(layer.bbox, layer.minZoom,
                                              layer.maxZoom, 0));
        });
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
            // tiles приходит null, когда записей столько, что их не пересчитать;
            // объём при этом известен.
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

        const openFolderBtn = $('openFolderBtn');
        if (openFolderBtn) {
            const path = guessCachePath();
            if (!path) openFolderBtn.classList.add('d-none');
            openFolderBtn.addEventListener('click', async () => {
                const shown = $('cachePathValue');
                if (shown) { shown.textContent = path; shown.classList.remove('d-none'); }
                try { await navigator.clipboard.writeText(path); } catch (e) { /* покажем текстом */ }
            });
        }

        loadRegions().catch(() => { /* регион просто не покажем */ });

        const clearBtn = $('offlineClearBtn');
        if (clearBtn) {
            clearBtn.addEventListener('click', async () => {
                if (!confirm(T.confirmClear || 'Удалить сохранённые плитки карты?')) return;
                try { await send('CLEAR_CACHE'); } catch (e) { await caches.delete(CACHE_NAME); }
                refreshStats();
            });
        }
    }

    async function download(urls, confirmText) {
        if (!confirm(confirmText)) return;

        // Кнопки регионов живут в своих карточках и блокируются отдельно.
        const buttons = [$('offlineSaveBtn')].filter(Boolean);
        buttons.forEach(b => { b.disabled = true; });
        const box = $('offlineProgress');
        const bar = box.querySelector('.progress-bar');
        box.classList.remove('d-none');
        bar.style.width = '0%';

        try {
            const result = await prefetchOnPage(urls, settings.maxBytes, s => {
                bar.style.width = Math.round(s.done / s.total * 100) + '%';
                $('offlineStatus').textContent = s.done.toLocaleString() + ' / ' +
                                                 s.total.toLocaleString();
            });
            $('offlineStatus').textContent = result.limitReached
                ? (T.limitReached || 'Достигнут лимит объёма — загрузка остановлена')
                : (T.saveDone || 'Готово');
        } catch (e) {
            $('offlineStatus').textContent = (T.downloadFailed || 'Загрузка прервана') +
                (e && e.message ? ': ' + e.message : '');
        } finally {
            buttons.forEach(b => { b.disabled = false; });
            box.classList.add('d-none');
            refreshStats();
        }
    }

    function onSave() {
        const urls = collectUrls();
        return download(urls,
            (T.confirmSave || 'Сохранить видимый участок карты?') + '\n\n' +
            (T.tiles || 'Плиток') + ': ' + urls.length.toLocaleString() + '\n' +
            (T.approxSize || 'Примерный объём') + ': ~' +
            Math.round(urls.length * 25 / 1024) + ' МБ');
    }

    // ================================================================
    // Готовые регионы
    // ================================================================
    let currentRegion = null;

    const absolute = url => new URL(url, location.origin).href;

    // Что уже лежит в кэше, выясняем пачками параллельных match.
    //
    // Крайности здесь одинаково плохи: cache.keys() отдаёт все записи одним
    // ответом и на десятках тысяч плиток падает с «Operation too large», а
    // поштучный await складывается в минуты ожидания. Пачка проверяется за
    // один тик и работает при любом размере кэша.
    const MATCH_BATCH = 200;

    async function filterMissing(cache, urls, onProgress) {
        const missing = [];
        for (let i = 0; i < urls.length; i += MATCH_BATCH) {
            const slice = urls.slice(i, i + MATCH_BATCH);
            const hits = await Promise.all(slice.map(url => cache.match(url)));
            hits.forEach((hit, j) => { if (!hit) missing.push(slice[j]); });
            if (onProgress) onProgress(Math.min(i + MATCH_BATCH, urls.length), urls.length);
        }
        return missing;
    }

    async function regionState(region, onProgress) {
        const cache = await caches.open(CACHE_NAME);
        const urls = regionUrls(region);
        const missing = await filterMissing(cache, urls, onProgress);
        const have = urls.length - missing.length;
        return { have: have, total: urls.length, missing: missing,
                 bytes: Math.round(have * (region.avgTileBytes || 25600)) };
    }

    let regions = [];
    const cards = new Map();        // id региона -> его элементы

    async function loadRegions() {
        const style = isDark ? 'dark' : 'light';
        const res = await fetch(CFG.prefix + '/tiles/regions?style=' + style,
                                { credentials: 'same-origin' });
        const data = await res.json();
        regions = data.regions || [];
        buildRegionCards();
        for (const region of regions) await refreshRegionCard(region);
    }

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function iconButton(className, icon, label) {
        const btn = el('button', className);
        btn.type = 'button';
        btn.innerHTML = '<i class="bi ' + icon + '"></i> ';
        btn.appendChild(document.createTextNode(label));
        return btn;
    }

    function buildRegionCards() {
        const list = $('regionList');
        if (!list) return;
        list.innerHTML = '';
        cards.clear();

        regions.forEach(region => {
            const card = el('div', 'card border-dashed p-2 mb-2');

            const head = el('div', 'd-flex justify-content-between align-items-start');
            const titleBox = el('div');
            // Название приходит с сервера — вставляем текстом, не разметкой.
            titleBox.appendChild(el('div', 'fw-bold small', region.title));
            const size = el('div', 'small text-muted', '—');
            titleBox.appendChild(size);
            head.appendChild(titleBox);
            head.appendChild(el('i', 'bi bi-map fs-5 text-golden'));
            card.appendChild(head);

            const meter = el('div', 'cache-meter my-2');
            const bar = el('div', 'bg-warning h-100');
            bar.style.width = '0%';
            meter.appendChild(bar);
            card.appendChild(meter);

            // Прогресс показывается здесь же, у своего региона: общий бар внизу
            // не давал понять, что именно грузится.
            const status = el('div', 'small text-muted mb-1');
            status.hidden = true;
            card.appendChild(status);

            // Когда всё на месте, кнопка загрузки уступает место отметке:
            // нажимать «обновить» на полном регионе незачем, а случайный
            // клик перекачивал бы его целиком.
            const ready = el('div', 'region-ready');
            ready.innerHTML = '<i class="bi bi-check-circle-fill"></i> ';
            ready.appendChild(document.createTextNode(
                T.regionUpToDate || 'Загружено, обновлений нет'));
            ready.hidden = true;
            card.appendChild(ready);

            const actions = el('div', 'd-grid gap-1');
            const download = iconButton('btn btn-sm btn-golden', 'bi-cloud-arrow-down',
                                        T.regionDownload || 'Загрузить регион');
            const goto = iconButton('btn btn-sm btn-outline-secondary', 'bi-geo-alt',
                                    T.regionGoto || 'Перейти к региону');
            const remove = iconButton('btn btn-sm btn-outline-secondary', 'bi-trash',
                                      T.regionDelete || 'Удалить регион');
            remove.classList.add('d-none');
            actions.appendChild(download);
            actions.appendChild(goto);
            actions.appendChild(remove);
            card.appendChild(actions);

            // Принудительная перезакачка остаётся, но мелкой ссылкой:
            // она нужна, только если плитки на сервере переснимали.
            const refresh = el('button', 'btn btn-link btn-sm p-0 mt-1 region-refresh',
                               T.regionRefresh || 'Обновить принудительно');
            refresh.type = 'button';
            refresh.hidden = true;
            card.appendChild(refresh);
            refresh.addEventListener('click', () => onRegionDownload(region, true));

            card.appendChild(el('div', 'small text-muted mt-1',
                region.measured
                    ? (T.regionMeasured || 'Вес посчитан по фактическому размеру плиток')
                    : (T.regionEstimated || 'Вес оценочный: сервер ещё не прогрет')));

            download.addEventListener('click', () => onRegionDownload(region));
            remove.addEventListener('click', () => onRegionDelete(region));
            goto.addEventListener('click', () => {
                map.setView(region.center, region.zoom);
                bootstrap.Offcanvas.getInstance($('settingsPanel')) &&
                    bootstrap.Offcanvas.getInstance($('settingsPanel')).hide();
            });

            list.appendChild(card);
            cards.set(region.id, { card, size, bar, status, download, remove, ready, refresh });
        });
    }

    async function refreshRegionCard(region) {
        const ui = cards.get(region.id);
        if (!ui) return;

        let state = { have: 0, total: region.tiles, bytes: 0 };
        try { state = await regionState(region); } catch (e) { /* кэша ещё нет */ }

        const pct = state.total ? Math.round(state.have / state.total * 100) : 0;
        const complete = state.have >= state.total && state.total > 0;

        ui.size.textContent = complete
            ? (T.regionReady || 'Загружен') + ' · ' + fmtBytes(state.bytes)
            : (state.have
                ? (T.regionPartial || 'Загружен частично') + ': ' + pct + '% · ' +
                  fmtBytes(state.bytes)
                : fmtBytes(region.bytes) + ' · ' +
                  region.tiles.toLocaleString() + ' ' + (T.tiles || 'плиток'));

        ui.bar.style.width = pct + '%';
        ui.bar.classList.toggle('bg-success', complete);
        ui.bar.classList.toggle('bg-warning', !complete);

        // Полный регион показывает отметку, неполный — кнопку с нужным словом.
        ui.ready.hidden = !complete;
        ui.refresh.hidden = !complete;
        ui.download.hidden = complete;
        if (!complete) {
            ui.download.innerHTML = '<i class="bi bi-cloud-arrow-down"></i> ';
            ui.download.appendChild(document.createTextNode(
                state.have ? (T.regionResume || 'Догрузить регион')
                           : (T.regionDownload || 'Загрузить регион')));
        }
        ui.remove.classList.toggle('d-none', state.have === 0);
    }

    async function onRegionDelete(region) {
        if (!confirm(T.confirmRegionDelete || 'Удалить сохранённый регион?')) return;
        const cache = await caches.open(CACHE_NAME);
        const urls = regionUrls(region);
        // Удаляем пачками по той же причине, что и проверяем: поштучный
        // обход сорока тысяч адресов занимает минуты.
        for (let i = 0; i < urls.length; i += MATCH_BATCH) {
            await Promise.all(urls.slice(i, i + MATCH_BATCH)
                                  .map(url => cache.delete(url)));
        }
        await refreshRegionCard(region);
        refreshStats();
    }

    // Поток байтов, из которого удобно забирать куски заданной длины.
    // Держим очередь пришедших чанков, а не один растущий буфер: регион
    // весит около гигабайта, и склеивать его в памяти нельзя.
    function byteStream(reader) {
        const queue = [];
        let queued = 0, done = false, consumed = 0;

        async function pull() {
            const { value, done: finished } = await reader.read();
            if (finished) { done = true; return false; }
            queue.push(value);
            queued += value.length;
            return true;
        }

        return {
            get consumed() { return consumed; },
            async read(n) {
                while (queued < n && !done) {
                    if (!await pull()) break;
                }
                if (queued < n) return null;        // поток кончился раньше
                const out = new Uint8Array(n);
                let filled = 0;
                while (filled < n) {
                    const head = queue[0];
                    const take = Math.min(head.length, n - filled);
                    out.set(head.subarray(0, take), filled);
                    filled += take;
                    if (take === head.length) queue.shift();
                    else queue[0] = head.subarray(take);
                    queued -= take;
                }
                consumed += n;
                return out;
            }
        };
    }

    function parseOctal(bytes) {
        const s = new TextDecoder().decode(bytes).replace(/\0.*$/, '').trim();
        return s ? parseInt(s, 8) : 0;
    }

    // Разбор ustar на лету: заголовок 512 байт, следом данные, выровненные
    // до кратности 512.
    async function unpackBundle(response, cache, onProgress) {
        const stream = byteStream(response.body.getReader());
        const decoder = new TextDecoder();
        // Запись в кэш пачками: по одной записи за раз хранилище ждёт
        // подтверждения каждой операции, и на десятках тысяч плиток это
        // становится основным расходом времени.
        const BATCH = 64;
        let batch = [];
        let stored = 0;

        async function flush() {
            if (!batch.length) return;
            const current = batch;
            batch = [];
            await Promise.all(current.map(item => cache.put(item.url, item.response)));
        }

        for (;;) {
            const header = await stream.read(512);
            if (!header) break;
            const name = decoder.decode(header.subarray(0, 100)).replace(/\0.*$/, '');
            if (!name) break;                       // два нулевых блока — конец
            const size = parseOctal(header.subarray(124, 136));
            const body = size ? await stream.read(size) : new Uint8Array(0);
            if (!body) break;
            const padding = (-size % 512 + 512) % 512;
            if (padding) await stream.read(padding);

            // Имя в архиве: <стиль>/<z>/<x>/<y>.png — восстанавливаем адрес,
            // под которым плитку будет искать карта.
            const m = name.match(/^([^/]+)\/(\d+)\/(\d+)\/(\d+)\.png$/);
            if (!m) continue;
            const url = CFG.tileUrlTemplate
                .replace('__STYLE__', m[1])
                .replace('{z}', m[2]).replace('{x}', m[3]).replace('{y}', m[4]);
            batch.push({
                url: url,
                response: new Response(body, {
                    headers: {
                        'Content-Type': 'image/png',
                        'Cache-Control': 'public, max-age=15552000'
                    }
                })
            });
            stored++;
            if (batch.length >= BATCH) {
                await flush();
                onProgress(stored, stream.consumed);
            }
        }
        await flush();
        return stored;
    }

    async function onRegionDownload(region, force) {
        const ui = cards.get(region.id);
        if (!ui) return;
        const ok = confirm(
            (force ? (T.confirmRegionRefresh || 'Перекачать регион заново?')
                   : (T.confirmRegion || 'Загрузить регион целиком?')) + '\n\n' +
            region.title + '\n' +
            (T.tiles || 'Плиток') + ': ' + region.tiles.toLocaleString() + '\n' +
            (T.approxSize || 'Примерный объём') + ': ' + fmtBytes(region.bytes));
        if (!ok) return;

        const say = text => { ui.status.hidden = false; ui.status.textContent = text; };
        const progress = pct => { ui.bar.style.width = pct + '%'; };

        ui.download.disabled = true;
        ui.refresh.disabled = true;
        ui.ready.hidden = true;
        ui.bar.classList.remove('bg-success');
        ui.bar.classList.add('bg-warning');
        progress(0);
        say(T.bundleStart || 'Загрузка одним пакетом...');

        const style = isDark ? 'dark' : 'light';
        try {
            const res = await fetch(
                CFG.prefix + '/tiles/region/' + region.id + '/bundle?style=' + style,
                { credentials: 'same-origin' });
            if (!res.ok || !res.body) throw new Error('bundle unavailable');

            const cache = await caches.open(CACHE_NAME);
            const stored = await unpackBundle(res, cache, (n, bytes) => {
                progress(Math.min(100, Math.round(n / region.tiles * 100)));
                say(n.toLocaleString() + ' / ' + region.tiles.toLocaleString() +
                    ' · ' + fmtBytes(bytes));
            });

            // В пакет попадает только то, что уже лежит в кэше сервера.
            // Остальное дотягиваем поштучно — так регион полон в любом случае.
            say(T.checkingCache || 'Проверяем, чего не хватает...');
            const missing = await filterMissing(cache, regionUrls(region),
                (done, total) => progress(Math.round(done / total * 100)));
            if (missing.length) {
                // Этого нет в кэше сервера, значит каждая плитка идёт во
                // внешний источник с паузами — фаза заметно медленнее пакета.
                say((T.fetchingRest || 'Догружаем остаток') + ': ' +
                    missing.length.toLocaleString() + ' — ' +
                    (T.slowPhase || 'сервер их ещё не прогрел, идёт медленно'));
                const rest = await prefetchOnPage(missing, settings.maxBytes, s => {
                    progress(Math.round(s.done / s.total * 100));
                    say((T.fetchingRest || 'Догружаем остаток') + ': ' +
                        s.done.toLocaleString() + ' / ' + s.total.toLocaleString());
                });
                if (rest.limitReached) {
                    say(T.limitReached || 'Достигнут лимит объёма — загрузка остановлена');
                    return;
                }
            }
            say((T.saveDone || 'Готово') + ': ' +
                (stored + missing.length).toLocaleString());
        } catch (e) {
            // Пакетная отдача не сложилась — тянем поштучно. Причину
            // показываем: молчаливый откат выглядел как сброс загрузки.
            say((T.bundleFallback || 'Пакет недоступен, загружаем поштучно') +
                (e && e.message ? ' (' + e.message + ')' : ''));
            try {
                const all = regionUrls(region);
                const result = await prefetchOnPage(all, settings.maxBytes, s => {
                    progress(Math.round(s.done / s.total * 100));
                    say(s.done.toLocaleString() + ' / ' + s.total.toLocaleString() +
                        (s.failed ? ' · ' + (T.failedCount || 'ошибок') + ': ' +
                                    s.failed.toLocaleString() : ''));
                });
                say(result.limitReached
                    ? (T.limitReached || 'Достигнут лимит объёма — загрузка остановлена')
                    : (T.saveDone || 'Готово') + ': ' + result.stored.toLocaleString() +
                      (result.failed ? ' · ' + (T.failedCount || 'ошибок') + ': ' +
                                       result.failed.toLocaleString() : ''));
            } catch (err) {
                say((T.downloadFailed || 'Загрузка прервана') +
                    (err && err.message ? ': ' + err.message : ''));
            }
        } finally {
            ui.download.disabled = false;
            ui.refresh.disabled = false;
            await refreshRegionCard(region);
            refreshStats();
            setTimeout(() => { ui.status.hidden = true; }, 4000);
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
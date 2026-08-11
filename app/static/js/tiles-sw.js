/* Service Worker для тайлов карты.
 *
 * Плитки складываются в Cache Storage на диске клиента и дальше отдаются
 * оттуда, без обращения к сети. Серверный прокси остаётся источником и
 * запасным путём: через него идёт всё, чего в кэше ещё нет.
 *
 * Воркер намеренно не знает про режимы хранения. Вкладочный режим страница
 * реализует сама, вычищая кэш при открытии новой сессии, — так у воркера не
 * появляется состояния, которое надо переживать между перезапусками.
 */
const CACHE_NAME = 'map-tiles-v2';
const TILE_PATH = '/tiles/';

// Настройки лежат в самом кэше под служебным ключом: воркер могут выгрузить
// в любой момент, и переменные в памяти после этого не восстановить.
const CONFIG_KEY = 'https://tile-cache.local/__config';
const DEFAULT_CONFIG = { maxBytes: 2 * 1024 * 1024 * 1024 };  // 2 ГБ

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', event => {
    event.waitUntil((async () => {
        const names = await caches.keys();
        await Promise.all(
            names.filter(n => n.startsWith('map-tiles-') && n !== CACHE_NAME)
                 .map(n => caches.delete(n))
        );
        await self.clients.claim();
    })());
});

async function readConfig() {
    try {
        const cache = await caches.open(CACHE_NAME);
        const hit = await cache.match(CONFIG_KEY);
        if (hit) return Object.assign({}, DEFAULT_CONFIG, await hit.json());
    } catch (e) { /* повреждённый конфиг — берём значения по умолчанию */ }
    return Object.assign({}, DEFAULT_CONFIG);
}

async function writeConfig(config) {
    const cache = await caches.open(CACHE_NAME);
    await cache.put(CONFIG_KEY, new Response(JSON.stringify(config), {
        headers: { 'Content-Type': 'application/json' }
    }));
}

function isTileRequest(request) {
    if (request.method !== 'GET') return false;
    const url = new URL(request.url);
    return url.origin === self.location.origin && url.pathname.includes(TILE_PATH);
}

// Кэшируем только настоящие плитки. Прокси отдаёт прозрачный 1x1 с
// Cache-Control: no-store, когда источник недоступен, — такой ответ
// сохранять нельзя, иначе дырка в карте застынет навсегда.
function isCacheable(response) {
    if (!response || response.status !== 200) return false;
    if ((response.headers.get('Cache-Control') || '').includes('no-store')) return false;
    return (response.headers.get('Content-Type') || '').startsWith('image/');
}

async function usedBytes() {
    if (!self.navigator.storage || !self.navigator.storage.estimate) return null;
    const { usage } = await self.navigator.storage.estimate();
    return usage || 0;
}

// Считать точный вес кэша дорого, поэтому проверяем не на каждой записи.
let writesSinceCheck = 0;
const CHECK_EVERY = 50;

async function enforceLimit(force) {
    if (!force && ++writesSinceCheck < CHECK_EVERY) return;
    writesSinceCheck = 0;

    const config = await readConfig();
    const used = await usedBytes();
    if (used === null || used <= config.maxBytes) return;

    // cache.keys() отдаёт записи в порядке добавления, так что удаление
    // с начала выбрасывает самые давние плитки.
    const cache = await caches.open(CACHE_NAME);
    const keys = await cache.keys();
    const overshoot = used - config.maxBytes;
    // Оценка по среднему весу плитки: точный размер каждой записи пришлось бы
    // читать телом, а это дороже самой очистки.
    const approxTile = 25 * 1024;
    let toDrop = Math.ceil(overshoot / approxTile) + 50;
    for (const key of keys) {
        if (toDrop-- <= 0) break;
        if (key.url === CONFIG_KEY) continue;
        await cache.delete(key);
    }
}

self.addEventListener('fetch', event => {
    if (!isTileRequest(event.request)) return;

    event.respondWith((async () => {
        const cache = await caches.open(CACHE_NAME);
        const hit = await cache.match(event.request);
        if (hit) return hit;

        // credentials обязательны: роут тайлов закрыт авторизацией,
        // без куки прокси ответит редиректом на страницу входа.
        const response = await fetch(event.request, { credentials: 'same-origin' });
        if (isCacheable(response)) {
            await cache.put(event.request, response.clone());
            event.waitUntil(enforceLimit(false));
        }
        return response;
    })());
});

async function collectStats() {
    const cache = await caches.open(CACHE_NAME);
    const keys = await cache.keys();
    const config = await readConfig();
    return {
        tiles: keys.filter(k => k.url !== CONFIG_KEY).length,
        bytes: await usedBytes(),
        maxBytes: config.maxBytes
    };
}

async function prefetch(msg, port) {
    const cache = await caches.open(CACHE_NAME);
    const urls = msg.urls || [];
    const total = urls.length;
    const concurrency = Math.max(1, Math.min(msg.concurrency || 6, 12));
    const config = await readConfig();
    let done = 0, stored = 0, cached = 0, failed = 0, stopped = false;

    // Что уже лежит в кэше, узнаём одним запросом ключей. Отдельный
    // cache.match на каждый адрес превращался в десятки тысяч обращений
    // к хранилищу и съедал больше времени, чем сама загрузка.
    const existing = new Set((await cache.keys()).map(request => request.url));
    const has = url => existing.has(new URL(url, self.location.origin).href);

    // navigator.storage.estimate() обходит хранилище и дорожает по мере его
    // роста. Раньше он вызывался перед каждой плиткой и к середине большого
    // региона практически останавливал загрузку. Теперь — раз в сотню штук.
    const LIMIT_CHECK_EVERY = 100;
    let sinceLimitCheck = 0;
    let lastUsed = await usedBytes();

    async function overLimit() {
        if (lastUsed === null) return false;
        if (++sinceLimitCheck >= LIMIT_CHECK_EVERY) {
            sinceLimitCheck = 0;
            lastUsed = await usedBytes();
        } else {
            // Между замерами ведём приблизительный счёт, чтобы не проскочить
            // лимит далеко за границу.
            lastUsed += 25 * 1024;
        }
        return lastUsed >= config.maxBytes;
    }

    async function worker() {
        while (!stopped) {
            const url = urls.shift();
            if (url === undefined) return;
            try {
                if (has(url)) {
                    cached++;
                } else {
                    if (await overLimit()) {
                        stopped = true;   // упёрлись в лимит, дальше не тянем
                        return;
                    }
                    const res = await fetch(url, { credentials: 'same-origin' });
                    if (isCacheable(res)) {
                        await cache.put(url, res.clone());
                        existing.add(new URL(url, self.location.origin).href);
                        stored++;
                    } else {
                        failed++;
                    }
                }
            } catch (e) {
                failed++;
            }
            done++;
            if (port && done % 25 === 0) {
                port.postMessage({ type: 'PROGRESS', done, total, stored, cached, failed });
            }
        }
    }

    await Promise.all(Array.from({ length: concurrency }, worker));
    const stats = await collectStats();
    if (port) {
        port.postMessage({ type: 'DONE', done, total, stored, cached, failed,
                           limitReached: stopped, stats });
    }
}

self.addEventListener('message', event => {
    const msg = event.data || {};
    const port = event.ports && event.ports[0];

    if (msg.type === 'PREFETCH_TILES') {
        event.waitUntil(prefetch(msg, port));
    } else if (msg.type === 'SET_CONFIG') {
        event.waitUntil((async () => {
            const config = Object.assign(await readConfig(), msg.config || {});
            await writeConfig(config);
            await enforceLimit(true);
            if (port) port.postMessage({ type: 'CONFIG_SET', stats: await collectStats() });
        })());
    } else if (msg.type === 'GET_STATS') {
        event.waitUntil((async () => {
            if (port) port.postMessage({ type: 'STATS', stats: await collectStats() });
        })());
    } else if (msg.type === 'CLEAR_CACHE') {
        event.waitUntil((async () => {
            const config = await readConfig();
            await caches.delete(CACHE_NAME);
            await writeConfig(config);          // настройки переживают очистку
            if (port) port.postMessage({ type: 'CLEARED', stats: await collectStats() });
        })());
    }
});
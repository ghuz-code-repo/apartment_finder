document.addEventListener('DOMContentLoaded', function() {
    const currencyToggle = document.getElementById('currencyToggle');
    const currencyLabel = document.getElementById('currencyLabel');
    const usdRate = parseFloat(document.body.dataset.usdRate) || 12650;
    const exportLink = document.getElementById('export-link');

    const STORAGE_KEYS = {
        currency: 'planFactReport_currencyIsUSD',
        activeTab: 'planFactReport_activeTab'
    };

    /**
     * Обновляет отображение валют на странице и динамически перестраивает
     * ссылку на экспорт, сохраняя все выбранные фильтры.
     */
    function updateCurrency(isUsd) {
        // 1. Обновление числовых значений в таблицах и карточках
        document.querySelectorAll('.currency-value').forEach(el => {
            const uzsValue = parseFloat(el.dataset.uzsValue);
            if (isNaN(uzsValue)) return;

            let displayValue;
            if (isUsd) {
                if (currencyLabel) currencyLabel.textContent = 'USD';
                let usdValue = uzsValue / usdRate;
                displayValue = '$' + usdValue.toLocaleString('en-US', { maximumFractionDigits: 0 });
            } else {
                if (currencyLabel) currencyLabel.textContent = 'UZS';
                displayValue = uzsValue.toLocaleString('ru-RU', { maximumFractionDigits: 0 }).replace(/,/g, '.');
            }

            const link = el.querySelector('a');
            if (link) {
                link.textContent = displayValue;
            } else {
                el.textContent = displayValue;
            }
        });

        // 2. ИСПРАВЛЕННАЯ ЛОГИКА ОБНОВЛЕНИЯ ССЫЛКИ ЭКСПОРТА
        if (exportLink) {
            // Берем базовый URL (без параметров) из сохраненного аттрибута или отрезаем от href
            const baseUrl = exportLink.dataset.baseUrl || exportLink.getAttribute('href').split('?')[0];
            const url = new URL(baseUrl, window.location.origin);

            // Собираем все текущие значения фильтров с формы
            const filters = {
                'year': document.getElementById('year'),
                'month': document.getElementById('month'),
                'period': document.getElementById('period'),
                'property_type': document.getElementById('property_type'),
                'group_by': document.getElementById('groupBySelect') // Для сводки по остаткам
            };

            for (let key in filters) {
                if (filters[key]) {
                    url.searchParams.set(key, filters[key].value);
                }
            }

            // Добавляем параметр валюты
            url.searchParams.set('currency', isUsd ? 'USD' : 'UZS');

            // Обновляем итоговый адрес кнопки экспорта
            exportLink.href = url.toString();
        }
    }

    function restoreState() {
        const savedCurrencyIsUSD = localStorage.getItem(STORAGE_KEYS.currency);
        if (savedCurrencyIsUSD === 'true' && currencyToggle) {
            currencyToggle.checked = true;
        }
        updateCurrency(currencyToggle ? currencyToggle.checked : false);

        const savedTabId = localStorage.getItem(STORAGE_KEYS.activeTab);
        if (savedTabId) {
            const tabTrigger = document.querySelector(`button[data-bs-target="${savedTabId}"]`);
            if (tabTrigger) {
                // Удаляем активные классы с дефолтных вкладок
                document.querySelectorAll('.nav-link.active, .tab-pane.show.active').forEach(el => {
                    el.classList.remove('active', 'show');
                });
                // Активируем сохраненную
                tabTrigger.classList.add('active');
                const pane = document.querySelector(savedTabId);
                if (pane) {
                    pane.classList.add('show', 'active');
                }
            }
        }
    }

    // Сортировка таблиц
    function sortTable(table, column, asc = true) {
        const dirModifier = asc ? 1 : -1;
        const tBody = table.tBodies[0];
        const rows = Array.from(tBody.querySelectorAll("tr"));
        const headerCell = table.querySelector(`th:nth-child(${column + 1})`);
        if (!headerCell) return;

        const isNumeric = headerCell.dataset.type === 'numeric';

        const sortedRows = rows.sort((a, b) => {
            const aCell = a.querySelector(`td:nth-child(${column + 1})`);
            const bCell = b.querySelector(`td:nth-child(${column + 1})`);
            if (!aCell || !bCell) return 0;

            const aColText = aCell.textContent.trim();
            const bColText = bCell.textContent.trim();

            if (isNumeric) {
                const aVal = parseFloat(aColText.replace(/[^0-9.-]+/g, ""));
                const bVal = parseFloat(bColText.replace(/[^0-9.-]+/g, ""));
                return (aVal - bVal) * dirModifier;
            }
            return aColText.localeCompare(bColText, 'ru', { sensitivity: 'base' }) * dirModifier;
        });

        tBody.append(...sortedRows);
        table.querySelectorAll("th").forEach(th => th.classList.remove("th-asc", "th-desc"));
        headerCell.classList.toggle("th-asc", asc);
        headerCell.classList.toggle("th-desc", !asc);
    }

    document.querySelectorAll("th[data-sortable]").forEach(headerCell => {
        headerCell.addEventListener("click", () => {
            const tableElement = headerCell.closest('table');
            const headerIndex = Array.prototype.indexOf.call(headerCell.parentElement.children, headerCell);
            const currentIsAsc = headerCell.classList.contains("th-asc");
            sortTable(tableElement, headerIndex, !currentIsAsc);
        });
    });

    // Поиск по проектам
    const searchInput = document.getElementById('projectSearchInput');
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            const searchTerm = searchInput.value.toLowerCase().trim();
            // Ищем во всех таблицах на странице
            document.querySelectorAll('table tbody').forEach(tbody => {
                tbody.querySelectorAll('tr').forEach(row => {
                    const projectNameEl = row.querySelector('td:first-child');
                    if (projectNameEl) {
                        const projectName = projectNameEl.textContent.toLowerCase();
                        row.style.display = projectName.includes(searchTerm) ? '' : 'none';
                    }
                });
            });
        });
    }

    // Обработка переключения валюты
    if (currencyToggle) {
        currencyToggle.addEventListener('change', function() {
            localStorage.setItem(STORAGE_KEYS.currency, this.checked);
            updateCurrency(this.checked);
        });
    }

    // Сохранение активной вкладки
    document.querySelectorAll('button[data-bs-toggle="tab"]').forEach(tab => {
        tab.addEventListener('shown.bs.tab', function (event) {
            const activeTabId = event.target.dataset.bsTarget;
            localStorage.setItem(STORAGE_KEYS.activeTab, activeTabId);
        });
    });

    // Инициализация при загрузке
    if (exportLink) {
        // Сохраняем базовый URL без параметров для последующих обновлений
        exportLink.dataset.baseUrl = exportLink.getAttribute('href').split('?')[0];
    }

    restoreState();
});
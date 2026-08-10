document.addEventListener('DOMContentLoaded', function () {
    if (typeof charts_json_data === 'undefined') {
        console.error('Данные для графиков (charts_json_data) не найдены.');
        return;
    }

    const usdRate = parseFloat(document.body.dataset.usdRate) || 13000;
    const initializedCharts = {}; // Реестр созданных экземпляров Chart.js

    // --- ФУНКЦИЯ ФОРМАТИРОВАНИЯ ВАЛЮТ ---
    function formatCurrency(value, isUsd) {
        const prefix = isUsd ? '$' : '';
        const locale = isUsd ? 'en-US' : 'ru-RU';
        return prefix + new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(value);
    }

    // --- РЕЕСТР ИНИЦИАЛИЗАТОРОВ ГРАФИКОВ ---
    const chartInitializers = {

        /**
         * График: План/Факт (Динамика продаж)
         */
        'planFactChart': (isUsd) => {
            const dynamics = charts_json_data.plan_fact_dynamics_yearly;
            const ctx = document.getElementById('planFactChart');
            if (!ctx || !dynamics) return;

            const divisor = isUsd ? usdRate : 1;
            initializedCharts['planFactChart'] = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: dynamics.labels,
                    datasets: [
                        { type: 'line', label: window.i18n.plan_contracting, data: dynamics.plan_volume.map(v => v / divisor), borderColor: 'rgba(54, 162, 235, 1)', fill: false, tension: 0.1 },
                        { type: 'bar', label: window.i18n.fact_contracting, data: dynamics.fact_volume.map(v => v / divisor), backgroundColor: 'rgba(75, 192, 192, 0.7)' },
                        { type: 'line', label: window.i18n.plan_income, data: dynamics.plan_income.map(v => v / divisor), borderColor: 'rgba(255, 99, 132, 1)', fill: false, tension: 0.1 },
                        { type: 'bar', label: window.i18n.fact_income, data: dynamics.fact_income.map(v => v / divisor), backgroundColor: 'rgba(255, 206, 86, 0.7)' }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: { y: { beginAtZero: true, ticks: { callback: value => formatCurrency(value, isUsd) } } },
                    plugins: { tooltip: { callbacks: { label: context => `${context.dataset.label}: ${formatCurrency(context.parsed.y, isUsd)}` } } }
                }
            });
        },

        /**
         * Графики: Анализ спроса (Этаж, Комнаты, Площадь)
         */
        'analysisCharts': () => {
            const analysis = charts_json_data.sales_analysis;
            if (!analysis) return;

            const config = [
                { id: 'floorChart', data: analysis.by_floor, label: window.i18n.units_sold },
                { id: 'roomsChart', data: analysis.by_rooms, label: window.i18n.units_sold },
                { id: 'areaChart', data: analysis.by_area, label: window.i18n.units_sold }
            ];

            config.forEach(item => {
                const ctx = document.getElementById(item.id);
                if (!ctx) return;
                if (!item.data || !item.data.data || !item.data.data.length) {
                    ctx.parentElement.innerHTML = '<div class="alert alert-secondary text-center">Нет данных для анализа.</div>';
                    return;
                }
                initializedCharts[item.id] = new Chart(ctx, {
                    type: 'bar',
                    data: { labels: item.data.labels, datasets: [{ label: item.label, data: item.data.data, backgroundColor: 'rgba(75, 192, 192, 0.7)' }] },
                    options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } }, plugins: { legend: { display: false } } }
                });
            });
        },

        /**
         * График: Динамика цен
         */
        'priceDynamicsChart': (isUsd) => {
            const chartData = charts_json_data.price_dynamics;
            const ctx = document.getElementById('priceDynamicsChart');
            if (!ctx || !chartData || !chartData.data || !chartData.data.length) return;

            const divisor = isUsd ? usdRate : 1;
            initializedCharts['priceDynamicsChart'] = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: chartData.labels,
                    datasets: [{ label: window.i18n.avg_price, data: chartData.data.map(p => p / divisor), borderColor: 'rgba(153, 102, 255, 1)', backgroundColor: 'rgba(153, 102, 255, 0.2)', fill: true, tension: 0.1 }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: { y: { beginAtZero: false, ticks: { callback: value => formatCurrency(value, isUsd) } } },
                    plugins: { legend: { display: false }, tooltip: { callbacks: { label: context => `${context.dataset.label}: ${formatCurrency(context.parsed.y, isUsd)}` } } }
                }
            });
        },

        /**
         * KPI и график темпа продаж (Структура продаж)
         */
        'salesPaceMetrics': () => {
            const paceData = charts_json_data.sales_pace_kpi;
            if (!paceData) return;

            const currentEl = document.getElementById('pace-current');
            const maxEl = document.getElementById('pace-max');
            const minEl = document.getElementById('pace-min');

            if (currentEl) currentEl.textContent = paceData.current.toFixed(1);
            if (maxEl) maxEl.textContent = paceData.max.toFixed(1);
            if (minEl) minEl.textContent = paceData.min.toFixed(1);

            const ctx = document.getElementById('paceQuarterlyChart');
            if (ctx && paceData.quarterly_comparison) {
                initializedCharts['paceQuarterlyChart'] = new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: paceData.quarterly_comparison.labels,
                        datasets: [{ label: 'Темп', data: paceData.quarterly_comparison.data, backgroundColor: 'rgba(153, 102, 255, 0.7)' }]
                    },
                    options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } }, plugins: { legend: { display: false } } }
                });
            }
        },

        /**
         * График: Анализ вымываемости планировок (%) и цена дна
         */
        'layoutAnalysisChart': () => {
            const ctx = document.getElementById('layoutChart');
            if (!ctx) return;

            const lData = charts_json_data.layout_analysis || (charts_json_data.charts ? charts_json_data.charts.layout_analysis : []);

            if (!lData || lData.length === 0) {
                ctx.parentElement.innerHTML = '<div class="alert alert-secondary text-center">Нет данных по планировкам.</div>';
                return;
            }

            const isUsd = document.getElementById('currencyToggle')?.checked;
            const divisor = isUsd ? usdRate : 1;
            const topLayouts = lData.slice(0, 15);

            initializedCharts['layoutChart'] = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: topLayouts.map(i => i.name),
                    datasets: [
                        {
                            label: 'Вымываемость (%)',
                            data: topLayouts.map(i => i.total > 0 ? ((i.sold / i.total) * 100).toFixed(1) : 0),
                            backgroundColor: 'rgba(75, 192, 192, 0.7)',
                            yAxisID: 'y'
                        },
                        {
                            label: isUsd ? 'Цена дна (USD/м²)' : 'Цена дна (UZS/м²)',
                            data: topLayouts.map(i => i.avg_bottom / divisor),
                            type: 'line',
                            borderColor: '#c59500',
                            yAxisID: 'y1',
                            tension: 0.3,
                            borderWidth: 3,
                            pointRadius: 4,
                            pointBackgroundColor: '#c59500'
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            position: 'left',
                            beginAtZero: true,
                            max: 100,
                            title: { display: true, text: '%' }
                        },
                        y1: {
                            position: 'right',
                            grid: { drawOnChartArea: false },
                            title: { display: true, text: isUsd ? 'USD/м²' : 'UZS/м²' },
                            ticks: { callback: value => formatCurrency(value, isUsd) }
                        }
                    },
                    plugins: {
                        tooltip: {
                            callbacks: {
                                label: (context) => {
                                    let label = context.dataset.label || '';
                                    if (label) label += ': ';
                                    if (context.datasetIndex === 0) {
                                        label += context.parsed.y + '%';
                                    } else {
                                        label += formatCurrency(context.parsed.y, isUsd);
                                    }
                                    return label;
                                }
                            }
                        }
                    }
                }
            });
        }
    };

    // --- ЛОГИКА ПЕРЕКЛЮЧЕНИЯ ВКЛАДОК (Lazy Loading) ---
    const tabs = document.querySelectorAll('button[data-bs-toggle="tab"]');
    tabs.forEach(tab => {
        tab.addEventListener('shown.bs.tab', function (event) {
            const targetPaneId = event.target.getAttribute('data-bs-target');
            const isUsd = document.getElementById('currencyToggle')?.checked;

            if (targetPaneId === '#remainders-pane' && !initializedCharts['paceQuarterlyChart']) {
                chartInitializers.salesPaceMetrics();
            } else if (targetPaneId === '#analysis-pane' && !initializedCharts['floorChart']) {
                chartInitializers.analysisCharts();
            } else if (targetPaneId === '#pricing-pane' && !initializedCharts['priceDynamicsChart']) {
                chartInitializers.priceDynamicsChart(isUsd);
            } else if (targetPaneId === '#layout-pane' && !initializedCharts['layoutChart']) {
                chartInitializers.layoutAnalysisChart();
            }
        });
    });

    // --- ИНИЦИАЛИЗАЦИЯ ПРИ ЗАГРУЗКЕ СТРАНИЦЫ ---
    const isInitiallyUsd = document.getElementById('currencyToggle')?.checked;
    const activeTabPane = document.querySelector('.tab-content .tab-pane.show.active');

    if (activeTabPane) {
        const activeId = activeTabPane.id;
        if (activeId === 'dynamics-pane') {
            chartInitializers.planFactChart(isInitiallyUsd);
        } else if (activeId === 'layout-pane') {
            chartInitializers.layoutAnalysisChart();
        } else if (activeId === 'remainders-pane') {
            chartInitializers.salesPaceMetrics();
        }
    }

    // --- ПЕРЕКЛЮЧАТЕЛЬ ВАЛЮТ ---
    const currencyToggle = document.getElementById('currencyToggle');
    if (currencyToggle) {
        currencyToggle.addEventListener('change', () => {
            const isNowUsd = currencyToggle.checked;
            if (initializedCharts['planFactChart']) {
                initializedCharts['planFactChart'].destroy();
                chartInitializers.planFactChart(isNowUsd);
            }
            if (initializedCharts['priceDynamicsChart']) {
                initializedCharts['priceDynamicsChart'].destroy();
                chartInitializers.priceDynamicsChart(isNowUsd);
            }
            if (initializedCharts['layoutChart']) {
                initializedCharts['layoutChart'].destroy();
                chartInitializers.layoutAnalysisChart();
            }
        });
    }

    // --- ЛОГИКА ИСКЛЮЧЕНИЯ ОБЪЕКТОВ ИЗ ПРАЙС-ЛИСТА ---
    const pricelistForm = document.getElementById('pricelistForm');
    const excludedIdsInput = document.getElementById('excludedIdsInput');
    const selectAllCheck = document.getElementById('selectAllExclusions');
    const exclusionTable = document.getElementById('exclusionTable');

    if (pricelistForm) {
        // Собираем все отмеченные чекбоксы в скрытое поле перед отправкой формы
        pricelistForm.addEventListener('submit', function () {
            const checkedIds = Array.from(document.querySelectorAll('.exclusion-checkbox:checked'))
                .map(cb => cb.value);
            excludedIdsInput.value = checkedIds.join(',');
        });

        // Работа кнопки "Выбрать все"
        if (selectAllCheck && exclusionTable) {
            selectAllCheck.addEventListener('change', function () {
                const checkboxes = exclusionTable.querySelectorAll('.exclusion-checkbox');
                checkboxes.forEach(cb => cb.checked = selectAllCheck.checked);
            });
        }
    }
});
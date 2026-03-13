document.addEventListener('DOMContentLoaded', function() {
    if (typeof pageData === 'undefined' || !pageData) {
        console.error('Данные для инициализации скрипта не найдены.');
        return;
    }

    const usdRate = pageData.usdRate || 1;
    const performanceData = pageData.performance;
    const monthNames = pageData.monthNames;
    const i18n = pageData.i18n || {}; // Получаем переводы
    const currencySwitcher = document.getElementById('currency-switcher');

    let performanceChartIncome;

    function createOrUpdateChart(canvasId, chartInstance, planKey, factKey, isUsd) {
        const ctx = document.getElementById(canvasId)?.getContext('2d');
        if (!ctx) return chartInstance;

        if (chartInstance) {
            chartInstance.destroy();
        }

        const labels = performanceData.map(d => monthNames[d.month] || d.month);
        const planData = performanceData.map(d => isUsd ? d[planKey] / usdRate : d[planKey]);
        const factData = performanceData.map(d => isUsd ? d[factKey] / usdRate : d[factKey]);

        return new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: i18n.plan || 'План', // Используем перевод
                    data: planData,
                    backgroundColor: 'rgba(255, 193, 7, 0.4)',
                    borderColor: 'rgba(255, 193, 7, 1)',
                    borderWidth: 1
                }, {
                    label: i18n.fact || 'Факт', // Используем перевод
                    data: factData,
                    backgroundColor: 'rgba(25, 135, 84, 0.6)',
                    borderColor: 'rgba(25, 135, 84, 1)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: { y: { beginAtZero: true } }
            }
        });
    }

    function updateCurrencyDisplay(isUsd) {
        document.querySelectorAll('.money-value, .kpi-result').forEach(el => {
            const uzsValue = parseFloat(el.dataset.uzsValue);
            if (isNaN(uzsValue)) return;

            const value = isUsd ? uzsValue / usdRate : uzsValue;
            let formattedValue;

            if (isUsd) {
                formattedValue = '$ ' + value.toLocaleString('en-US', { maximumFractionDigits: 0 });
            } else {
                formattedValue = value.toLocaleString('ru-RU', { maximumFractionDigits: 0 });
            }

            el.textContent = formattedValue;
        });

        document.querySelectorAll('.currency-symbol, .table-currency-label, .chart-currency-label').forEach(el => {
            el.textContent = isUsd ? 'USD' : 'UZS';
        });
    }

    function handleCurrencyChange() {
        const isUsd = currencySwitcher.checked;
        updateCurrencyDisplay(isUsd);
        // Вы можете добавить сюда вызов для performanceChartVolume, если он нужен
        performanceChartIncome = createOrUpdateChart('performanceChartIncome', performanceChartIncome, 'plan_income', 'fact_income', isUsd);
    }

    if (currencySwitcher && usdRate > 1) {
        currencySwitcher.addEventListener('change', handleCurrencyChange);
    }

    // --- Логика для кнопок расчета KPI ---
    document.querySelectorAll('.calculate-kpi-btn').forEach(button => {
        button.addEventListener('click', function(e) {
            e.preventDefault();

            const managerId = this.dataset.managerId;
            const year = this.dataset.year;
            const month = this.dataset.month;
            const resultSpan = document.getElementById(`kpi-result-${month}`);

            resultSpan.innerHTML = `<div class="spinner-border spinner-border-sm" role="status"><span class="visually-hidden">${i18n.loading || '...'}</span></div>`;
            resultSpan.style.display = 'inline-block';
            this.disabled = true;

            fetch(`/reports/manager-kpi-calculate/${managerId}/${year}/${month}`)
                .then(response => response.ok ? response.json() : Promise.reject('Network error'))
                .then(result => {
                    if (result.success) {
                        const flooredPayment = Math.floor(result.data.payment);
                        resultSpan.dataset.uzsValue = flooredPayment; // Сохраняем для переключения валют
                        updateCurrencyDisplay(currencySwitcher.checked); // Обновляем отображение
                    } else {
                        resultSpan.textContent = i18n.error || 'Ошибка';
                    }
                })
                .catch(error => {
                    resultSpan.textContent = i18n.networkError || 'Ошибка сети';
                    console.error('Fetch error:', error);
                })
                .finally(() => {
                    this.disabled = false;
                });
        });
    });

    // Первоначальная отрисовка всех значений
    handleCurrencyChange();
});
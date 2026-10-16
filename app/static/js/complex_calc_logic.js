document.addEventListener('DOMContentLoaded', function() {
    // --- ОБЩИЕ ПЕРЕМЕННЫЕ И ФУНКЦИИ ---
    const sellIdElement = document.querySelector('h1');
    if (!sellIdElement || !sellIdElement.textContent.includes('ID:')) {
        console.error('Не удалось найти ID объекта на странице.');
        return;
    }
    const sellId = sellIdElement.textContent.split('ID:')[1].trim();

    // Хранилища для данных после успешного расчета
    let installmentCalcData = null;
    let dpInstallmentCalcData = null;
    let zeroMortgageCalcData = null;

    // Функция для форматирования объекта в строку для URL
    const formatForUrl = (obj) => JSON.stringify(obj);
    // Функция для форматирования чисел
    const formatCurrency = (value) => value.toLocaleString('ru-RU', { maximumFractionDigits: 0 });


    // --- ЛОГИКА ДЛЯ КАЛЬКУЛЯТОРА СТАНДАРТНОЙ РАССРОЧКИ ---
    const installmentForm = document.getElementById('installment-form');
    if (installmentForm) {
        installmentForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const actionUrl = this.dataset.action;
            const printBtn = document.getElementById('print-kp-installment');
            printBtn.classList.add('d-none');
            installmentCalcData = null;

            const errorDisplay = document.getElementById('error-display');
            const discountInputs = this.querySelectorAll('.discount-input');
            let additionalDiscounts = {};
            let is_valid = true;

            discountInputs.forEach(input => {
                input.classList.remove('is-invalid');
                const enteredValue = parseFloat(input.value);
                const maxValue = parseFloat(input.max);
                if (enteredValue > maxValue) {
                    is_valid = false;
                    input.classList.add('is-invalid');
                    errorDisplay.textContent = `Скидка ${input.previousElementSibling.textContent} не может превышать ${input.max}%`;
                    errorDisplay.classList.remove('d-none');
                } else if (enteredValue > 0) {
                    additionalDiscounts[input.id.replace('disc-', '')] = enteredValue / 100.0;
                }
            });

            if (!is_valid) return;
            errorDisplay.classList.add('d-none');
            ['res-price-list', 'res-discount', 'res-contract-value', 'res-monthly-payment'].forEach(id => document.getElementById(id).textContent = '...');

            fetch(actionUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sell_id: sellId,
                    term: document.getElementById('term').value,
                    start_date: document.getElementById('first_payment_date').value,
                    dp_amount: document.getElementById('dp-amount-standard').value,
                    dp_type: document.getElementById('dp-type-standard').value,
                    additional_discounts: additionalDiscounts
                })
            })
            .then(response => response.json())
            .then(result => {
                if (result.success) {
                    const data = result.data;
                    document.getElementById('res-price-list').textContent = formatCurrency(data.price_list) + ' UZS';
                    document.getElementById('res-discount').textContent = data.calculated_discount.toFixed(2) + ' %';
                    document.getElementById('res-contract-value').textContent = formatCurrency(data.calculated_contract_value) + ' UZS';
                    document.getElementById('res-monthly-payment').textContent = formatCurrency(data.monthly_payment) + ' UZS';

                    installmentCalcData = data;
                    printBtn.classList.remove('d-none');
                } else {
                    errorDisplay.textContent = result.error;
                    errorDisplay.classList.remove('d-none');
                }
            })
            .catch(err => {
                console.error("Fetch Error:", err);
                errorDisplay.textContent = 'Ошибка сети. Попробуйте позже.';
                errorDisplay.classList.remove('d-none');
            });
        });
    }


    // --- ЛОГИКА ДЛЯ КАЛЬКУЛЯТОРА РАССРОЧКИ НА ПВ ---
    const dpInstallmentForm = document.getElementById('dp-installment-form');
    if (dpInstallmentForm) {
        dpInstallmentForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const actionUrl = this.dataset.action;
            const printBtn = document.getElementById('print-kp-dp-installment');
            printBtn.classList.add('d-none');
            dpInstallmentCalcData = null;

            const errorDisplay = document.getElementById('dp-error-display');
            let is_valid = true;
            let additionalDiscounts = {};

            this.querySelectorAll('.discount-input-dp').forEach(input => {
                input.classList.remove('is-invalid');
                const enteredValue = parseFloat(input.value);
                const maxValue = parseFloat(input.max);
                if (enteredValue > maxValue) {
                    is_valid = false;
                    input.classList.add('is-invalid');
                    errorDisplay.textContent = `Скидка ${input.previousElementSibling.textContent} не может превышать ${input.max}%`;
                    errorDisplay.classList.remove('d-none');
                } else if (enteredValue > 0) {
                    additionalDiscounts[input.id.replace('dp-disc-', '')] = enteredValue / 100.0;
                }
            });

            if (!is_valid) return;
            errorDisplay.classList.add('d-none');
            ['dp-res-term', 'dp-res-monthly', 'dp-res-mortgage', 'dp-res-contract'].forEach(id => document.getElementById(id).textContent = '...');

            const mortgageType = document.querySelector('input[name="mortgage_type"]:checked').value;

            fetch(actionUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sell_id: sellId,
                    term: document.getElementById('dp-term').value,
                    dp_amount: document.getElementById('dp-amount').value,
                    dp_type: document.getElementById('dp-type').value,
                    start_date: document.getElementById('dp_first_payment_date').value,
                    additional_discounts: additionalDiscounts,
                    mortgage_type: mortgageType
                })
            })
            .then(response => response.json())
            .then(result => {
                if (result.success) {
                    const data = result.data;
                    document.getElementById('dp-res-term').textContent = data.term_months + ' мес.';
                    document.getElementById('dp-res-monthly').textContent = formatCurrency(data.monthly_payment_for_dp) + ' UZS';
                    document.getElementById('dp-res-mortgage').textContent = formatCurrency(data.mortgage_body) + ' UZS';
                    document.getElementById('dp-res-contract').textContent = formatCurrency(data.calculated_contract_value) + ' UZS';

                    dpInstallmentCalcData = data;
                    printBtn.classList.remove('d-none');
                } else {
                    errorDisplay.textContent = result.error;
                    errorDisplay.classList.remove('d-none');
                }
            })
            .catch(err => {
                console.error("Fetch Error:", err);
                errorDisplay.textContent = 'Ошибка сети. Попробуйте позже.';
                errorDisplay.classList.remove('d-none');
            });
        });
    }

    // --- ЛОГИКА ДЛЯ ИПОТЕКИ ПОД 0% ---
    const zeroMortgageForm = document.getElementById('zero-mortgage-form');
    if(zeroMortgageForm) {
        zeroMortgageForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const actionUrl = this.dataset.action;
            const errorDisplay = document.getElementById('zero-mortgage-error-display');
            const printBtn = document.getElementById('print-kp-zero-mortgage');
            printBtn.classList.add('d-none');
            zeroMortgageCalcData = null;
            errorDisplay.classList.add('d-none');

            const discountInputs = this.querySelectorAll('.discount-input-zero-mortgage');
            let additionalDiscounts = {};
            let is_valid = true;

            discountInputs.forEach(input => {
                input.classList.remove('is-invalid');
                const enteredValue = parseFloat(input.value);
                const maxValue = parseFloat(input.max);
                if (enteredValue > maxValue) {
                    is_valid = false;
                    input.classList.add('is-invalid');
                    errorDisplay.textContent = `Скидка ${input.previousElementSibling.textContent} не может превышать ${input.max}%`;
                    errorDisplay.classList.remove('d-none');
                } else if (enteredValue > 0) {
                    additionalDiscounts[input.id.replace('zero-mortgage-disc-', '')] = enteredValue / 100.0;
                }
            });

            if (!is_valid) return;

            ['zero-mortgage-res-contract', 'zero-mortgage-res-dp', 'zero-mortgage-res-monthly'].forEach(id => document.getElementById(id).textContent = '...');

            // --- ИЗМЕНЕНИЕ: Получаем значение типа ипотеки ---
            const mortgageType = document.querySelector('input[name="zero_mortgage_type"]:checked').value;

            fetch(actionUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sell_id: sellId,
                    term_months: document.getElementById('zero-mortgage-term').value,
                    dp_percent: document.getElementById('zero-mortgage-dp').value,
                    additional_discounts: additionalDiscounts,
                    mortgage_type: mortgageType // <-- ИЗМЕНЕНИЕ: Добавляем тип ипотеки в запрос
                })
            })
            .then(response => response.json())
            .then(result => {
                if(result.success) {
                    const data = result.data;
                    document.getElementById('zero-mortgage-res-contract').textContent = formatCurrency(data.contract_value) + ' UZS';
                    document.getElementById('zero-mortgage-res-dp').textContent = formatCurrency(data.initial_payment) + ' UZS';
                    document.getElementById('zero-mortgage-res-monthly').textContent = formatCurrency(data.monthly_payment) + ' UZS';

                    zeroMortgageCalcData = data;
                    printBtn.classList.remove('d-none');

                } else {
                    errorDisplay.textContent = result.error;
                    errorDisplay.classList.remove('d-none');
                }
            })
            .catch(err => {
                console.error("Fetch Error:", err);
                errorDisplay.textContent = 'Ошибка сети. Попробуйте позже.';
                errorDisplay.classList.remove('d-none');
            });
        });
    }

    // --- ОБРАБОТЧИКИ КНОПОК ПЕЧАТИ ---
    const printKpInstallmentBtn = document.getElementById('print-kp-installment');
    if(printKpInstallmentBtn) {
        printKpInstallmentBtn.addEventListener('click', function() {
            if (installmentCalcData) {
                const queryParams = new URLSearchParams({
                    calc_type: 'standard_installment',
                    details: formatForUrl(installmentCalcData)
                });
                window.open(`${window.APP_PREFIX}/reports/commercial-offer/complex/${sellId}?${queryParams.toString()}`, '_blank');
            }
        });
    }


    // --- РАССРОЧКА ПО СЕТКЕ «ПВ x СРОК» ---
    const matrixForm = document.getElementById('matrix-installment-form');
    if (matrixForm) {
        const dpByTerm = JSON.parse(matrixForm.dataset.dpByTerm || '{}');
        const costPercent = JSON.parse(matrixForm.dataset.costPercent || '{}');
        const termSelect = document.getElementById('matrix-term');
        const dpSelect = document.getElementById('matrix-dp');
        const costHint = document.getElementById('matrix-cost-hint');
        const errorBox = document.getElementById('matrix-installment-error-display');

        // В сетке заполнены не все пары, поэтому список взносов зависит от
        // выбранного срока и перестраивается при его смене.
        function fillDpOptions() {
            const options = dpByTerm[termSelect.value] || [];
            dpSelect.innerHTML = '';
            options.forEach(function (dp) {
                const option = document.createElement('option');
                option.value = dp;
                option.textContent = dp + '%';
                dpSelect.appendChild(option);
            });
            showCost();
        }

        function showCost() {
            const cost = costPercent[dpSelect.value + ':' + termSelect.value];
            costHint.textContent = cost === undefined
                ? ''
                : 'Рассрочка на этих условиях стоит ' + cost + '% скидки';
        }

        termSelect.addEventListener('change', fillDpOptions);
        dpSelect.addEventListener('change', showCost);
        fillDpOptions();

        matrixForm.addEventListener('submit', function (e) {
            e.preventDefault();
            errorBox.classList.add('d-none');

            fetch(matrixForm.dataset.action, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    sell_id: sellId,
                    term: termSelect.value,
                    dp_percent: dpSelect.value,
                    with_opt: document.getElementById('matrix-opt').checked,
                    with_referral: document.getElementById('matrix-referral').checked
                })
            })
            .then(function (r) { return r.json(); })
            .then(function (payload) {
                if (!payload.success) {
                    errorBox.textContent = payload.error;
                    errorBox.classList.remove('d-none');
                    return;
                }
                const data = payload.data;
                const parts = (data.base_discount_parts || [])
                    .map(function (p) { return p.name + ' ' + p.percent + '%'; }).join(' + ');

                document.getElementById('matrix-res-base').textContent =
                    data.base_discount_percent + '%' + (parts ? ' (' + parts + ')' : '');
                document.getElementById('matrix-res-cost').textContent = '- ' + data.plan_cost_percent + '%';
                document.getElementById('matrix-res-available').textContent = data.available_discount_percent + '%';
                document.getElementById('matrix-res-dp').textContent = formatCurrency(data.initial_payment) + ' UZS';
                document.getElementById('matrix-res-remainder').textContent = formatCurrency(data.remainder) + ' UZS';
                document.getElementById('matrix-res-monthly').textContent = formatCurrency(data.monthly_payment) + ' UZS';
                document.getElementById('matrix-res-sqm').textContent =
                    data.price_per_sqm ? formatCurrency(data.price_per_sqm) + ' UZS' : '—';
                document.getElementById('matrix-res-deal').textContent = formatCurrency(data.deal_price) + ' UZS';
            })
            .catch(function () {
                errorBox.textContent = 'Не удалось выполнить расчёт.';
                errorBox.classList.remove('d-none');
            });
        });
    }

    const printKpDpInstallmentBtn = document.getElementById('print-kp-dp-installment');
    if(printKpDpInstallmentBtn) {
        printKpDpInstallmentBtn.addEventListener('click', function() {
            if (dpInstallmentCalcData) {
                const queryParams = new URLSearchParams({
                    calc_type: 'dp_installment',
                    details: formatForUrl(dpInstallmentCalcData)
                });
                window.open(`${window.APP_PREFIX}/reports/commercial-offer/complex/${sellId}?${queryParams.toString()}`, '_blank');
            }
        });
    }

    const printKpZeroMortgageBtn = document.getElementById('print-kp-zero-mortgage');
    if(printKpZeroMortgageBtn) {
        printKpZeroMortgageBtn.addEventListener('click', function() {
            if (zeroMortgageCalcData) {
                const queryParams = new URLSearchParams({
                    calc_type: 'zero_mortgage',
                    details: formatForUrl(zeroMortgageCalcData)
                });
                window.open(`${window.APP_PREFIX}/reports/commercial-offer/complex/${sellId}?${queryParams.toString()}`, '_blank');
            }
        });
    }
});
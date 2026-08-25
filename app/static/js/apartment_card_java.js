// Пересчёт карточки объекта при движении ползунков скидок.
// Формула повторяет app/services/pricing_service.py: проценты складываются
// и применяются к цене после вычета. Любое расхождение здесь означает, что
// экран и КП покажут разные суммы, поэтому менять её нужно в обоих местах.
document.addEventListener('DOMContentLoaded', function () {

    if (typeof cardData === 'undefined' || cardData === null) {
        console.error('Данные о квартире (cardData) не были переданы из шаблона!');
        return;
    }

    const mortgageTerms = cardData.mortgageTerms || {};
    const MAX_MORTGAGE_BODY = mortgageTerms.body || 0;
    const MIN_INITIAL_PAYMENT_PERCENT = mortgageTerms.min_initial_payment_percent || 0;

    // {type_key: {код скидки: процент}} — то, что менеджер выставил ползунками.
    const manualDiscounts = {};
    // Взнос, поднятый менеджером вручную. null — считаем по минимуму.
    let manualInitialPayment = null;

    function formatCurrency(value) {
        return value.toLocaleString('ru-RU', {minimumFractionDigits: 0, maximumFractionDigits: 0});
    }

    // Ползунок и поле ввода — две ручки одного значения, поэтому при правке
    // одной подтягиваем вторую. Число обрезаем по максимуму из матрицы скидок:
    // ввести больше разрешённого нельзя ни ползунком, ни руками.
    function syncDiscountPair(card, code, percent, source) {
        card.querySelectorAll('[data-discount-code="' + code + '"]').forEach(function (el) {
            if (el === source || el.tagName !== 'INPUT') return;
            el.value = percent;
        });
    }

    function readManualPercents(card) {
        const percents = {};
        card.querySelectorAll('.manual-discount-input').forEach(function (input) {
            const max = parseInt(input.max, 10) || 0;
            let percent = parseInt(input.value, 10) || 0;
            percent = Math.min(Math.max(percent, 0), max);
            if (String(percent) !== input.value) input.value = percent;
            if (percent > 0) percents[input.dataset.discountCode] = percent;
        });
        return percents;
    }

    function updateCard(card) {
        const typeKey = card.dataset.typeKey;
        const priceAfterDeduction = parseFloat(card.dataset.basePriceDeducted) || 0;

        const manualPercents = readManualPercents(card);
        manualDiscounts[typeKey] = manualPercents;

        let totalPercent = 0;
        card.querySelectorAll('.manual-discount-row').forEach(function (row) {
            const percent = manualPercents[row.dataset.discountCode] || 0;
            if (percent > 0) {
                row.classList.remove('d-none');
                row.querySelector('.manual-discount-percent').textContent = percent;
                row.querySelector('.manual-discount-amount').textContent =
                    formatCurrency(priceAfterDeduction * percent / 100);
                totalPercent += percent;
            } else {
                row.classList.add('d-none');
            }
        });

        const discountAmount = priceAfterDeduction * totalPercent / 100;
        const priceAfterDiscounts = priceAfterDeduction - discountAmount;

        card.querySelector('.benefit-percent').textContent = totalPercent;
        card.querySelector('.benefit-amount').textContent = '- ' + formatCurrency(discountAmount);

        const initialPaymentInput = card.querySelector('.initial-payment-input');
        if (initialPaymentInput) {
            // Минимум — 15% от стоимости сделки; всё сверх лимита банка тоже
            // ложится на взнос. Скидки меняют цену, значит и минимум плавает:
            // пересчитываем его и подтягиваем взнос, если он ушёл ниже.
            const minInitialPayment = Math.max(
                priceAfterDiscounts - MAX_MORTGAGE_BODY,
                priceAfterDiscounts * MIN_INITIAL_PAYMENT_PERCENT
            );

            let initialPayment = manualInitialPayment;
            if (initialPayment === null || initialPayment < minInitialPayment) {
                initialPayment = minInitialPayment;
            }
            initialPayment = Math.min(initialPayment, priceAfterDiscounts);

            initialPaymentInput.min = Math.ceil(minInitialPayment);
            initialPaymentInput.dataset.minInitial = minInitialPayment;
            if (document.activeElement !== initialPaymentInput) {
                initialPaymentInput.value = Math.round(initialPayment);
            }

            const minLabel = card.querySelector('.min-initial-payment');
            if (minLabel) minLabel.textContent = formatCurrency(minInitialPayment) + ' UZS';

            const mortgageBodyEl = card.querySelector('.mortgage-body');
            if (mortgageBodyEl) {
                mortgageBodyEl.textContent =
                    formatCurrency(priceAfterDiscounts - initialPayment) + ' UZS';
            }
        }

        card.querySelector('.price-final').textContent =
            formatCurrency(priceAfterDiscounts) + ' UZS';

        updateOfferLink();
    }

    // Ссылка на КП всегда актуальна: скидки дописываются в адрес сразу, чтобы
    // переход работал и обычным кликом, и открытием в новой вкладке.
    const offerLink = document.getElementById('openKpBtn');
    const offerBaseUrl = offerLink ? offerLink.getAttribute('href').split('?')[0] : null;

    function updateOfferLink() {
        if (!offerLink) return;

        const selections = {};
        for (const typeKey in manualDiscounts) {
            if (Object.keys(manualDiscounts[typeKey]).length > 0) {
                selections[typeKey] = manualDiscounts[typeKey];
            }
        }

        const params = new URLSearchParams();
        if (Object.keys(selections).length > 0) {
            params.set('selections', JSON.stringify(selections));
        }
        // Взнос по минимуму КП посчитает сам — в адрес пишем только поднятый.
        const raised = document.querySelector('.initial-payment-input');
        if (raised && manualInitialPayment !== null) {
            const min = parseFloat(raised.dataset.minInitial) || 0;
            if (manualInitialPayment > min) {
                params.set('initial_payment', Math.round(manualInitialPayment));
            }
        }

        const query = params.toString();
        offerLink.setAttribute('href', query ? offerBaseUrl + '?' + query : offerBaseUrl);
    }

    document.querySelectorAll('.payment-option-card').forEach(function (card) {
        card.querySelectorAll('.manual-discount-input, .manual-discount-number').forEach(function (input) {
            const handler = function () {
                const max = parseInt(input.max, 10) || 0;
                let percent = parseInt(input.value, 10);
                if (isNaN(percent)) percent = 0;
                percent = Math.min(Math.max(percent, 0), max);
                syncDiscountPair(card, input.dataset.discountCode, percent, input);
                updateCard(card);
            };
            input.addEventListener('input', handler);
            input.addEventListener('change', handler);
        });

        const initialPaymentInput = card.querySelector('.initial-payment-input');
        if (initialPaymentInput) {
            initialPaymentInput.addEventListener('input', function () {
                const value = parseFloat(initialPaymentInput.value);
                manualInitialPayment = isNaN(value) ? null : value;
                updateCard(card);
            });
            // Проверку минимума делаем на blur: пока менеджер набирает сумму,
            // промежуточные цифры почти всегда меньше минимума, и подтягивать
            // поле под курсором — значит мешать вводу.
            initialPaymentInput.addEventListener('change', function () {
                const min = parseFloat(initialPaymentInput.dataset.minInitial) || 0;
                const value = parseFloat(initialPaymentInput.value);
                if (isNaN(value) || value < min) {
                    manualInitialPayment = null;
                    initialPaymentInput.value = Math.ceil(min);
                } else {
                    manualInitialPayment = value;
                }
                updateCard(card);
            });
        }

        updateCard(card);
    });
});

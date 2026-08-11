// Пересчёт карточки объекта при ручном вводе скидок менеджером.
// Формула повторяет app/services/pricing_service.py: проценты складываются
// и применяются к цене после вычета. Любое расхождение здесь означает, что
// экран и КП покажут разные суммы, поэтому менять её нужно в обоих местах.
document.addEventListener('DOMContentLoaded', function () {

    if (typeof cardData === 'undefined' || cardData === null) {
        console.error('Данные о квартире (cardData) не были переданы из шаблона!');
        return;
    }

    const mortgageTerms = cardData.mortgageTerms || {};
    const MORTGAGE_BODY = mortgageTerms.body || 0;
    const MIN_INITIAL_PAYMENT_PERCENT = mortgageTerms.min_initial_payment_percent || 0;

    // {type_key: {код скидки: процент}} — то, что менеджер выставил руками.
    const manualDiscounts = {};

    function formatCurrency(value) {
        return value.toLocaleString('ru-RU', {minimumFractionDigits: 0, maximumFractionDigits: 0});
    }

    function readManualPercents(card) {
        const percents = {};
        card.querySelectorAll('.manual-discount-input').forEach(input => {
            const max = parseFloat(input.max) || 0;
            let percent = parseFloat(input.value);
            if (isNaN(percent) || percent < 0) percent = 0;
            // Больше максимума из матрицы выдать нельзя — правим и само поле,
            // чтобы менеджер видел, что значение обрезано.
            if (percent > max) {
                percent = max;
                input.value = max;
            }
            if (percent > 0) percents[input.dataset.discountCode] = percent;
        });
        return percents;
    }

    function updateCard(card) {
        const typeKey = card.dataset.typeKey;
        const priceAfterDeduction = parseFloat(card.dataset.basePriceDeducted) || 0;
        const basePercent = parseFloat(card.dataset.baseDiscountPercent) || 0;

        const manualPercents = readManualPercents(card);
        manualDiscounts[typeKey] = manualPercents;

        let manualPercentTotal = 0;
        card.querySelectorAll('.manual-discount-row').forEach(row => {
            const percent = manualPercents[row.dataset.discountCode] || 0;
            if (percent > 0) {
                row.classList.remove('d-none');
                row.querySelector('.manual-discount-percent').textContent = percent.toFixed(1);
                row.querySelector('.manual-discount-amount').textContent =
                    formatCurrency(priceAfterDeduction * percent / 100);
                manualPercentTotal += percent;
            } else {
                row.classList.add('d-none');
            }
        });

        const totalPercent = basePercent + manualPercentTotal;
        const discountAmount = priceAfterDeduction * totalPercent / 100;
        const priceAfterDiscounts = priceAfterDeduction - discountAmount;

        card.querySelector('.benefit-percent').textContent = totalPercent.toFixed(1);
        card.querySelector('.benefit-amount').textContent = '- ' + formatCurrency(discountAmount);

        const initialPaymentEl = card.querySelector('.price-initial');
        let finalPrice = priceAfterDiscounts;

        if (initialPaymentEl) {
            const initialPayment = Math.max(
                priceAfterDiscounts - MORTGAGE_BODY,
                priceAfterDiscounts * MIN_INITIAL_PAYMENT_PERCENT
            );
            finalPrice = initialPayment + MORTGAGE_BODY;
            initialPaymentEl.textContent = formatCurrency(initialPayment) + ' UZS';
        }

        card.querySelector('.price-final').textContent = formatCurrency(finalPrice) + ' UZS';
    }

    const cards = document.querySelectorAll('.payment-option-card');
    cards.forEach(card => {
        card.querySelectorAll('.manual-discount-input').forEach(input => {
            input.addEventListener('input', () => updateCard(card));
            input.addEventListener('change', () => updateCard(card));
        });
        updateCard(card);
    });

    // КП открывается одной кнопкой: выбранные скидки уезжают в адрес,
    // сервер пересчитывает их той же функцией и сразу отдаёт готовый документ.
    const openKpBtn = document.getElementById('openKpBtn');
    if (openKpBtn) {
        openKpBtn.addEventListener('click', function () {
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

            const query = params.toString();
            const sellId = cardData.apartment.id;
            window.open(
                `${window.APP_PREFIX}/commercial-offer/${sellId}${query ? '?' + query : ''}`,
                '_blank'
            );
        });
    }
});

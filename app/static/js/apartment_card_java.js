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

    function formatCurrency(value) {
        return value.toLocaleString('ru-RU', {minimumFractionDigits: 0, maximumFractionDigits: 0});
    }

    function readManualPercents(card) {
        const percents = {};
        card.querySelectorAll('.manual-discount-input').forEach(input => {
            const percent = parseInt(input.value, 10) || 0;
            const label = input.closest('.col-6');
            const valueLabel = label && label.querySelector('.manual-discount-value');
            if (valueLabel) valueLabel.textContent = percent;
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
        card.querySelectorAll('.manual-discount-row').forEach(row => {
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

        const initialPaymentEl = card.querySelector('.price-initial');
        if (initialPaymentEl) {
            // Первый взнос — минимум 15% от стоимости сделки; всё сверх лимита
            // банка тоже ложится на взнос. Остаток и есть тело кредита.
            const initialPayment = Math.max(
                priceAfterDiscounts - MAX_MORTGAGE_BODY,
                priceAfterDiscounts * MIN_INITIAL_PAYMENT_PERCENT
            );
            initialPaymentEl.textContent = formatCurrency(initialPayment) + ' UZS';

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

        if (Object.keys(selections).length === 0) {
            offerLink.setAttribute('href', offerBaseUrl);
            return;
        }

        const params = new URLSearchParams({selections: JSON.stringify(selections)});
        offerLink.setAttribute('href', `${offerBaseUrl}?${params.toString()}`);
    }

    document.querySelectorAll('.payment-option-card').forEach(card => {
        card.querySelectorAll('.manual-discount-input').forEach(input => {
            input.addEventListener('input', () => updateCard(card));
            input.addEventListener('change', () => updateCard(card));
        });
        updateCard(card);
    });
});

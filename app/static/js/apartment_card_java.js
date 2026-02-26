// dieforglory/apartment_finder/apartment_finder-f37e02bf8a9dc8b95aa12dfb12abacef7b6edc2c/app/static/js/apartment_card_java.js
document.addEventListener('DOMContentLoaded', function() {

    if (typeof cardData === 'undefined' || cardData === null) {
        console.error('Данные о квартире (cardData) не были переданы из шаблона!');
        return;
    }

    const pricingData = cardData.pricing || [];
    const allDiscountsForPropertyType = cardData.all_discounts_for_property_type || [];
    const apartmentData = cardData.apartment || {};
    // --- ИЗМЕНЕНИЕ 1: Получаем объект с переводами ---
    const i18n = cardData.i18n || {};


    const appliedAdditionalDiscounts = {};
    pricingData.forEach(option => {
        appliedAdditionalDiscounts[option.type_key] = {
            details: { kd: 0.0, opt: 0.0, gd: 0.0, holding: 0.0, shareholder: 0.0, action: 0.0 }
        };
    });

    function formatCurrency(value) {
        return value.toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
    }

    function calculateFinalPrice(basePriceDeducted, initialStaticDiscountRate, typeKey) {
        let totalDiscountRate = initialStaticDiscountRate;

        if (appliedAdditionalDiscounts[typeKey]) {
            for (const type in appliedAdditionalDiscounts[typeKey].details) {
                totalDiscountRate += appliedAdditionalDiscounts[typeKey].details[type];
            }
        }

        let priceAfterAllDiscounts = basePriceDeducted * (1 - (totalDiscountRate / 100));

        if (typeKey.includes('mortgage')) {
            const MAX_MORTGAGE = 420000000;
            const MIN_INITIAL_PAYMENT_PERCENT = 0.15;
            let initialPayment = priceAfterAllDiscounts - MAX_MORTGAGE;
            let minRequiredPayment = priceAfterAllDiscounts * MIN_INITIAL_PAYMENT_PERCENT;

            if (initialPayment < 0) initialPayment = 0;
            if (initialPayment < minRequiredPayment) initialPayment = minRequiredPayment;

            const finalPrice = initialPayment + MAX_MORTGAGE;
            return { finalPrice: finalPrice, initialPayment: initialPayment };
        }
        return { finalPrice: priceAfterAllDiscounts, initialPayment: null };
    }

    function updateOptionUI(optionElement) {
        const typeKey = optionElement.dataset.typeKey;
        const basePriceDeducted = parseFloat(optionElement.dataset.basePriceDeducted);

        let initialStaticDiscountRate = 0;
        optionElement.querySelectorAll('.static-discount-percent').forEach(span => {
            initialStaticDiscountRate += parseFloat(span.textContent);
        });

        const calculatedPrices = calculateFinalPrice(basePriceDeducted, initialStaticDiscountRate, typeKey);

        const finalPriceSpan = optionElement.querySelector('.price-final');
        const initialPaymentSpan = optionElement.querySelector('.price-initial');

        if (typeKey === 'easy_start_100') {
            finalPriceSpan.innerHTML = formatCurrency(calculatedPrices.finalPrice / 3) + ' UZS / мес.';
            const totalSumSpan = optionElement.querySelector('.total-sum');
            if(totalSumSpan) totalSumSpan.textContent = formatCurrency(calculatedPrices.finalPrice);
        } else if (typeKey.includes('easy_start_mortgage')) {
            if (initialPaymentSpan) initialPaymentSpan.textContent = formatCurrency(calculatedPrices.initialPayment / 3) + ' UZS / мес.';
            finalPriceSpan.textContent = formatCurrency(calculatedPrices.finalPrice) + ' UZS';
        } else {
            finalPriceSpan.textContent = formatCurrency(calculatedPrices.finalPrice) + ' UZS';
            if (initialPaymentSpan) {
                if (calculatedPrices.initialPayment !== null && calculatedPrices.initialPayment >= 0) {
                    initialPaymentSpan.textContent = formatCurrency(calculatedPrices.initialPayment) + ' UZS';
                } else {
                    initialPaymentSpan.textContent = '— UZS';
                }
            }
        }

        const currentAppliedDetails = appliedAdditionalDiscounts[typeKey] ? appliedAdditionalDiscounts[typeKey].details : {};
        let anyAdditionalDiscountApplied = false;
        let totalAppliedPercent = 0;

        optionElement.querySelectorAll('.additional-discount-row').forEach(row => {
            const discountType = row.dataset.discountType;
            const appliedValue = currentAppliedDetails[discountType] || 0;
            if (appliedValue > 0) {
                row.classList.remove('d-none');
                row.querySelector('.applied-discount-percent').textContent = appliedValue.toFixed(1);
                const discountAmount = basePriceDeducted * (appliedValue / 100);
                row.querySelector('.applied-discount-amount').textContent = '- ' + formatCurrency(discountAmount);
                anyAdditionalDiscountApplied = true;
                totalAppliedPercent += appliedValue;
            } else {
                row.classList.add('d-none');
            }
        });

        const toggleButton = optionElement.querySelector('.btn-additional-discounts-toggle');
        // --- ИЗМЕНЕНИЕ 2: Используем переводы для текста кнопки ---
        if (anyAdditionalDiscountApplied) {
            toggleButton.classList.add('active');
            toggleButton.innerHTML = `<i class="bi bi-check-circle-fill me-1"></i> ${i18n.appliedDiscounts || 'Доп. скидки'} (${totalAppliedPercent.toFixed(1)}%)`;
        } else {
            toggleButton.classList.remove('active');
            toggleButton.innerHTML = `<i class="bi bi-percent me-1"></i> ${i18n.applyDiscounts || 'Применить доп. скидки'}`;
        }
    }

    document.querySelectorAll('.additional-discount-item').forEach(item => {
        item.addEventListener('click', function(e) {
            e.preventDefault();
            const discountType = this.dataset.discountType;
            const maxPercent = parseFloat(this.dataset.maxPercent);

            const paymentOptionCard = this.closest('.payment-option-card');
            const typeKey = paymentOptionCard.dataset.typeKey;

            // Используем in для проверки наличия свойства, а не его значения
            if (appliedAdditionalDiscounts[typeKey].details[discountType] > 0) {
                // Если да, отключаем ее, устанавливая значение в 0
                appliedAdditionalDiscounts[typeKey].details[discountType] = 0.0;
                this.classList.remove('active');
            } else {
                // Если нет, включаем, присваивая максимальное значение
                appliedAdditionalDiscounts[typeKey].details[discountType] = maxPercent;
                this.classList.add('active');
            }

            updateOptionUI(paymentOptionCard);
        });
    });

    document.querySelectorAll('.payment-option-card').forEach(card => updateOptionUI(card));

    // --- ИЗМЕНЕНИЕ: Новый обработчик для кнопок в модальном окне ---
     const printModal = document.getElementById('printChoiceModal');
    if (printModal) {
        const printModalInstance = new bootstrap.Modal(printModal);

        document.querySelectorAll('.print-variant-btn').forEach(button => {
            button.addEventListener('click', function() {
                // ИСПРАВЛЕНИЕ: Получаем ID из объекта cardData, который теперь содержит apartment
                const sellId = cardData.apartment.id;
                const mortgageType = this.dataset.mortgageType;

                const selectionsForUrl = {};
                for (const typeKey in appliedAdditionalDiscounts) {
                    const applied = {};
                    for (const discountName in appliedAdditionalDiscounts[typeKey].details) {
                        const value = appliedAdditionalDiscounts[typeKey].details[discountName];
                        if (value > 0) {
                            applied[discountName] = value;
                        }
                    }
                    if (Object.keys(applied).length > 0) {
                        selectionsForUrl[typeKey] = applied;
                    }
                }

                const selectionsJson = JSON.stringify(selectionsForUrl);
                const queryParams = new URLSearchParams({
                    selections: selectionsJson,
                    mortgage_type_to_print: mortgageType
                });

                const printUrl = `/commercial-offer/${sellId}?${queryParams.toString()}`;
                window.open(printUrl, '_blank');
                printModalInstance.hide();
            });
        });
    }
});
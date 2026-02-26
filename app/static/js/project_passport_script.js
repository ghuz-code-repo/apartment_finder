// JS для переключателя валют
document.addEventListener('DOMContentLoaded', function () {
    const container = document.getElementById('passport-form-container');
    if (!container) return;

    // --- ЛОГИКА ПЕРЕКЛЮЧАТЕЛЯ ВАЛЮТ ---
    // Читаем данные из document.body, которые установил inline-script
    const usdRate = parseFloat(document.body.dataset.usdRate) || 13050;
    const currencyToggle = document.getElementById('currencyToggle');
    const currencyLabel = document.getElementById('currencyLabel');

    function updateCurrency() {
        const isUsd = currencyToggle.checked;

        if (currencyLabel) {
            currencyLabel.textContent = isUsd ? 'USD' : 'UZS';
        }

        document.querySelectorAll('.currency-value').forEach(el => {
            const uzsValue = parseFloat(el.dataset.uzsValue);
            if (isNaN(uzsValue)) return;

            let displayValue;
            let originalText = el.textContent || "";
            let suffix = originalText.includes("UZS/м²") ? " USD/м²" : (originalText.includes("UZS") ? " USD" : "");

            if (isUsd) {
                displayValue = '$ ' + (uzsValue / usdRate).toLocaleString('ru-RU', { maximumFractionDigits: 0 });
                if(suffix) displayValue = displayValue.replace(" USD", suffix);
            } else {
                displayValue = uzsValue.toLocaleString('ru-RU', { maximumFractionDigits: 0 });
                if(suffix) displayValue += suffix.replace("USD", "UZS");
                else displayValue += " UZS";
            }
            el.textContent = displayValue;
        });
    }

    if (currencyToggle) {
        currencyToggle.addEventListener('change', updateCurrency);
        // Инициализация при загрузке
        updateCurrency();
    }

    // --- ЛОГИКА РЕДАКТИРОВАНИЯ ПАСПОРТА ---
    const editBtn = document.getElementById('edit-btn');
    const saveBtn = document.getElementById('save-btn');
    const cancelBtn = document.getElementById('cancel-btn');

    const editableFields = [
        'construction_type', 'address_link', 'heating_type',
        'finishing_type', 'start_date', 'current_stage',
        'project_manager', 'chief_engineer', 'sales_manager',
        'planned_sales_pace'
    ];

    // Читаем данные из window, которые установил inline-script
    const initialData = window.passportInitialData || {};
    // Читаем переводы
    const i18n = window.passportTranslations || {};

    function toggleEditMode(isEditing) {
        if (isEditing) {
            container.classList.add('editing');
            editBtn.style.display = 'none';
            saveBtn.style.display = 'block';
            cancelBtn.style.display = 'block';
        } else {
            container.classList.remove('editing');
            editBtn.style.display = 'block';
            saveBtn.style.display = 'none';
            cancelBtn.style.display = 'none';
        }
    }

    if (editBtn) {
        editBtn.addEventListener('click', function () {
            toggleEditMode(true);
        });
    }

    if (cancelBtn) {
        cancelBtn.addEventListener('click', function () {
            editableFields.forEach(fieldId => {
                const input = document.getElementById(fieldId);
                if (input) {
                    input.value = initialData[fieldId] || (fieldId === 'planned_sales_pace' ? '' : '');
                }
            });
            toggleEditMode(false);
        });
    }

    if (saveBtn) {
        saveBtn.addEventListener('click', function () {
            const payload = {
                complex_name: container.dataset.complexName
            };

            editableFields.forEach(fieldId => {
                const input = document.getElementById(fieldId);
                if (input) {
                    if (fieldId === 'planned_sales_pace') {
                        payload[fieldId] = input.value ? parseFloat(input.value) : null;
                    } else {
                        payload[fieldId] = input.value;
                    }
                }
            });

            saveBtn.disabled = true;
            // Используем перевод
            saveBtn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> ${i18n.saving || 'Сохранение...'}`;

            fetch('/api/v1/passport/save', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload)
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    editableFields.forEach(fieldId => {
                        const input = document.getElementById(fieldId);
                        const viewEl = document.querySelector(`.passport-value-view[data-field="${fieldId}"]`);

                        if (input && viewEl) {
                            const newValue = input.value;
                            initialData[fieldId] = (fieldId === 'planned_sales_pace') ? (newValue ? parseFloat(newValue) : null) : newValue;

                            if (fieldId === 'address_link') {
                                viewEl.innerHTML = newValue ? `<a href="${newValue}" target="_blank">${newValue}</a>` : '...';
                            } else {
                                viewEl.textContent = newValue || '...';
                            }
                        }
                    });
                    toggleEditMode(false);
                } else {
                    alert('Ошибка сохранения: ' + data.error);
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('Произошла сетевая ошибка.');
            })
            .finally(() => {
                saveBtn.disabled = false;
                // Используем перевод
                saveBtn.innerHTML = `<i class="bi bi-save me-2"></i> ${i18n.save || 'Сохранить'}`;
            });
        });
    }

    // =============================================
    //          КОД ДЛЯ ЭТАПОВ СТРОИТЕЛЬСТВА
    // =============================================
    const complexName = container.dataset.complexName;
    const addStageForm = document.getElementById('add-stage-form');
    const stagesTbody = document.getElementById('stages-tbody');

    // --- 1. Добавление нового этапа ---
    if (addStageForm) {
        addStageForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const stageNameInput = document.getElementById('new-stage-name');
            const startDateInput = document.getElementById('new-stage-start-date');
            const plannedEndDateInput = document.getElementById('new-stage-planned-end-date');

            const payload = {
                complex_name: complexName,
                stage_name: stageNameInput.value,
                start_date: startDateInput.value || null,
                planned_end_date: plannedEndDateInput.value || null
            };

            fetch('/api/v1/passport/stages/add', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    // Динамически добавляем новую строку в таблицу
                    appendStageRow(data.stage);
                    // Очищаем форму
                    stageNameInput.value = '';
                    startDateInput.value = '';
                    plannedEndDateInput.value = '';
                } else {
                    alert('Ошибка добавления этапа: ' + data.error);
                }
            });
        });
    }

    // --- 2. Управление (Сохранение/Удаление) существующими этапами ---
    if (stagesTbody) {
        stagesTbody.addEventListener('click', function(e) {
            const saveBtn = e.target.closest('.save-stage-btn');
            const deleteBtn = e.target.closest('.delete-stage-btn');

            if (saveBtn) {
                handleUpdateStage(saveBtn);
            }
            if (deleteBtn) {
                handleDeleteStage(deleteBtn);
            }
        });
    }

    function handleUpdateStage(button) {
        const row = button.closest('tr');
        const stageId = row.dataset.stageId;

        const payload = {
            stage_name: row.querySelector('.stage-name-input').value,
            start_date: row.querySelector('.stage-start-date-input').value || null,
            planned_end_date: row.querySelector('.stage-planned-end-date-input').value || null,
            actual_end_date: row.querySelector('.stage-actual-end-date-input').value || null
        };

        button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span>';

        fetch(`/api/v1/passport/stages/update/${stageId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                // Обновляем "view" спаны
                updateRowViews(row, data.stage);
            } else {
                alert('Ошибка обновления: ' + data.error);
            }
        })
        .finally(() => {
            button.innerHTML = '<i class="bi bi-check-lg"></i>';
        });
    }

    function handleDeleteStage(button) {
        const row = button.closest('tr');
        const stageId = row.dataset.stageId;

        // Используем перевод
        if (confirm(i18n.confirmDelete || 'Вы уверены, что хотите удалить этот этап?')) {
            fetch(`/api/v1/passport/stages/delete/${stageId}`, {
                method: 'POST'
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    row.remove(); // Удаляем строку из DOM
                } else {
                    alert('Ошибка удаления: ' + data.error);
                }
            });
        }
    }

    // --- 3. Вспомогательные функции для обновления DOM ---

    function updateRowViews(rowElement, stageData) {
        // Обновляем текстовые спаны
        rowElement.querySelector('.passport-value-view').textContent = stageData.stage_name;
        (rowElement.querySelectorAll('.passport-value-view'))[1].textContent = stageData.start_date || '...';
        (rowElement.querySelectorAll('.passport-value-view'))[2].textContent = stageData.planned_end_date || '...';
        (rowElement.querySelectorAll('.passport-value-view'))[3].textContent = stageData.actual_end_date || '...';

        // Также обновляем значения в input на случай, если пользователь захочет
        // отредактировать снова, не отменяя режим редактирования
        rowElement.querySelector('.stage-name-input').value = stageData.stage_name;
        rowElement.querySelector('.stage-start-date-input').value = stageData.start_date || '';
        rowElement.querySelector('.stage-planned-end-date-input').value = stageData.planned_end_date || '';
        rowElement.querySelector('.stage-actual-end-date-input').value = stageData.actual_end_date || '';
    }

    function appendStageRow(stage) {
        const newRow = document.createElement('tr');
        newRow.dataset.stageId = stage.id;
        newRow.innerHTML = `
            <td>
                <span class="passport-value-view">${stage.stage_name}</span>
                <input type="text" class="form-control passport-value-edit stage-name-input" value="${stage.stage_name}">
            </td>
            <td>
                <span class="passport-value-view">${stage.start_date || '...'}</span>
                <input type="date" class="form-control passport-value-edit stage-start-date-input" value="${stage.start_date || ''}">
            </td>
            <td>
                <span class="passport-value-view">${stage.planned_end_date || '...'}</span>
                <input type="date" class="form-control passport-value-edit stage-planned-end-date-input" value="${stage.planned_end_date || ''}">
            </td>
            <td>
                <span class="passport-value-view">${stage.actual_end_date || '...'}</span>
                <input type="date" class="form-control passport-value-edit stage-actual-end-date-input" value="${stage.actual_end_date || ''}">
            </td>
            <td class="passport-value-edit">
                <button type="button" class="btn btn-sm btn-success save-stage-btn" data-id="${stage.id}"><i class="bi bi-check-lg"></i></button>
                <button type="button" class="btn btn-sm btn-danger delete-stage-btn" data-id="${stage.id}"><i class="bi bi-trash"></i></button>
            </td>
        `;
        stagesTbody.appendChild(newRow);
    }

}); // <-- Это закрывающая скобка для document.addEventListener
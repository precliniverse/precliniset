/**
 * groups_edit.js
 * Handles logic for creating and editing experimental groups.
 */

document.addEventListener('DOMContentLoaded', function () {
    // 1. Load Configuration from the DOM
    const configEl = document.getElementById('group-editor-config');
    if (!configEl) return;
    const CONFIG = JSON.parse(configEl.textContent);

    // --- DOM Elements ---
    const projectSelect = document.getElementById('project_select');
    const modelSelect = document.getElementById('model_select');
    const eaSelect = document.getElementById('ethical_approval_select');
    const downloadBtn = document.getElementById('download-data-btn');
    const animalTable = document.getElementById('animal-data-table');
    const tableBody = animalTable.querySelector('tbody');
    const addAnimalButtonContainer = document.getElementById('add-animal-button-container');
    const saveBtn = document.getElementById('save-group-btn');
    const groupForm = document.getElementById('group-form');
    // --- Delete Button Logic ---
    const deleteBtn = document.getElementById('delete-group-btn');
    const deleteForm = document.getElementById('deleteGroupForm');

    if (deleteBtn && deleteForm) {
        deleteBtn.addEventListener('click', function (e) {
            e.preventDefault();
            const message = deleteForm.dataset.confirmMessage || 'Are you sure?';
            if (confirm(message)) {
                deleteForm.submit();
            }
        });
    }


    let nextRowIndex = 0;

    function getRandomColor() {
        const letters = '0123456789ABCDEF';
        let color = '#';
        for (let i = 0; i < 6; i++) {
            color += letters[Math.floor(Math.random() * 16)];
        }
        return color;
    }

    // --- Helper Functions ---
    function showErrorModal(message) {
        const modal = new bootstrap.Modal(document.getElementById('errorModal'));
        document.getElementById('errorModalMessage').textContent = message;
        modal.show();
    }

    function formatDateToHTMLInput(dateString) {
        if (!dateString) return '';
        if (dateString.match(/^\d{4}-\d{2}-\d{2}$/)) return dateString;
        try {
            const date = new Date(dateString);
            if (isNaN(date.getTime())) return dateString;
            const year = date.getFullYear();
            const month = (date.getMonth() + 1).toString().padStart(2, '0');
            const day = date.getDate().toString().padStart(2, '0');
            return `${year}-${month}-${day}`;
        } catch (e) {
            console.warn("Failed to format date string:", dateString, e);
            return dateString;
        }
    }

    function updateDownloadButton() {
        if (!downloadBtn) return;

        // Update button URL based on model selection (for new groups) or keep group download (for existing)
        if (!CONFIG.isEditing) {
            const modelId = $(modelSelect).val();
            if (modelId && modelId !== '0') {
                downloadBtn.href = CONFIG.urls.downloadTemplate.replace('0', modelId);
                downloadBtn.removeAttribute('disabled');
            } else {
                downloadBtn.href = '#';
                downloadBtn.setAttribute('disabled', 'disabled');
            }
        }
        // For existing groups, the href is already set to download current data
    }

    function createAddButton(fields) {
        addAnimalButtonContainer.innerHTML = '';
        if (fields && fields.length > 0) {
            const addButton = document.createElement('button');
            addButton.type = 'button';
            addButton.className = 'btn btn-success btn-sm';
            addButton.innerHTML = '<i class="fas fa-plus me-1"></i>' + CONFIG.i18n.addAnimal;
            addButton.addEventListener('click', () => {
                addAnimalRow({}, nextRowIndex, fields);
            });
            addAnimalButtonContainer.appendChild(addButton);
        }
    }

    function reindexTableRows() {
        const rows = tableBody.querySelectorAll('tr');
        rows.forEach((row, newIndex) => {
            const inputs = row.querySelectorAll('input[name^="animal_"]');
            inputs.forEach(input => {
                const nameParts = input.name.split('_');
                if (nameParts.length >= 4) {
                    nameParts[1] = newIndex.toString();
                    input.name = nameParts.join('_');
                }
            });
        });
        nextRowIndex = rows.length;
    }

    function updateTableHeader(fields) {
        const headerRow = animalTable.querySelector('thead tr');
        headerRow.innerHTML = `<th>${CONFIG.i18n.actions}</th>`;

        // Conditionally add Blinding/Randomization
        if (CONFIG.hasRandomization) {
            if (CONFIG.isBlinded) {
                const blindedTh = document.createElement('th');
                blindedTh.textContent = "Blinded Group";
                blindedTh.dataset.fieldName = "blinded_group";
                headerRow.appendChild(blindedTh);

                // Only show treatment_group if user can view unblinded
                if (CONFIG.canViewUnblinded) {
                    const treatmentTh = document.createElement('th');
                    treatmentTh.textContent = "Treatment Group";
                    treatmentTh.dataset.fieldName = "treatment_group";
                    headerRow.appendChild(treatmentTh);
                }
            } else {
                // Not blinded, just show treatment_group
                const treatmentTh = document.createElement('th');
                treatmentTh.textContent = "Treatment Group";
                treatmentTh.dataset.fieldName = "treatment_group";
                headerRow.appendChild(treatmentTh);
            }
        }

        // age_days is always visible in UI
        const ageTh = document.createElement('th');
        ageTh.textContent = "Age (Days)";
        ageTh.dataset.fieldName = "age_days";
        ageTh.title = "Calculated automatically from Date of Birth";
        headerRow.appendChild(ageTh);

        fields.forEach(field => {
            const lowFieldName = field.name.toLowerCase();
            // Logic: Show if editing/viewing AND (not randomized OR not sensitive OR user can view unblinded)
            const shouldShow = !CONFIG.isEditing || !CONFIG.hasRandomization || !field.is_sensitive || CONFIG.canViewUnblinded;

            if (shouldShow && lowFieldName !== 'age_days' && lowFieldName !== 'age (days)' &&
                field.name !== 'blinded_group' && field.name !== 'treatment_group') {
                const th = document.createElement('th');
                th.textContent = field.name + (field.unit ? ` (${field.unit})` : '');
                headerRow.appendChild(th);
            }
        });

        // Add euthanasia columns if there are dead animals
        const hasDeadAnimals = CONFIG.existingAnimalData && CONFIG.existingAnimalData.some(animal => animal.status === 'dead');
        if (hasDeadAnimals) {
            const reasonTh = document.createElement('th');
            reasonTh.textContent = 'Euthanasia Reason';
            headerRow.appendChild(reasonTh);

            const severityTh = document.createElement('th');
            severityTh.textContent = 'Severity';
            headerRow.appendChild(severityTh);
        }
    }

    function addAnimalRow(animalData = {}, rowIndex = -1, fields = []) {
        const row = document.createElement('tr');
        if (animalData.status === 'dead') {
            row.classList.add('table-danger');
        }

        // Actions Cell
        const actionsCell = document.createElement('td');
        const btnGroup = document.createElement('div');
        btnGroup.className = 'btn-group btn-group-sm';

        const duplicateBtn = document.createElement('button');
        duplicateBtn.type = 'button';
        duplicateBtn.className = 'btn btn-outline-primary duplicate-row-btn';
        duplicateBtn.innerHTML = '<i class="fa-solid fa-copy"></i>';
        if (animalData.status === 'dead') duplicateBtn.disabled = true;

        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'btn btn-outline-danger remove-row-btn';
        removeBtn.innerHTML = '<i class="fa-solid fa-trash"></i>';
        if (animalData.status === 'dead') removeBtn.disabled = true;

        btnGroup.appendChild(duplicateBtn);
        btnGroup.appendChild(removeBtn);
        actionsCell.appendChild(btnGroup);
        row.appendChild(actionsCell);

        // Randomization Cells
        if (CONFIG.hasRandomization) {
            if (CONFIG.isBlinded) {
                const blindedCell = document.createElement('td');
                const blindedValue = animalData['blinded_group'] || '-';
                blindedCell.innerHTML = `<span class="badge bg-info">${blindedValue}</span>`;
                row.appendChild(blindedCell);

                if (CONFIG.canViewUnblinded) {
                    const treatmentCell = document.createElement('td');
                    treatmentCell.textContent = animalData['treatment_group'] || '-';
                    row.appendChild(treatmentCell);
                }
            } else {
                const treatmentCell = document.createElement('td');
                treatmentCell.textContent = animalData['treatment_group'] || '-';
                row.appendChild(treatmentCell);
            }
        }

        // age_days Cell
        const ageCell = document.createElement('td');
        ageCell.className = "text-center bg-light";
        const ageSpan = document.createElement('span');
        ageSpan.className = "age-display";
        ageSpan.textContent = animalData['age_days'] || '-';
        ageCell.appendChild(ageSpan);
        row.appendChild(ageCell);

        // Field Cells
        fields.forEach(field => {
            const lowFieldName = field.name.toLowerCase();
            if (lowFieldName === 'age_days' || lowFieldName === 'age (days)' ||
                field.name === 'blinded_group' || field.name === 'treatment_group') return;

            const shouldShow = !CONFIG.isEditing || !CONFIG.hasRandomization || !field.is_sensitive || CONFIG.canViewUnblinded;

            if (shouldShow) {
                const cell = document.createElement('td');
                const input = document.createElement('input');

                input.type = field.type === 'date' ? 'date' : 'text';
                input.name = `animal_${rowIndex}_field_${field.name}`;
                input.className = 'form-control form-control-sm';

                // Try exact match, then lowercase
                let fieldValue = animalData[field.name];
                if (fieldValue === undefined || fieldValue === null) {
                    fieldValue = animalData[lowFieldName];
                }
                if (fieldValue === undefined || fieldValue === null) fieldValue = field.default_value || '';

                if (field.type === 'date' && fieldValue) {
                    input.value = formatDateToHTMLInput(fieldValue);
                } else {
                    input.value = fieldValue;
                }

                if (lowFieldName === 'id' || lowFieldName === 'uid') input.required = true;
                if (animalData.status === 'dead') input.disabled = true;

                if (field.type === 'category' && field.allowed_values) {
                    input.setAttribute('list', `datalist-${field.name.replace(/\s+/g, '-')}-${rowIndex}`);
                    const datalist = document.createElement('datalist');
                    datalist.id = `datalist-${field.name.replace(/\s+/g, '-')}-${rowIndex}`;
                    field.allowed_values.split(';').forEach(val => {
                        const option = document.createElement('option');
                        option.value = val.trim();
                        datalist.appendChild(option);
                    });
                    cell.appendChild(datalist);
                }

                // Death Info
                if (lowFieldName === 'date_of_birth' && animalData.status === 'dead' && animalData.death_date) {
                    const div = document.createElement('div');
                    div.className = 'death-info';
                    div.dataset.deathDate = animalData.death_date;
                    div.innerHTML = `<small class="text-muted d-block">${CONFIG.i18n.deceased}: ${animalData.death_date.split('T')[0]}</small>`;
                    cell.appendChild(div);
                }

                cell.appendChild(input);
                row.appendChild(cell);
            }
        });

        // Trigger age calculation
        calculateRowAge(row);

        // Add euthanasia cells if there are dead animals
        const hasDeadAnimals = CONFIG.existingAnimalData && CONFIG.existingAnimalData.some(animal => animal.status === 'dead');
        if (hasDeadAnimals) {
            // Euthanasia Reason Cell
            const reasonCell = document.createElement('td');
            const reasonInput = document.createElement('input');
            reasonInput.type = 'text';
            reasonInput.className = 'form-control form-control-sm';
            reasonInput.value = animalData.euthanasia_reason || '';
            reasonInput.disabled = animalData.status !== 'dead';
            reasonCell.appendChild(reasonInput);
            row.appendChild(reasonCell);

            // Severity Cell
            const severityCell = document.createElement('td');
            const severityInput = document.createElement('input');
            severityInput.type = 'text';
            severityInput.className = 'form-control form-control-sm';
            severityInput.value = animalData.severity || '';
            severityInput.disabled = animalData.status !== 'dead';
            severityCell.appendChild(severityInput);
            row.appendChild(severityCell);
        }

        tableBody.appendChild(row);
        nextRowIndex++;
    }

    function handleModelChange() {
        const modelId = $(modelSelect).val();
        if (!modelId || modelId === '0' || modelId === '') {
            tableBody.innerHTML = '';
            addAnimalButtonContainer.innerHTML = '';
            updateDownloadButton();
            return;
        }

        // Loading state
        const headerRow = animalTable.querySelector('thead tr');
        headerRow.innerHTML = `<th>${CONFIG.i18n.loading}</th>`;

        fetch(CONFIG.urls.getModelFields.replace('0', modelId))
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    updateTableHeader(data.fields);
                    tableBody.innerHTML = '';

                    // Populate existing data if available
                    if (CONFIG.existingAnimalData && CONFIG.existingAnimalData.length > 0 && CONFIG.isEditing) {
                        CONFIG.existingAnimalData.forEach((animal, index) => {
                            addAnimalRow(animal, index, data.fields);
                        });
                    }

                    createAddButton(data.fields);
                    updateDownloadButton();

                    // Store fields for duplication logic
                    CONFIG.currentModelFields = data.fields;
                } else {
                    alert("Error: " + data.error);
                }
            })
            .catch(err => console.error(err));
    }

    // --- Event Listeners ---

    // Initialisation standard pour les champs statiques
    $('#model_select').select2({
        theme: "bootstrap-5",
        width: '100%'
    });

    $('#ethical_approval_select').select2({
        theme: "bootstrap-5",
        width: '100%',
        templateSelection: function (data) {
            if (!data.id) { return data.text; }
            // Shorten the text for the selection display (closed dropdown)
            // Split by " - " and take the first part (ID)
            return data.text.split(' - ')[0];
        },
        templateResult: function (data) {
            return data.text;
        }
    });

    // Initialisation AJAX pour le Projet (Optimisation Performance)
    $('#project_select').select2({
        theme: "bootstrap-5",
        width: '100%',
        placeholder: CONFIG.i18n.selectProject,
        allowClear: true,
        ajax: {
            url: CONFIG.urls.searchProjects,
            dataType: 'json',
            delay: 250,
            data: function (params) {
                return {
                    q: params.term,
                    page: params.page || 1,
                    show_archived: false
                };
            },
            processResults: function (data, params) {
                params.page = params.page || 1;
                return {
                    results: data.results,
                    pagination: {
                        more: (params.page * 10) < data.total_count
                    }
                };
            },
            cache: true
        },
        minimumInputLength: 0
    });

    $('#project_select').on('select2:select', function (e) {
        const projectId = e.params.data.id;
        updateEADropdown(projectId);
    });

    function updateEADropdown(projectId) {
        // Clear existing options
        $(eaSelect).empty().append(new Option(CONFIG.i18n.selectEA, ''));

        if (!projectId || projectId === '0') {
            $(eaSelect).prop('disabled', true);
            $(eaSelect).trigger('change');
            return;
        }

        $(eaSelect).prop('disabled', false);
        // Fetch EAs for the selected project
        fetch(CONFIG.urls.getEthicalApprovalsForProject.replace('0', projectId))
            .then(response => response.json())
            .then(data => {
                data.forEach(ea => {
                    const fullText = ea.text;
                    // Use full text for the option so it shows in the dropdown list
                    const newOption = new Option(fullText, ea.id, false, false);
                    newOption.title = fullText;
                    $(eaSelect).append(newOption);
                });

                // Set initial selection if exists
                if (CONFIG.ethicalApprovalId) {
                    $(eaSelect).val(CONFIG.ethicalApprovalId);
                }
                $(eaSelect).trigger('change'); // Notify Select2 of changes
            })
            .catch(err => {
                console.error("Error fetching ethical approvals:", err);
                $(eaSelect).prop('disabled', true);
                $(eaSelect).trigger('change');
            });
    }

    // Initial Load
    const initialProjectId = $(projectSelect).val();
    if (initialProjectId && initialProjectId !== '0') {
        updateEADropdown(initialProjectId);
    } else if (CONFIG.prefilledProjectId) {
        // Trigger for prefilled projects on new groups
        updateEADropdown(CONFIG.prefilledProjectId);
    }

    if ($(modelSelect).val() && $(modelSelect).val() !== '0') {
        handleModelChange();
    }

    // Add change listener for model selection
    $(modelSelect).on('change', function () {
        handleModelChange();
    });

    // Calculate age for existing rows
    animalTable.querySelectorAll('tbody tr').forEach(row => {
        calculateRowAge(row);
    });

    // Table Actions (Delete/Duplicate/Calculate Age)
    tableBody.addEventListener('change', (e) => {
        // Dynamic Age Calculation
        if (e.target.name && e.target.name.includes('_field_date_of_birth')) {
            const row = e.target.closest('tr');
            calculateRowAge(row);
        }
    });

    function calculateRowAge(row) {
        // Look for the field ending in _date_of_birth
        const dobInput = row.querySelector('input[name*="_field_date_of_birth"]');
        const ageDisplay = row.querySelector('.age-display');

        if (dobInput && dobInput.value) {
            const dob = new Date(dobInput.value);
            const today = new Date();
            const diff = Math.floor((today - dob) / (1000 * 60 * 60 * 24));

            if (!isNaN(diff) && diff >= 0) {
                const weeks = Math.floor(diff / 7);
                ageDisplay.textContent = `${diff} days (${weeks} weeks)`;
            } else {
                ageDisplay.textContent = '-';
            }
        } else {
            if (ageDisplay) ageDisplay.textContent = '-';
        }
    }

    // Import Button
    const importBtn = document.getElementById('import-xlsx-btn');
    if (importBtn) {
        importBtn.addEventListener('click', function () {
            const fileInput = document.getElementById('xlsx_upload');

            if (!fileInput.files.length) {
                alert("Please select an XLSX file to import.");
                return;
            }

            // Validation of the rest of the form (Group Name, etc.)
            if (validateForm()) {
                // For imports, we usually want to confirm because it overwrites the table
                if (confirm("Importing this file will replace or update the current animal list. Continue?")) {
                    // We call performAjaxSave. The FormData(groupForm) will 
                    // automatically include the file from the 'xlsx_upload' input.
                    performAjaxSave(false);
                }
            }
        });
    }

    tableBody.addEventListener('click', (e) => {
        // Handle Delete
        if (e.target.closest('.remove-row-btn')) {
            if (confirm(CONFIG.i18n.confirmDelete)) {
                e.target.closest('tr').remove();
                reindexTableRows();
                updateDownloadButton();
            }
        }
        // Handle Duplicate
        else if (e.target.closest('.duplicate-row-btn')) {
            const sourceRow = e.target.closest('tr');
            const inputs = sourceRow.querySelectorAll('input');

            // 1. Extract data from the source row
            let rowData = {};
            inputs.forEach(input => {
                // Input names are like: animal_0_field_ID
                const parts = input.name.split('_field_');
                if (parts.length === 2) {
                    const fieldName = parts[1];
                    // Don't copy the uid, we want a new one or blank
                    if (fieldName !== 'uid') {
                        rowData[fieldName] = input.value;
                    }
                }
            });

            // 2. Copy status if needed (usually we don't duplicate dead status)
            // rowData.status = 'alive'; 

            // 3. Use the existing function to add a new row with this data
            // We need to pass the current model fields to ensure columns match
            // If we loaded via handleModelChange, we have them. 
            // If page just loaded, we need to scrape headers or use the config.

            // Fallback: If we don't have the fields list in memory, we can't easily use addAnimalRow
            // BUT, we can just clone the DOM node like the old code did, which is safer for now.

            const newRow = sourceRow.cloneNode(true);

            // Reset the uid field in the clone
            const idInput = newRow.querySelector('input[name*="_field_uid"]');
            if (idInput) idInput.value = '';

            // Enable buttons if they were disabled (e.g. if source was dead)
            newRow.classList.remove('table-danger');
            newRow.querySelectorAll('input').forEach(i => i.disabled = false);
            newRow.querySelectorAll('button').forEach(b => b.disabled = false);

            // Remove any death info text
            newRow.querySelectorAll('.death-info, .death-info-container').forEach(el => el.innerHTML = '');

            // Append and Reindex
            tableBody.appendChild(newRow);
            reindexTableRows();
            updateDownloadButton();
        }
    });

    function validateForm() {
        let isValid = true;
        // Clear previous errors
        $('.is-invalid').removeClass('is-invalid');
        $('.invalid-feedback').remove();

        if (!CONFIG.isEditing) {
            const project = $('#project_select').val();
            if (!project || project === '0') {
                isValid = false;
                $('#project_select').addClass('is-invalid');
                $('#project_select').next('.select2-container').after('<div class="invalid-feedback d-block">Project is required.</div>');
            }

            const model = $('#model_select').val();
            if (!model || model === '0') {
                isValid = false;
                $('#model_select').addClass('is-invalid');
                $('#model_select').next('.select2-container').after('<div class="invalid-feedback d-block">Model is required.</div>');
            }
        }

        const name = $('input[name=name]').val();
        if (!name.trim()) {
            isValid = false;
            $('input[name=name]').addClass('is-invalid');
            $('input[name=name]').after('<div class="invalid-feedback d-block">Group Name is required.</div>');
        }

        return isValid;
    }

    // Save Button
    if (saveBtn) {
        saveBtn.addEventListener('click', function (e) {
            e.preventDefault();
            if (validateForm()) {
                // If editing, show confirmation modal about updating datatables
                if (CONFIG.isEditing) {
                    performAjaxSave(); // No 'dont-update-datatables' for new groups
                }
            }
        });
    }

    // Confirmation modal logic
    const confirmSaveBtn = document.getElementById('confirm-save-group');
    if (confirmSaveBtn) {
        confirmSaveBtn.addEventListener('click', function () {
            performAjaxSave();
        });
    }

    function performAjaxSave(allowNewCategories = false) {
        const formData = new FormData(groupForm);
        formData.append('is_ajax', 'true');
        if (allowNewCategories) {
            formData.append('allow_new_categories', 'true');
        }

        // Collect dynamically added animal data
        const animalData = [];
        animalTable.querySelectorAll('tbody tr').forEach(row => {
            const rowData = {};
            row.querySelectorAll('input[name^="animal_"]').forEach(input => {
                const nameParts = input.name.split('_field_');
                if (nameParts.length === 2) {
                    const fieldName = nameParts[1];
                    rowData[fieldName] = input.value;
                }
            });
            // Also collect age_days from display span if present, 
            // though backend might recalculate it, it's safer to send current UI state
            const ageDisplay = row.querySelector('.age-display');
            if (ageDisplay) {
                rowData['age_days'] = ageDisplay.textContent.trim();
            }

            animalData.push(rowData);
        });
        formData.append('animal_data', JSON.stringify(animalData));

        // Submit via Fetch API
        fetch(groupForm.action, {
            method: 'POST',
            body: formData
        })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    if (!CONFIG.isEditing && data.redirect_url) {
                        window.location.href = data.redirect_url;
                    } else {
                        window.location.reload();
                    }
                } else if (data.type === 'new_categories') {
                    handleNewCategoriesDiscovered(data.data, dontUpdateDataTables);
                } else {
                    showErrorModal(data.message);
                }
                // Hide modals
                ['saveConfirmationModal', 'newCategoryModal'].forEach(id => {
                    const modalEl = document.getElementById(id);
                    if (modalEl) {
                        const inst = bootstrap.Modal.getInstance(modalEl);
                        if (inst) inst.hide();
                    }
                });
            })
            .catch(error => {
                console.error('Error during AJAX save:', error);
                showErrorModal(CONFIG.i18n.ajaxError || "An error occurred while saving.");
            });
    }

    function handleNewCategoriesDiscovered(categoriesMap, dontUpdateDataTables) {
        const listContainer = document.getElementById('new-categories-list');
        listContainer.innerHTML = '';

        // Map of analyteId -> analyteName for better display
        // We can get this from the table headers or just use IDs for now
        // Let's scrape the table headers for a quick map
        const fieldNameMap = {};
        animalTable.querySelectorAll('thead th').forEach(th => {
            const name = th.textContent.trim();
            fieldNameMap[name] = name; // Basic map, ideally we'd have IDs
        });

        for (const [analyteId, values] of Object.entries(categoriesMap)) {
            const div = document.createElement('div');
            div.className = 'mb-2';
            div.innerHTML = `<strong>Analyte ID ${analyteId}:</strong> <span class="text-muted">${values.join(', ')}</span>`;
            listContainer.appendChild(div);
        }

        const modalEl = document.getElementById('newCategoryModal');
        const confirmBtn = document.getElementById('confirm-add-categories');
        const modalBody = modalEl.querySelector('.modal-body p');

        if (!CONFIG.canEditAnalytes) {
            confirmBtn.style.display = 'none';
            modalBody.textContent = "The following new values were found for categorical fields. You do not have permission to add new allowed values to the system. Please correct your data or contact an administrator.";
        } else {
            confirmBtn.style.display = 'inline-block';
            modalBody.textContent = "The following new values were found for categorical fields. Would you like to add them to the system and proceed?";

            // Setup confirm button
            const newConfirmBtn = confirmBtn.cloneNode(true);
            confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);

            newConfirmBtn.addEventListener('click', () => {
                performAjaxSave(dontUpdateDataTables, true);
            });
        }

        const modal = new bootstrap.Modal(modalEl);
        modal.show();
    }

    // --- Declare Death Modal Logic ---
    // Submit handler for the modal (ensure it's bound only once)
    const submitDeadBtn = document.getElementById('submitDeclareDead');
    if (submitDeadBtn) {
        // Remove existing listener to prevent duplicates if re-initialized
        const newSubmitBtn = submitDeadBtn.cloneNode(true);
        submitDeadBtn.parentNode.replaceChild(newSubmitBtn, submitDeadBtn);

        newSubmitBtn.addEventListener('click', function () {
            const groupId = document.getElementById('modalGroupId').value;
            const form = document.getElementById('declareDeadForm');
            const death_date = form.querySelector('#death_date').value;

            if (!death_date) { alert("Please select a date of death."); return; }

            // Collect per-animal data
            const animalData = [];
            const checkedCheckboxes = form.querySelectorAll('input[name="animal_indices"]:checked');

            if (checkedCheckboxes.length === 0) {
                alert("Please select at least one animal.");
                return;
            }

            for (const checkbox of checkedCheckboxes) {
                const index = checkbox.value;
                const reasonSelect = form.querySelector(`select[name="euthanasia_reason_${index}"]`);
                const severitySelect = form.querySelector(`select[name="severity_${index}"]`);

                const reason = reasonSelect ? reasonSelect.value : '';
                const severity = severitySelect ? severitySelect.value : '';

                if (!reason || !severity) {
                    alert(`Please select both reason and severity for animal ${index}.`);
                    return;
                }

                animalData.push({
                    index: index,
                    euthanasia_reason: reason,
                    severity: severity
                });
            }

            const csrfToken = document.querySelector('input[name="csrf_token"]').value;
            fetch(`/groups/declare_dead/${groupId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({
                    death_date: death_date,
                    animals: animalData
                })
            })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        bootstrap.Modal.getInstance(document.getElementById('declareDeadModal')).hide();
                        window.location.reload();
                    } else {
                        alert("Error: " + data.message);
                    }
                });
        });
    }

    // Declare Death Button Logic
    document.addEventListener('click', function (e) {
        if (e.target.closest('.declare-dead-btn')) {
            e.stopPropagation();
            const btn = e.target.closest('.declare-dead-btn');
            const groupId = btn.getAttribute('data-group-id');
            const groupName = btn.getAttribute('data-group-name');

            const modelFieldsScript = document.getElementById(btn.getAttribute('data-model-fields-id'));
            let modelFields = [];
            if (modelFieldsScript) {
                try {
                    modelFields = JSON.parse(modelFieldsScript.textContent);
                } catch (e) {
                    console.error("Error parsing model fields JSON:", e);
                    modelFields = [];
                }
            }

            // Fetch animal data
            fetch(`/groups/api/${groupId}/animal_data`)
                .then(r => r.json())
                .then(animalData => {
                    if (animalData.error) {
                        alert(animalData.error);
                        return;
                    }

                    const modalEl = document.getElementById('declareDeadModal');
                    const modalInstance = new bootstrap.Modal(modalEl);
                    const modalTitle = modalEl.querySelector('.modal-title');
                    const modalGroupIdInput = modalEl.querySelector('#modalGroupId');
                    const table = modalEl.querySelector('#declareDeadAnimalsTable');
                    const header = table.querySelector('thead');
                    const body = table.querySelector('tbody');

                    modalTitle.textContent = `Declare Animal(s) as Dead for Group: ${groupName}`;
                    modalGroupIdInput.value = groupId;

                    // Clear previous
                    header.innerHTML = '';
                    body.innerHTML = '';

                    // Build Header
                    const headerRow = header.insertRow();
                    let th = headerRow.insertCell();
                    const selectAllCheckbox = document.createElement('input');
                    selectAllCheckbox.type = 'checkbox';
                    selectAllCheckbox.id = 'selectAllAnimalsDeadModal_edit';
                    th.appendChild(selectAllCheckbox);

                    modelFields.forEach(field => {
                        if (field.name === 'ID' || field.name === 'Genotype' || field.name === 'Cage') {
                            th = headerRow.insertCell();
                            th.textContent = field.name;
                        }
                    });
                    th = headerRow.insertCell();
                    th.textContent = 'Status';
                    th = headerRow.insertCell();
                    th.textContent = 'Euthanasia Reason';
                    th = headerRow.insertCell();
                    th.textContent = 'Severity';

                    // Build Body
                    animalData.animals.forEach((animal, index) => {
                        const row = body.insertRow();
                        if (animal.status === 'dead') row.classList.add('table-danger');

                        let cell = row.insertCell();
                        const checkbox = document.createElement('input');
                        checkbox.type = 'checkbox';
                        checkbox.name = 'animal_indices';
                        checkbox.value = index;
                        if (animal.status === 'dead') checkbox.disabled = true;
                        cell.appendChild(checkbox);

                        modelFields.forEach(field => {
                            if (field.name === 'ID' || field.name === 'Genotype' || field.name === 'Cage') {
                                cell = row.insertCell();
                                cell.textContent = animal[field.name] || '';
                            }
                        });

                        cell = row.insertCell();
                        if (animal.status === 'dead') cell.textContent = `Dead (${animal.death_date || 'N/A'})`;

                        // Euthanasia Reason Cell
                        cell = row.insertCell();
                        const reasonSelect = document.createElement('select');
                        reasonSelect.className = 'form-select form-select-sm';
                        reasonSelect.name = `euthanasia_reason_${index}`;
                        reasonSelect.innerHTML = `
                            <option value="">-- Select --</option>
                            <option value="état de santé">état de santé</option>
                            <option value="fin de protocole">fin de protocole</option>
                            <option value="Point limite atteint">Point limite atteint</option>
                        `;
                        if (animal.status === 'dead') {
                            reasonSelect.disabled = true;
                            reasonSelect.value = animal.euthanasia_reason || '';
                        }
                        cell.appendChild(reasonSelect);

                        // Severity Cell
                        cell = row.insertCell();
                        const severitySelect = document.createElement('select');
                        severitySelect.className = 'form-select form-select-sm';
                        severitySelect.name = `severity_${index}`;
                        severitySelect.innerHTML = `
                            <option value="">-- Select --</option>
                            <option value="légère">légère</option>
                            <option value="modérée">modérée</option>
                            <option value="sévère">sévère</option>
                        `;
                        if (animal.status === 'dead') {
                            severitySelect.disabled = true;
                            severitySelect.value = animal.severity || '';
                        }
                        cell.appendChild(severitySelect);
                    });

                    selectAllCheckbox.addEventListener('change', function () {
                        body.querySelectorAll('input[name="animal_indices"]:not([disabled])').forEach(checkbox => {
                            checkbox.checked = this.checked;
                        });
                    });

                    // Apply to Selected Button Logic
                    const applyToSelectedBtn = modalEl.querySelector('#applyToSelectedBtn');
                    if (applyToSelectedBtn) {
                        applyToSelectedBtn.addEventListener('click', function () {
                            const globalReason = modalEl.querySelector('#global_euthanasia_reason').value;
                            const globalSeverity = modalEl.querySelector('#global_severity').value;

                            if (!globalReason || !globalSeverity) {
                                alert("Please select both euthanasia reason and severity to apply.");
                                return;
                            }

                            const checkedCheckboxes = body.querySelectorAll('input[name="animal_indices"]:checked');
                            if (checkedCheckboxes.length === 0) {
                                alert("Please select at least one animal to apply the settings to.");
                                return;
                            }

                            checkedCheckboxes.forEach(checkbox => {
                                const index = checkbox.value;
                                const reasonSelect = body.querySelector(`select[name="euthanasia_reason_${index}"]`);
                                const severitySelect = body.querySelector(`select[name="severity_${index}"]`);

                                if (reasonSelect && !reasonSelect.disabled) {
                                    reasonSelect.value = globalReason;
                                }
                                if (severitySelect && !severitySelect.disabled) {
                                    severitySelect.value = globalSeverity;
                                }
                            });
                        });
                    }

                    // Ensure modal is properly disposed when hidden
                    modalEl.addEventListener('hidden.bs.modal', function () {
                        // Reset form and clear dynamic content
                        const form = modalEl.querySelector('#declareDeadForm');
                        if (form) form.reset();
                        const table = modalEl.querySelector('#declareDeadAnimalsTable');
                        if (table) {
                            table.querySelector('thead').innerHTML = '';
                            table.querySelector('tbody').innerHTML = '';
                        }
                    });

                    modalInstance.show();
                })
                .catch(err => console.error(err));
        }
    });

    // --- Analyte Concatenation Feature ---
    let concatenatedData = null;
    let availableAnalytes = [];

    // Add concatenation button to action bar (only when editing)
    let showConcatenationBtn = document.getElementById('show-concatenation-btn');
    if (!showConcatenationBtn && CONFIG.isEditing) {
        const actionBar = document.querySelector('.d-flex.align-items-center');
        if (actionBar) {
            showConcatenationBtn = document.createElement('button');
            showConcatenationBtn.type = 'button';
            showConcatenationBtn.className = 'btn btn-info ms-2';
            showConcatenationBtn.id = 'show-concatenation-btn';
            showConcatenationBtn.title = 'Analyte Concatenation & Analysis';
            showConcatenationBtn.innerHTML = '<i class="fas fa-chart-line"></i> Concatenation';
            actionBar.appendChild(showConcatenationBtn);
        }
    }

    // Show concatenation card
    let concatenationCard = document.getElementById('analyte-concatenation-card');

    // Create card if it doesn't exist
    if (!concatenationCard) {
        concatenationCard = document.createElement('div');
        concatenationCard.id = 'analyte-concatenation-card';
        concatenationCard.className = 'card mt-4';
        concatenationCard.style.display = 'none';
        concatenationCard.innerHTML = `
            <div class="card-header d-flex justify-content-between align-items-center">
                <h5 class="mb-0">Analyte Concatenation & Analysis</h5>
                <button type="button" class="btn btn-sm btn-outline-secondary" id="toggle-concatenation-btn">
                    <i class="fas fa-eye-slash"></i> Hide
                </button>
            </div>
            <div class="card-body">
                <p class="text-muted">Concatenate and analyze analytes from all datatables linked to this group chronologically.</p>

                <div class="mb-3">
                    <label for="analyte-selector" class="form-label">Select Analytes to Concatenate</label>
                    <select id="analyte-selector" class="form-select" multiple style="min-height: 100px;"></select>
                    <small class="form-text text-muted">Select one or more analytes. Hold Ctrl/Cmd to select multiple.</small>
                </div>

                <button type="button" class="btn btn-primary mb-3" id="load-concatenation-btn">
                    <i class="fas fa-sync"></i> Load Concatenated Data
                </button>

                <div id="concatenated-data-container" style="display: none;">
                    <h6>Chronological Analyte Data</h6>
                    <div class="table-responsive" style="max-height: 400px; overflow-y: auto;">
                        <table class="table table-sm table-bordered table-striped" id="concatenated-data-table">
                            <thead class="table-light" style="position: sticky; top: 0; background: white;">
                                <tr>
                                    <th>Animal ID</th>
                                    <th>Analyte</th>
                                    <th>Date</th>
                                    <th>Value</th>
                                    <th>Protocol</th>
                                </tr>
                            </thead>
                            <tbody></tbody>
                        </table>
                    </div>

                    <!-- Global Measurement Tools -->
                    <div class="mt-4">
                        <h6>Global Measurement Tools</h6>
                        <div class="row g-3">
                            <div class="col-md-3">
                                <label for="global-analyte-select" class="form-label">Select Analyte</label>
                                <select id="global-analyte-select" class="form-select">
                                    <option value="">Choose Analyte</option>
                                </select>
                            </div>
                            <div class="col-md-3">
                                <label for="measurement-type-select" class="form-label">Measurement Type</label>
                                <select id="measurement-type-select" class="form-select">
                                    <option value="baseline-reduction">Baseline Reduction %</option>
                                    <option value="time-reduction">Time-based Reduction</option>
                                    <option value="threshold-check">Threshold Check</option>
                                </select>
                            </div>
                            <div class="col-md-2">
                                <label for="measurement-value" class="form-label">Value</label>
                                <input type="number" id="measurement-value" class="form-control" placeholder="20">
                            </div>
                            <div class="col-md-2">
                                <label for="measurement-unit" class="form-label">Unit</label>
                                <select id="measurement-unit" class="form-select">
                                    <option value="%">%</option>
                                    <option value="days">days</option>
                                    <option value="absolute">absolute</option>
                                </select>
                            </div>
                            <div class="col-md-2">
                                <label class="form-label">Action</label>
                                <button type="button" class="btn btn-outline-info w-100" id="run-global-measurement-btn">
                                    <i class="fas fa-calculator"></i> Run
                                </button>
                            </div>
                        </div>

                        <div id="global-measurement-results" class="mt-3" style="display: none;">
                            <div class="alert alert-info">
                                <h6>Global Measurement Results</h6>
                                <div id="global-measurement-output"></div>
                            </div>
                        </div>
                    </div>

                    <!-- Evolution Graph -->
                    <div class="mt-4">
                        <h6>Evolution Graph</h6>
                        <div class="row g-3">
                            <div class="col-md-4">
                                <label for="graph-analyte-select" class="form-label">Select Analyte for Graph</label>
                                <select id="graph-analyte-select" class="form-select">
                                    <option value="">Choose Analyte</option>
                                </select>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Action</label>
                                <button type="button" class="btn btn-outline-success w-100" id="generate-graph-btn">
                                    <i class="fas fa-chart-line"></i> Generate Graph
                                </button>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label">Export</label>
                                <button type="button" class="btn btn-outline-primary w-100" id="export-concatenated-btn">
                                    <i class="fas fa-download"></i> Export XLSX
                                </button>
                            </div>
                        </div>

                        <div id="graph-container" class="mt-3" style="display: none;">
                            <canvas id="evolution-chart" width="400" height="200"></canvas>
                        </div>
                    </div>

                    <div class="mt-4">
                        <h6>Statistical Analysis</h6>
                        <div class="row g-3">
                            <div class="col-md-6">
                                <label for="stats-analyte-select" class="form-label">Select Analyte for Stats</label>
                                <select id="stats-analyte-select" class="form-select">
                                    <option value="">Choose Analyte</option>
                                </select>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Action</label>
                                <button type="button" class="btn btn-outline-success w-100" id="calculate-stats-btn">
                                    <i class="fas fa-chart-line"></i> Calculate Statistics
                                </button>
                            </div>
                        </div>

                        <div id="stats-results" class="mt-3" style="display: none;">
                            <div class="alert alert-success">
                                <h6>Statistical Results</h6>
                                <div id="stats-output"></div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        const saveButtonContainer = document.querySelector('.mt-4');
        if (saveButtonContainer && saveButtonContainer.parentNode) {
            saveButtonContainer.parentNode.insertBefore(concatenationCard, saveButtonContainer);
        } else {
            document.querySelector('.container').appendChild(concatenationCard);
        }
    }

    if (showConcatenationBtn && concatenationCard) {
        showConcatenationBtn.addEventListener('click', function () {
            concatenationCard.style.display = 'block';
            showConcatenationBtn.style.display = 'none';
            loadAnalytes();
        });
    }

    // Hide concatenation card
    const toggleConcatenationBtn = document.getElementById('toggle-concatenation-btn');
    if (toggleConcatenationBtn) {
        toggleConcatenationBtn.addEventListener('click', function () {
            concatenationCard.style.display = 'none';
            if (showConcatenationBtn) showConcatenationBtn.style.display = 'inline-block';
        });
    }

    function loadAnalytes() {
        if (!CONFIG.groupId) return;

        fetch(`/groups/api/${CONFIG.groupId}/concatenated_analytes`)
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    showErrorModal(data.error);
                    return;
                }

                availableAnalytes = Object.values(data.analytes);
                const analyteSelector = document.getElementById('analyte-selector');
                analyteSelector.innerHTML = '';

                availableAnalytes.forEach(analyte => {
                    const option = document.createElement('option');
                    option.value = analyte.id;
                    option.textContent = `${analyte.name} (${analyte.unit || 'N/A'})`;
                    analyteSelector.appendChild(option);
                });

                concatenatedData = data;
            })
            .catch(err => {
                console.error('Error loading analytes:', err);
                showErrorModal('Error loading analytes.');
            });
    }

    // Load concatenated data
    const loadConcatenationBtn = document.getElementById('load-concatenation-btn');
    if (loadConcatenationBtn) {
        loadConcatenationBtn.addEventListener('click', function () {
            const selectedAnalyteIds = Array.from(document.getElementById('analyte-selector').selectedOptions).map(opt => opt.value);
            if (selectedAnalyteIds.length === 0) {
                alert('Please select at least one analyte.');
                return;
            }

            const tableBody = document.querySelector('#concatenated-data-table tbody');
            tableBody.innerHTML = '';

            const animalIds = Object.keys(concatenatedData.animal_data);
            const selectedAnalyteNames = availableAnalytes.filter(a => selectedAnalyteIds.includes(a.id.toString())).map(a => a.name);

            let rowCount = 0;
            animalIds.forEach(animalId => {
                selectedAnalyteNames.forEach(analyteName => {
                    const values = concatenatedData.animal_data[animalId][analyteName] || [];
                    values.forEach(([date, value]) => {
                        const row = tableBody.insertRow();
                        row.insertCell().textContent = animalId;
                        row.insertCell().textContent = analyteName;
                        row.insertCell().textContent = date;
                        row.insertCell().textContent = value;
                        row.insertCell().textContent = concatenatedData.datatables.find(dt => dt.date === date)?.protocol_name || 'Unknown';
                        rowCount++;
                    });
                });
            });

            document.getElementById('concatenated-data-container').style.display = 'block';

            // Populate selectors for analysis
            populateAnalysisSelectors(selectedAnalyteNames, animalIds);

            // Show load complete
            loadConcatenationBtn.innerHTML = '<i class="fas fa-check"></i> Loaded ' + rowCount + ' data points';
            setTimeout(() => {
                loadConcatenationBtn.innerHTML = '<i class="fas fa-sync"></i> Reload Data';
            }, 2000);
        });
    }

    function populateAnalysisSelectors(analytes, animals) {
        const globalAnalyteSelect = document.getElementById('global-analyte-select');
        const graphAnalyteSelect = document.getElementById('graph-analyte-select');

        globalAnalyteSelect.innerHTML = '<option value="">Choose Analyte</option>';
        graphAnalyteSelect.innerHTML = '<option value="">Choose Analyte</option>';
        analytes.forEach(analyte => {
            const option1 = document.createElement('option');
            option1.value = analyte;
            option1.textContent = analyte;
            globalAnalyteSelect.appendChild(option1);

            const option2 = document.createElement('option');
            option2.value = analyte;
            option2.textContent = analyte;
            graphAnalyteSelect.appendChild(option2);
        });
    }

    // Run global measurement
    const runGlobalMeasurementBtn = document.getElementById('run-global-measurement-btn');
    if (runGlobalMeasurementBtn) {
        runGlobalMeasurementBtn.addEventListener('click', function () {
            const analyteName = document.getElementById('global-analyte-select').value;
            const measurementType = document.getElementById('measurement-type-select').value;
            const value = parseFloat(document.getElementById('measurement-value').value);
            const unit = document.getElementById('measurement-unit').value;

            if (!analyteName || !measurementType || isNaN(value)) {
                alert('Please fill all fields.');
                return;
            }

            const results = [];
            Object.keys(concatenatedData.animal_data).forEach(animalId => {
                const values = concatenatedData.animal_data[animalId][analyteName] || [];
                if (values.length === 0) return;

                let meetsCriteria = false;
                let resultText = '';

                if (measurementType === 'baseline-reduction') {
                    if (values.length >= 2) {
                        const baseline = values[0][1];
                        const latest = values[values.length - 1][1];
                        const reduction = ((baseline - latest) / baseline * 100);
                        meetsCriteria = reduction >= value;
                        resultText = `Reduction: ${reduction.toFixed(2)}% (threshold: ${value}%)`;
                    }
                } else if (measurementType === 'time-reduction') {
                    // Find values within time window
                    const now = new Date();
                    const cutoff = new Date(now.getTime() - value * 24 * 60 * 60 * 1000);
                    const recentValues = values.filter(([date]) => new Date(date) >= cutoff);
                    if (recentValues.length >= 2) {
                        const baseline = recentValues[0][1];
                        const latest = recentValues[recentValues.length - 1][1];
                        const reduction = ((baseline - latest) / baseline * 100);
                        meetsCriteria = reduction >= value;
                        resultText = `Reduction in last ${value} days: ${reduction.toFixed(2)}%`;
                    }
                } else if (measurementType === 'threshold-check') {
                    const latest = values[values.length - 1][1];
                    if (unit === '%') {
                        meetsCriteria = latest <= value;
                        resultText = `Latest value: ${latest} (threshold: ${value})`;
                    } else {
                        meetsCriteria = latest <= value;
                        resultText = `Latest value: ${latest} (threshold: ${value})`;
                    }
                }

                if (meetsCriteria) {
                    results.push({ animalId, resultText, meets: true });
                }
            });

            const resultsDiv = document.getElementById('global-measurement-results');
            const outputDiv = document.getElementById('global-measurement-output');
            if (results.length > 0) {
                outputDiv.innerHTML = `<p><strong>Animals meeting criteria (${results.length}):</strong></p><ul>` +
                    results.map(r => `<li><strong>${r.animalId}</strong>: ${r.resultText}</li>`).join('') + '</ul>';
            } else {
                outputDiv.innerHTML = '<p>No animals meet the specified criteria.</p>';
            }
            resultsDiv.style.display = 'block';
        });
    }

    // Generate graph
    const generateGraphBtn = document.getElementById('generate-graph-btn');
    if (generateGraphBtn) {
        generateGraphBtn.addEventListener('click', function () {
            const analyteName = document.getElementById('graph-analyte-select').value;
            if (!analyteName) {
                alert('Please select an analyte.');
                return;
            }

            const graphContainer = document.getElementById('graph-container');
            graphContainer.style.display = 'block';

            // Prepare data for Chart.js
            const datasets = [];
            const allDates = new Set();

            Object.keys(concatenatedData.animal_data).forEach(animalId => {
                const values = concatenatedData.animal_data[animalId][analyteName] || [];
                if (values.length > 0) {
                    const dataPoints = values.map(([date, value]) => {
                        allDates.add(date);
                        return { x: date, y: value };
                    });

                    datasets.push({
                        label: animalId,
                        data: dataPoints,
                        borderColor: getRandomColor(),
                        backgroundColor: 'transparent',
                        tension: 0.1
                    });
                }
            });

            const sortedDates = Array.from(allDates).sort();

            const ctx = document.getElementById('evolution-chart').getContext('2d');
            if (window.evolutionChart) {
                window.evolutionChart.destroy();
            }

            window.evolutionChart = new Chart(ctx, {
                type: 'line',
                data: { datasets },
                options: {
                    responsive: true,
                    plugins: {
                        tooltip: {
                            callbacks: {
                                title: function (context) {
                                    return `Animal: ${context[0].dataset.label}`;
                                }
                            }
                        },
                        legend: {
                            display: false // Too many animals, hide legend
                        }
                    },
                    scales: {
                        x: {
                            type: 'time',
                            time: {
                                unit: 'day',
                                displayFormats: {
                                    day: 'MMM dd'
                                }
                            }
                        },
                        y: {
                            beginAtZero: false
                        }
                    },
                    onHover: (event, activeElements) => {
                        if (activeElements.length > 0) {
                            const datasetIndex = activeElements[0].datasetIndex;
                            // Highlight the line
                            window.evolutionChart.data.datasets.forEach((dataset, index) => {
                                dataset.borderWidth = index === datasetIndex ? 4 : 2;
                                dataset.borderColor = index === datasetIndex ? dataset.borderColor : dataset.borderColor.replace('1)', '0.3)');
                            });
                            window.evolutionChart.update();
                        }
                    }
                }
            });
        });
    }

    // Export concatenated data
    const exportConcatenatedBtn = document.getElementById('export-concatenated-btn');
    if (exportConcatenatedBtn) {
        exportConcatenatedBtn.addEventListener('click', function () {
            // Send concatenated data to backend for XLSX generation
            fetch(`/groups/export_concatenated/${CONFIG.groupId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('input[name="csrf_token"]').value
                },
                body: JSON.stringify({ concatenated_data: concatenatedData })
            })
                .then(response => response.blob())
                .then(blob => {
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `concatenated_analytes_${CONFIG.groupId}.xlsx`;
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(url);
                    document.body.removeChild(a);
                })
                .catch(err => {
                    console.error('Export error:', err);
                    alert('Export failed.');
                });
        });
    }

    // --- Randomization Modal Logic ---
    const randModalEl = document.getElementById('randomizationModal');
    if (randModalEl) {
        // --- Element Cache ---
        const steps = {
            step1: document.getElementById('rand-step-1'),
            step2: document.getElementById('rand-step-2'),
            step3: document.getElementById('rand-step-3'),
            step4: document.getElementById('rand-step-4')
        };
        const randomizeBySelect = document.getElementById('randomize-by-select');
        const totalUnitsAvailableSpan = document.getElementById('total-units-available');
        const totalUnitsAvailableStep2Span = document.getElementById('total-units-available-step2');
        const totalUnitsAssignedSpan = document.getElementById('total-units-assigned');
        const treatmentGroupsContainer = document.getElementById('treatment-groups-container');
        const useBlindingCheckbox = document.getElementById('use-blinding-checkbox');
        const groupTemplate = document.getElementById('treatment-group-template');
        const assignmentMethodRadios = document.querySelectorAll('input[name="assignmentMethod"]');
        const minimizationOptions = document.getElementById('minimization-options');
        const allowSplittingCheckbox = document.getElementById('allow-splitting-checkbox');
        const minSubgroupSizeContainer = document.getElementById('min-subgroup-size-container');
        const minSubgroupSizeInput = document.getElementById('min-subgroup-size');
        const stratificationFactorSelect = document.getElementById('stratification-factor-select');
        const minimizeSourceSelect = document.getElementById('minimize-source');
        const minimizeAnimalModelParams = document.getElementById('minimize-animal-model-params');
        const minimizeDatatableParams = document.getElementById('minimize-datatable-params');
        const minimizeAnalyteAmSelect = document.getElementById('minimize-analyte-am');
        const minimizeDatatableSelect = document.getElementById('minimize-datatable-select');
        const minimizeAnalyteDtSelect = document.getElementById('minimize-analyte-dt');
        const randomizationSummaryDiv = document.getElementById('randomization-summary');

        const animalModelsDataEl = document.getElementById('animal-models-data');
        const animalModelsData = animalModelsDataEl ? JSON.parse(animalModelsDataEl.textContent) : [];
        const csrfToken = document.querySelector('input[name="csrf_token"]')?.value;

        let randomizationState = {};
        let datatableCache = [];

        // --- Core Functions ---
        function showRandStep(stepKey) {
            Object.values(steps).forEach(s => { if (s) s.style.display = 'none'; });
            if (steps[stepKey]) steps[stepKey].style.display = 'block';
        }

        function updateAvailableUnits() {
            const unitType = randomizeBySelect.value;
            const animalData = CONFIG.existingAnimalData.filter(animal => animal.status !== 'dead');
            let count = 0;

            if (allowSplittingCheckbox.checked || unitType === '__individual__') {
                count = animalData.length;
            } else {
                const uniqueValues = new Set();
                animalData.forEach(animal => {
                    const value = animal[unitType];
                    if (value !== undefined && value !== null && value !== '') {
                        uniqueValues.add(value);
                    }
                });
                count = uniqueValues.size;
            }

            totalUnitsAvailableSpan.textContent = count;
            totalUnitsAvailableStep2Span.textContent = count;

            if (unitType === '__individual__') {
                allowSplittingCheckbox.checked = false;
                allowSplittingCheckbox.disabled = true;
                minSubgroupSizeContainer.style.display = 'none';
            } else {
                allowSplittingCheckbox.disabled = false;
            }
        }

        function updateAssignedUnits() {
            let totalAssigned = 0;
            treatmentGroupsContainer.querySelectorAll('.unit-count').forEach(input => {
                totalAssigned += parseInt(input.value, 10) || 0;
            });
            totalUnitsAssignedSpan.textContent = totalAssigned;
        }

        function addTreatmentGroup(actual = '', blinded = '', count = 0) {
            if (!groupTemplate) return;
            const clone = groupTemplate.content.cloneNode(true);
            const row = clone.querySelector('.treatment-group-row');
            row.querySelector('.actual-name').value = actual;
            row.querySelector('.blinded-name').value = blinded;
            row.querySelector('.unit-count').value = count;
            row.querySelector('.remove-treatment-group-btn').addEventListener('click', () => { row.remove(); updateAssignedUnits(); });
            row.querySelector('.unit-count').addEventListener('input', updateAssignedUnits);
            treatmentGroupsContainer.appendChild(row);
            toggleBlindingFields();
            updateAssignedUnits();
        }

        function toggleBlindingFields() {
            const useBlinding = useBlindingCheckbox.checked;
            treatmentGroupsContainer.querySelectorAll('.treatment-group-row').forEach((row, index) => {
                const blindedNameInput = row.querySelector('.blinded-name');
                const actualNameCol = row.querySelector('.actual-name-col');
                const blindedNameCol = row.querySelector('.blinded-name-col');
                if (useBlinding) {
                    blindedNameInput.required = true;
                    blindedNameCol.style.display = '';
                    actualNameCol.classList.remove('col-8');
                    actualNameCol.classList.add('col');
                    if (!blindedNameInput.value) blindedNameInput.value = String.fromCharCode(65 + index);
                } else {
                    blindedNameInput.required = false;
                    blindedNameCol.style.display = 'none';
                    actualNameCol.classList.remove('col');
                    actualNameCol.classList.add('col-8');
                }
            });
        }

        function fetchGroupDataTables() {
            if (!CONFIG.urls.getGroupDatatablesForRandomization || CONFIG.urls.getGroupDatatablesForRandomization === '#') return;
            fetch(CONFIG.urls.getGroupDatatablesForRandomization)
                .then(res => res.json())
                .then(data => {
                    datatableCache = data;
                    minimizeDatatableSelect.innerHTML = '<option value="">-- Select DataTable --</option>';
                    data.forEach(dt => {
                        minimizeDatatableSelect.add(new Option(dt.text, dt.id));
                    });
                })
                .catch(error => console.error('Error fetching datatables:', error));
        }

        function populateSummaryModal(summaryData) {
            document.getElementById('summary-randomized-at').textContent = new Date(summaryData.randomized_at).toLocaleString();
            document.getElementById('summary-randomized-by').textContent = summaryData.randomized_by;

            // Populate Settings
            const settingsUl = document.getElementById('summary-settings-list');
            settingsUl.innerHTML = '';
            let unitText = summaryData.unit_of_randomization;
            if (unitText === '__individual__') {
                unitText = `Individual Animal`;
            }
            if (summaryData.allow_splitting) {
                unitText = `${unitText} (with cluster splitting allowed)`;
            }
            settingsUl.innerHTML += `<li><strong>Randomization Unit:</strong> ${unitText}</li>`;
            if (summaryData.stratification_factor) {
                settingsUl.innerHTML += `<li><strong>Primary Stratification:</strong> ${summaryData.stratification_factor}</li>`;
            }
            settingsUl.innerHTML += `<li><strong>Balancing Method:</strong> ${summaryData.assignment_method}</li>`;

            // Populate Baseline Data section
            const baselineContainer = document.getElementById('summary-baseline-data-container');
            const baselineDetails = document.getElementById('summary-baseline-data-details');
            if (summaryData.assignment_method === 'Minimization' && summaryData.minimization_details) {
                baselineContainer.style.display = 'block';
                const details = summaryData.minimization_details;
                let sourceText = `<strong>${details.analyte}</strong> from `;
                if (details.source === 'datatable' && details.source_url) {
                    sourceText += `<a href="${details.source_url}" target="_blank">${details.source_name}</a>`;
                } else {
                    sourceText += `the Animal Model`;
                }
                baselineDetails.innerHTML = sourceText;
            } else {
                baselineContainer.style.display = 'none';
            }

            // Populate Group Sizes
            const requestedUl = document.getElementById('summary-requested-group-sizes');
            requestedUl.innerHTML = '';
            for (const groupName in summaryData.requested_group_sizes) {
                requestedUl.innerHTML += `<li><strong>${groupName}:</strong> ${summaryData.requested_group_sizes[groupName]}</li>`;
            }

            const actualUl = document.getElementById('summary-actual-group-sizes');
            actualUl.innerHTML = '';
            for (const groupName in summaryData.actual_group_sizes) {
                actualUl.innerHTML += `<li><strong>${groupName}:</strong> ${summaryData.actual_group_sizes[groupName]}</li>`;
            }

            // Populate Minimization Results
            const minimizationResultsDiv = document.getElementById('summary-minimization-results');
            if (summaryData.minimization_summary && Object.keys(summaryData.minimization_summary).length > 0) {
                minimizationResultsDiv.style.display = 'block';
                const minimizationUl = document.getElementById('summary-minimization-list');
                minimizationUl.innerHTML = '';
                for (const groupName in summaryData.minimization_summary) {
                    const stats = summaryData.minimization_summary[groupName];
                    const mean = stats.mean.toFixed(2);
                    const sem = stats.sem.toFixed(2);
                    const n = stats.n;
                    minimizationUl.innerHTML += `<li><strong>${groupName}:</strong> ${mean} ± ${sem} (n=${n})</li>`;
                }
            } else {
                minimizationResultsDiv.style.display = 'none';
            }

            // Populate Blinding Key
            const blindingKeyDiv = document.getElementById('summary-blinding-key');
            if (summaryData.blinding_key) {
                blindingKeyDiv.style.display = 'block';
                const blindingKeyUl = document.getElementById('summary-blinding-list');
                blindingKeyUl.innerHTML = '';
                for (const blindedName in summaryData.blinding_key) {
                    blindingKeyUl.innerHTML += `<li><strong>${blindedName}:</strong> ${summaryData.blinding_key[blindedName]}</li>`;
                }
            } else {
                blindingKeyDiv.style.display = 'none';
            }
        }

        // --- Event Listeners ---
        randModalEl.addEventListener('show.bs.modal', () => {
            showRandStep('step1');

            const selectedModelId = $(modelSelect).val();
            const selectedModel = animalModelsData.find(m => String(m.id) === selectedModelId);

            randomizeBySelect.innerHTML = '<option value="__individual__">Individual Animal</option>';
            stratificationFactorSelect.innerHTML = '<option value="">None</option>';
            minimizeAnalyteAmSelect.innerHTML = '';

            if (selectedModel && selectedModel.analytes) {
                selectedModel.analytes.forEach(analyte => {
                    // Check for analytes that can be used for grouping/stratification
                    // Include INT and FLOAT as well for Cage IDs or similar
                    const isCategorical = analyte.data_type === 'text' || analyte.data_type === 'category' || analyte.data_type === 'int' || analyte.data_type === 'float';
                    if (isCategorical) {
                        randomizeBySelect.add(new Option(analyte.name, analyte.name));
                        stratificationFactorSelect.add(new Option(analyte.name, analyte.name));
                    }
                    // Check for continuous variables for minimization
                    if (analyte.data_type === 'float' || analyte.data_type === 'int') {
                        minimizeAnalyteAmSelect.add(new Option(analyte.name, analyte.name));
                    }
                });
            }

            updateAvailableUnits();
            treatmentGroupsContainer.innerHTML = '';
            addTreatmentGroup('', 'Group A', 0);
            addTreatmentGroup('', 'Group B', 0);
            fetchGroupDataTables();
        });

        randomizeBySelect.addEventListener('change', updateAvailableUnits);
        allowSplittingCheckbox.addEventListener('change', () => {
            minSubgroupSizeContainer.style.display = allowSplittingCheckbox.checked ? 'block' : 'none';
            updateAvailableUnits();
        });
        useBlindingCheckbox.addEventListener('change', toggleBlindingFields);
        document.getElementById('add-treatment-group-btn')?.addEventListener('click', () => addTreatmentGroup());

        assignmentMethodRadios.forEach(radio => {
            radio.addEventListener('change', () => {
                minimizationOptions.style.display = (radio.value === 'Minimization') ? 'block' : 'none';
            });
        });

        minimizeSourceSelect.addEventListener('change', function () {
            const isAM = this.value === 'animal_model';
            minimizeAnimalModelParams.style.display = isAM ? 'block' : 'none';
            minimizeDatatableParams.style.display = isAM ? 'none' : 'block';
            if (!isAM && datatableCache.length === 0) {
                fetchGroupDataTables();
            }
        });

        minimizeDatatableSelect.addEventListener('change', function () {
            const dtId = this.value;
            minimizeAnalyteDtSelect.innerHTML = '';
            if (dtId) {
                const selectedDt = datatableCache.find(dt => String(dt.id) === dtId);
                if (selectedDt && selectedDt.analytes) {
                    selectedDt.analytes.forEach(analyte => {
                        minimizeAnalyteDtSelect.add(new Option(analyte.name, analyte.name));
                    });
                }
            }
        });

        // Navigation
        document.getElementById('rand-next-to-step-2')?.addEventListener('click', () => showRandStep('step2'));
        document.getElementById('rand-back-to-step-1')?.addEventListener('click', () => showRandStep('step1'));

        document.getElementById('rand-next-to-step-3')?.addEventListener('click', () => {
            const totalAssigned = parseInt(totalUnitsAssignedSpan.textContent, 10);
            const totalAvailable = parseInt(totalUnitsAvailableStep2Span.textContent, 10);
            if (totalAssigned !== totalAvailable) {
                alert("The total number of units/animals assigned must exactly match the total available.");
                return;
            }
            showRandStep('step3');
        });
        document.getElementById('rand-back-to-step-2')?.addEventListener('click', () => showRandStep('step2'));

        document.getElementById('rand-next-to-step-4')?.addEventListener('click', () => {
            let summary = [];
            let unitText;

            if (allowSplittingCheckbox.checked) {
                unitText = `individual animals, balanced by <strong>${randomizeBySelect.value}</strong>`;
            } else {
                unitText = `<strong>${randomizeBySelect.options[randomizeBySelect.selectedIndex].text}</strong>`;
            }

            summary.push(`You are randomizing <strong>${totalUnitsAvailableStep2Span.textContent}</strong> ${unitText}.`);

            if (stratificationFactorSelect.value) {
                summary.push(`Animals will be stratified by <strong>${stratificationFactorSelect.value}</strong> first.`);
            }

            const method = document.querySelector('input[name="assignmentMethod"]:checked').value;
            if (method === 'Minimization') {
                const analyte = minimizeSourceSelect.value === 'animal_model' ? minimizeAnalyteAmSelect.value : minimizeAnalyteDtSelect.value;
                if (!analyte) {
                    alert("Please select a parameter for minimization.");
                    return;
                }
                summary.push(`Groups will be balanced using <strong>Minimization</strong> on the <strong>${analyte}</strong> parameter.`);
            } else {
                summary.push(`Groups will be assigned using a <strong>Simple</strong> randomization method.`);
            }

            randomizationSummaryDiv.innerHTML = summary.join('<br>');
            showRandStep('step4');
        });
        document.getElementById('rand-back-to-step-3')?.addEventListener('click', () => showRandStep('step3'));

        // Final confirmation
        document.getElementById('rand-confirm-btn')?.addEventListener('click', function () {
            randomizationState = {
                randomization_unit: randomizeBySelect.value,
                allow_splitting: allowSplittingCheckbox.checked,
                min_subgroup_size: minSubgroupSizeInput.value,
                stratification_factor: stratificationFactorSelect.value,
                use_blinding: useBlindingCheckbox.checked,
                assignment_method: document.querySelector('input[name="assignmentMethod"]:checked').value,
                treatment_groups: [],
                minimization_details: null
            };

            if (randomizationState.assignment_method === 'Minimization') {
                const source = minimizeSourceSelect.value;
                const analyte = source === 'animal_model' ? minimizeAnalyteAmSelect.value : minimizeAnalyteDtSelect.value;
                randomizationState.minimization_details = { source: source, analyte: analyte };
                if (source === 'datatable') {
                    randomizationState.minimization_details.datatable_id = minimizeDatatableSelect.value;
                }
            }

            treatmentGroupsContainer.querySelectorAll('.treatment-group-row').forEach(row => {
                randomizationState.treatment_groups.push({
                    actual_name: row.querySelector('.actual-name').value.trim(),
                    blinded_name: row.querySelector('.blinded-name').value.trim(),
                    count: parseInt(row.querySelector('.unit-count').value, 10)
                });
            });

            this.disabled = true;
            this.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Processing...`;
            fetch(CONFIG.urls.randomizeGroup, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
                body: JSON.stringify(randomizationState)
            })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        fetch(CONFIG.urls.getRandomizationSummary)
                            .then(res => res.json())
                            .then(summaryData => {
                                populateSummaryModal(summaryData);

                                const randModal = bootstrap.Modal.getInstance(randModalEl);
                                randModal.hide();
                                const summaryModal = new bootstrap.Modal(document.getElementById('randomizationSummaryModal'));
                                summaryModal.show();
                            })
                            .catch(error => {
                                console.error('Error fetching randomization summary:', error);
                                alert("Randomization was successful, but failed to load the summary. Please reload the page to see the results.");
                                window.location.reload();
                            });
                    } else {
                        alert("Error: " + data.message);
                        this.disabled = false;
                        this.innerHTML = `Confirm & Randomize`;
                    }
                })
                .catch(error => {
                    console.error('Error during randomization:', error);
                    alert("An unexpected error occurred during randomization.");
                    this.disabled = false;
                    this.innerHTML = `Confirm & Randomize`;
                });
        });
    }

    // --- Randomization UI Actions ---
    const viewSummaryBtn = document.getElementById('view-randomization-summary-btn-dropdown');
    if (viewSummaryBtn) {
        viewSummaryBtn.addEventListener('click', function () {
            fetch(CONFIG.urls.getRandomizationSummary)
                .then(res => res.json())
                .then(summaryData => {
                    populateSummaryModal(summaryData);
                    const summaryModal = new bootstrap.Modal(document.getElementById('randomizationSummaryModal'));
                    summaryModal.show();
                })
                .catch(error => console.error('Error fetching summary:', error));
        });
    }

    const unblindBtn = document.getElementById('unblind-randomization-btn-dropdown');
    if (unblindBtn) {
        unblindBtn.addEventListener('click', function () {
            if (confirm("Are you sure you want to unblind this group? This will keep the randomization and groups, but make assignments visible.")) {
                fetch(CONFIG.urls.unblindGroup, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': document.querySelector('input[name="csrf_token"]').value }
                }).then(response => {
                    if (response.ok) location.reload();
                    else alert("An error occurred while unblinding the group.");
                });
            }
        });
    }

    const deleteRandomizationBtn = document.getElementById('delete-randomization-btn-dropdown') || document.getElementById('delete-randomization-btn');
    if (deleteRandomizationBtn) {
        deleteRandomizationBtn.addEventListener('click', function () {
            if (confirm("Are you sure you want to delete the randomization? This will remove randomization details and assigned groups, reverting to a pre-randomized state.")) {
                fetch(CONFIG.urls.deleteRandomization, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': document.querySelector('input[name="csrf_token"]').value }
                }).then(response => {
                    if (response.ok) location.reload();
                    else alert("An error occurred while deleting the randomization.");
                });
            }
        });
    }

    const summaryModalCloseBtn = document.getElementById('summary-modal-close-btn');
    if (summaryModalCloseBtn) {
        summaryModalCloseBtn.addEventListener('click', () => window.location.reload());
    }

});

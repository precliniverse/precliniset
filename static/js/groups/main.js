import { AnimalTable } from './table_manager.js';
import { Randomizer } from './randomization.js';
import { DeathManager } from './death_manager.js';
import { ConcatenationManager } from './concatenation_manager.js';

document.addEventListener('DOMContentLoaded', () => {
    // 1. Parse Config
    const configEl = document.getElementById('group-config');
    if (!configEl) {
        console.error("Group Config element (id='group-config') not found!");
        return;
    }
    const CONFIG = JSON.parse(configEl.dataset.config);

    console.log("Initializing Group Editor with Config:", CONFIG);

    // --- Helper to fetch fields ---
    async function fetchModelFields(projectId, modelId) {
        if (CONFIG.modelFields && CONFIG.modelFields.length > 0) {
            return CONFIG.modelFields;
        }
        return []; 
    }

    // --- State ---
    let currentFields = [];

    // --- 2. Initialize Components ---
    const animalTable = new AnimalTable('#animal-data-table', CONFIG);
    const randomizer = new Randomizer(CONFIG);
    const deathManager = new DeathManager();
    const concatenationManager = new ConcatenationManager(CONFIG);

    // --- 2.5 Initialize Select2 (Project, Model, EA) ---
    const projectSelect = $('#project_select');
    const modelSelect = $('#model_select');
    const eaSelect = $('#ethical_approval_select');

    if (projectSelect.length) {
        projectSelect.select2({
            theme: "bootstrap-5",
            width: '100%',
            placeholder: CONFIG.i18n.selectProject || "Select Project...",
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

        projectSelect.on('select2:select', function (e) {
            const projectId = e.params.data.id;
            updateEADropdown(projectId);
        });
    }

    if (modelSelect.length) {
        modelSelect.select2({
            theme: "bootstrap-5",
            width: '100%',
            allowClear: true
        });
    }

    if (eaSelect.length) {
        eaSelect.select2({
            theme: "bootstrap-5",
            width: '100%',
            allowClear: true
        });
    }

    function updateEADropdown(projectId) {
        if (!eaSelect.length) return;
        
        const currentVal = eaSelect.val();

        eaSelect.empty().append(new Option(CONFIG.i18n.selectEA || "Select Ethical Approval...", ''));

        if (!projectId || projectId === '0') {
            eaSelect.prop('disabled', true);
            eaSelect.trigger('change');
            return;
        }

        eaSelect.prop('disabled', false);
        fetch(CONFIG.urls.getEthicalApprovalsForProject.replace('0', projectId))
            .then(response => response.json())
            .then(data => {
                data.forEach(ea => {
                    const newOption = new Option(ea.text, ea.id, false, false);
                    eaSelect.append(newOption);
                });
                
                const targetId = CONFIG.ethicalApprovalId || currentVal;
                if (targetId) {
                    eaSelect.val(targetId);
                }
                eaSelect.trigger('change');
            })
            .catch(err => console.error("Error updating EA dropdown:", err));
    }

    // --- 3. Initial project-based state ---
    if (projectSelect.length) {
        const initialProjectId = projectSelect.val();
        if (initialProjectId && initialProjectId !== '0') {
            updateEADropdown(initialProjectId);
        }
    }

    // --- 3.5 Initial Data Load ---
    if (CONFIG.modelFields) {
        currentFields = CONFIG.modelFields;
        animalTable.updateTableHeader(currentFields);
        
        if (CONFIG.existingAnimalData) {
            CONFIG.existingAnimalData.forEach(animal => {
                animalTable.addAnimalRow(animal, currentFields);
            });
        }
    }

    // --- 4. Event Listeners ---
    
    // Add Animal Button
    const addAnimalContainer = document.getElementById('add-animal-button-container');
    if (addAnimalContainer && currentFields.length > 0) {
        const btn = document.createElement('button');
        btn.className = 'btn btn-success btn-sm';
        btn.innerHTML = `<i class="fas fa-plus me-1"></i> ${CONFIG.i18n.addAnimal}`;
        btn.addEventListener('click', () => {
            animalTable.addAnimalRow({}, currentFields);
        });
        addAnimalContainer.appendChild(btn);
    }
    
    // Model Change Listener (for new groups)
    $('#model_select').on('change', async function() {
        const modelId = $(this).val();
        if(!modelId || modelId === '0') return;

        try {
            const url = CONFIG.urls.getModelFields.replace('0', modelId);
            const response = await fetch(url);
            const fields = await response.json();
            
            currentFields = fields;
            animalTable.clearRows();
            animalTable.updateTableHeader(fields);
            
            // Re-render Add Button
            addAnimalContainer.innerHTML = '';
            const btn = document.createElement('button');
            btn.className = 'btn btn-success btn-sm';
            btn.innerHTML = `<i class="fas fa-plus me-1"></i> ${CONFIG.i18n.addAnimal}`;
            btn.addEventListener('click', () => {
                animalTable.addAnimalRow({}, currentFields);
            });
            addAnimalContainer.appendChild(btn);
            
            // Allow template download
             const downloadBtn = document.getElementById('download-data-btn');
             if(downloadBtn) {
                 downloadBtn.href = CONFIG.urls.downloadTemplate.replace('0', modelId);
                 downloadBtn.removeAttribute('disabled');
             }

        } catch (e) {
            console.error("Error fetching model fields:", e);
        }
    });

    // Duplicate Handling (Delegated)
    document.getElementById('animal-data-table').addEventListener('click', (e) => {
        const target = e.target.closest('.duplicate-row-btn');
        if (target) {
            const tr = target.closest('tr');
            const inputs = tr.querySelectorAll('input, select');
            const rowData = {};
            
            inputs.forEach(input => {
                const parts = input.name.split('_field_');
                if (parts.length === 2) {
                    const fieldName = parts[1];
                    if (fieldName !== 'ID') rowData[fieldName] = input.value;
                }
            });
            
            animalTable.addAnimalRow(rowData, currentFields);
        }
    });

    // --- 5. Validation & Save Logic ---
    function validateForm() {
        let isValid = true;
        document.querySelectorAll('.is-invalid').forEach(el => el.classList.remove('is-invalid'));
        document.querySelectorAll('.invalid-feedback').forEach(el => el.remove());

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

        const nameInput = document.querySelector('input[name=name]');
        if (!nameInput.value.trim()) {
            isValid = false;
            nameInput.classList.add('is-invalid');
            if (!nameInput.nextElementSibling || !nameInput.nextElementSibling.classList.contains('invalid-feedback')) {
                 const div = document.createElement('div');
                 div.className = 'invalid-feedback d-block';
                 div.textContent = 'Group Name is required.';
                 nameInput.parentNode.appendChild(div);
            }
        }
        return isValid;
    }

    const saveBtn = document.getElementById('save-group-btn');
    const groupForm = document.getElementById('group-form');
    
    if (saveBtn) {
        saveBtn.addEventListener('click', function(e) {
            e.preventDefault();
            if (validateForm()) {
                if (CONFIG.isEditing) {
                    $('#saveConfirmationModal').modal('show');
                } else {
                    performAjaxSave(false);
                }
            }
        });
    }

    const confirmSaveBtn = document.getElementById('confirm-save-group');
    if (confirmSaveBtn) {
        confirmSaveBtn.addEventListener('click', function() {
            const dontUpdate = document.getElementById('dont-update-datatables').checked;
            performAjaxSave(dontUpdate);
        });
    }

    function performAjaxSave(dontUpdateDataTables, allowNewCategories = false) {
        const formData = new FormData(groupForm);
        formData.append('is_ajax', 'true');
        if (dontUpdateDataTables) formData.append('update_data_tables', 'no');
        if (allowNewCategories) formData.append('allow_new_categories', 'true');
        
        const animalData = animalTable.getData();
        formData.append('animal_data', JSON.stringify(animalData));

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
                handleNewCategoriesDiscovered(data.map, dontUpdateDataTables);
            } else {
                alert(data.message || "Error saving group.");
            }
             $('#saveConfirmationModal').modal('hide');
        })
        .catch(error => {
            console.error('Error during AJAX save:', error);
            alert("An error occurred while saving.");
        });
    }

    function handleNewCategoriesDiscovered(categoriesMap, dontUpdateDataTables) {
        const listContainer = document.getElementById('new-categories-list');
        listContainer.innerHTML = '';
        
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
            modalBody.textContent = "New values found for categorical fields. Permission denied to update system values.";
        } else {
            confirmBtn.style.display = 'inline-block';
            modalBody.textContent = "New values found. Add them to the system and proceed?";
            
            const newConfirmBtn = confirmBtn.cloneNode(true);
            confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
            
            newConfirmBtn.addEventListener('click', () => {
                performAjaxSave(dontUpdateDataTables, true);
            });
        }
        const modal = new bootstrap.Modal(modalEl);
        modal.show();
    }
});

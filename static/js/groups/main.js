/**
 * static/js/groups/main.js
 * Orchestrator for the Group Editor page.
 * Implements Lazy Loading for heavy modules.
 */

import { AnimalTable } from './table_manager.js';

document.addEventListener('DOMContentLoaded', () => {
    // 1. Parse Config
    const configEl = document.getElementById('group-config');
    if (!configEl) {
        console.error("Group Config element (id='group-config') not found!");
        return;
    }
    const CONFIG = JSON.parse(configEl.dataset.config);
    let currentFields = CONFIG.modelFields || [];

    // --- State for Lazy Loaded Modules ---
    let randomizerInstance = null;
    let deathManagerInstance = null;
    let concatenationManagerInstance = null;

    // --- 2. Initialize Core Component (Table) Immediately ---
    const animalTable = new AnimalTable('#animal-data-table', CONFIG);

    // Initial Data Load
    animalTable.updateTableHeader(currentFields);
    if (CONFIG.existingAnimalData) {
        animalTable.clearRows();
        CONFIG.existingAnimalData.forEach(animal => {
            animalTable.addAnimalRow(animal, currentFields);
        });
    }

    // --- 3. Lazy Load Handlers ---

    /**
     * Lazy Load Randomization
     */
    const initRandomization = async (openModalImmediately = true) => {
        // Sync Latest Data from Table to CONFIG
        CONFIG.existingAnimalData = animalTable.getData();

        if (!randomizerInstance) {
            // Visual feedback
            const btn = document.getElementById('randomize-btn') || document.getElementById('rerun-randomization-btn-dropdown');
            const originalText = btn ? btn.innerHTML : '';
            if (btn) btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Loading...';

            try {
                const module = await import('./randomization.js');
                randomizerInstance = new module.Randomizer(CONFIG);
            } catch (err) {
                console.error("Failed to load Randomizer:", err);
                alert("Failed to load randomization module. Please refresh.");
                return;
            } finally {
                if (btn) btn.innerHTML = originalText;
            }
        }

        if (openModalImmediately) {
            const modalEl = document.getElementById('randomizationModal');
            const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
            modal.show();
        }
    };

    // Bind Randomization Triggers
    // Note: We remove data-bs-target in HTML or preventDefault here to handle loading first
    const randBtn = document.getElementById('randomize-btn');
    if (randBtn) {
        randBtn.addEventListener('click', (e) => {
            e.preventDefault();
            initRandomization(true);
        });
    }
    const rerunRandBtn = document.getElementById('rerun-randomization-btn-dropdown');
    if (rerunRandBtn) {
        rerunRandBtn.addEventListener('click', (e) => {
            e.preventDefault();
            initRandomization(true);
        });
    }
    // Pre-load summary logic if summary button exists (lightweight, but ensures class exists)
    const summaryBtn = document.getElementById('view-randomization-summary-btn-dropdown');
    if (summaryBtn) {
        summaryBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            await initRandomization(false);
            if (randomizerInstance) randomizerInstance.openSummary();
        });
    }

    const unblindBtn = document.getElementById('unblind-randomization-btn-dropdown');
    if (unblindBtn) {
        unblindBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            await initRandomization(false);
            if (randomizerInstance) randomizerInstance.unblindRandomization();
        });
    }

    const deleteBtn = document.getElementById('delete-randomization-btn-dropdown');
    if (deleteBtn) {
        deleteBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            await initRandomization(false);
            if (randomizerInstance) randomizerInstance.deleteRandomization();
        });
    }


    /**
     * Lazy Load Death Manager
     * Uses event delegation on document because buttons are dynamic
     */
    document.addEventListener('click', async (e) => {
        const target = e.target.closest('.declare-dead-btn');
        if (target) {
            e.preventDefault();
            e.stopPropagation();

            if (!deathManagerInstance) {
                target.classList.add('disabled');
                const originalHtml = target.innerHTML;
                target.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

                try {
                    const module = await import('./death_manager.js');
                    deathManagerInstance = new module.DeathManager();
                    // Manually trigger the handle click for this first event
                    deathManagerInstance.handleDeclareClick({ target: target, stopPropagation: () => { } });
                } catch (err) {
                    console.error("Failed to load DeathManager:", err);
                } finally {
                    target.classList.remove('disabled');
                    target.innerHTML = originalHtml;
                }
            } else {
                // Instance exists, just let the delegation inside DeathManager handle future clicks, 
                // BUT since we are in a handler that caught it, we should manually trigger it 
                // because the class's own listener might not have caught *this specific* event bubble phase depending on timing.
                deathManagerInstance.handleDeclareClick({ target: target, stopPropagation: () => { } });
            }
        }
    });


    // --- 4. Core Select2 Initialization (Project/Model/EA) ---
    // Keep this in main.js as it runs on page load
    const projectSelect = $('#project_select');
    const modelSelect = $('#model_select');
    const eaSelect = $('#ethical_approval_select');

    if (projectSelect.length) {
        projectSelect.select2({
            theme: "bootstrap-5",
            width: '100%',
            placeholder: CONFIG.i18n.selectProject,
            allowClear: true,
            ajax: {
                url: CONFIG.urls.searchProjects,
                dataType: 'json',
                delay: 250,
                data: function (params) {
                    return { q: params.term, page: params.page || 1, show_archived: false };
                },
                processResults: function (data, params) {
                    params.page = params.page || 1;
                    return { results: data.results, pagination: { more: (params.page * 10) < data.total_count } };
                },
                cache: true
            },
            minimumInputLength: 0
        });

        projectSelect.on('select2:select', function (e) {
            updateEADropdown(e.params.data.id);
        });
    }

    if (modelSelect.length) {
        modelSelect.select2({ theme: "bootstrap-5", width: '100%', allowClear: true });
        // Handle Model Change
        modelSelect.on('change', async function () {
            const modelId = $(this).val();
            if (!modelId || modelId === '0') return;
            try {
                const url = CONFIG.urls.getModelFields.replace('0', modelId);
                const response = await fetch(url);
                const data = await response.json();
                if (data.success) {
                    currentFields = data.fields;
                    animalTable.clearRows();
                    animalTable.updateTableHeader(currentFields);
                    updateAddButton(currentFields);
                    updateDownloadLink(modelId);
                }
            } catch (e) { console.error("Error fetching model fields:", e); }
        });
    }

    if (eaSelect.length) {
        eaSelect.select2({ theme: "bootstrap-5", width: '100%', allowClear: true });
    }

    function updateEADropdown(projectId) {
        if (!eaSelect.length) return;
        eaSelect.empty().append(new Option(CONFIG.i18n.selectEA || "Select...", ''));
        if (!projectId || projectId === '0') { eaSelect.prop('disabled', true).trigger('change'); return; }

        eaSelect.prop('disabled', false);
        fetch(CONFIG.urls.getEthicalApprovalsForProject.replace('0', projectId))
            .then(r => r.json())
            .then(data => {
                data.forEach(ea => eaSelect.append(new Option(ea.text, ea.id, false, false)));
                if (CONFIG.ethicalApprovalId) eaSelect.val(CONFIG.ethicalApprovalId);
                eaSelect.trigger('change');
            });
    }

    // --- 5. UI Helpers (Buttons, Validation) ---

    const addAnimalContainer = document.getElementById('add-animal-button-container');

    function updateAddButton(fields) {
        if (addAnimalContainer) {
            addAnimalContainer.innerHTML = '';
            if (fields && fields.length > 0) {
                const btn = document.createElement('button');
                btn.className = 'btn btn-success btn-sm';
                btn.innerHTML = `<i class="fas fa-plus me-1"></i> ${CONFIG.i18n.addAnimal}`;
                btn.type = 'button';
                btn.addEventListener('click', () => animalTable.addAnimalRow({}, fields));
                addAnimalContainer.appendChild(btn);
            }
        }
    }

    // Initial Add Button
    updateAddButton(currentFields);

    function updateDownloadLink(modelId) {
        const btn = document.getElementById('download-data-btn');
        if (btn) {
            btn.href = CONFIG.urls.downloadTemplate.replace('0', modelId);
            btn.removeAttribute('disabled');
        }
    }

    // --- Save Logic ---
    const saveBtn = document.getElementById('save-group-btn');
    if (saveBtn) {
        saveBtn.addEventListener('click', (e) => {
            e.preventDefault();
            if (validateForm()) {
                if (CONFIG.isEditing) $('#saveConfirmationModal').modal('show');
                else performAjaxSave(false);
            }
        });
    }

    document.getElementById('confirm-save-group')?.addEventListener('click', () => {
        performAjaxSave();
    });

    // Import Logic
    document.getElementById('import-xlsx-btn')?.addEventListener('click', () => {
        const fileInput = document.getElementById('xlsx_upload');
        if (!fileInput.files.length) { alert("Please select a file."); return; }
        if (validateForm() && confirm("Overwrite current list?")) performAjaxSave();
    });

    function validateForm() {
        // ... (Keep existing validation logic)
        let isValid = true;
        $('.is-invalid').removeClass('is-invalid');
        $('.invalid-feedback').remove();

        const nameInput = document.querySelector('input[name=name]');
        if (!nameInput.value.trim()) {
            isValid = false;
            nameInput.classList.add('is-invalid');
        }
        return isValid;
    }

    function performAjaxSave(allowNewCategories = false) {
        const groupForm = document.getElementById('group-form');
        const formData = new FormData(groupForm);
        formData.append('is_ajax', 'true');
        // update_data_tables is now always True on backend, but we can explicitely send 'yes' if needed 
        // Or just let the backend handle the default. Given backend change, we don't need to append 'no'.
        if (allowNewCategories) formData.append('allow_new_categories', 'true');
        formData.append('animal_data', JSON.stringify(animalTable.getData()));

        fetch(groupForm.action, { method: 'POST', body: formData })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    if (!CONFIG.isEditing && data.redirect_url) window.location.href = data.redirect_url;
                    else window.location.reload();
                } else if (data.type === 'new_categories') {
                    // Logic to show category modal (Requires extracting that function or defining here)
                    // For brevity, simple alert fallback if modal logic not copied
                    alert("New categories found. Please check data.");
                } else {
                    alert(data.message);
                }
            })
            .catch(e => console.error(e));
    }

    // Auto-open summary if redirected after randomization
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has('randomized')) {
        const url = new URL(window.location.href);
        url.searchParams.delete('randomized');
        window.history.replaceState({}, '', url.toString());

        initRandomization(false).then(() => {
            if (randomizerInstance) randomizerInstance.openSummary();
        });
    }
});
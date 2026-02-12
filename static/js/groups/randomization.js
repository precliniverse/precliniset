/**
 * static/js/groups/randomization.js
 * Handles the logic for the Randomization Modal and related actions.
 */

export class Randomizer {
    constructor(config) {
        this.config = config;
        this.modalEl = document.getElementById('randomizationModal');

        // State
        this.datatableCache = [];
        this.randomizationState = {};

        // Elements Cache
        this.elements = {
            steps: {
                step1: document.getElementById('rand-step-1'),
                step2: document.getElementById('rand-step-2'),
                step3: document.getElementById('rand-step-3'),
                step4: document.getElementById('rand-step-4')
            },
            randomizeBySelect: document.getElementById('randomize-by-select'),
            totalUnitsAvailableSpan: document.getElementById('total-units-available'),
            totalUnitsAvailableStep2Span: document.getElementById('total-units-available-step2'),
            totalUnitsAssignedSpan: document.getElementById('total-units-assigned'),
            treatmentGroupsContainer: document.getElementById('treatment-groups-container'),
            useBlindingCheckbox: document.getElementById('use-blinding-checkbox'),
            assignmentMethodRadios: document.querySelectorAll('input[name="assignmentMethod"]'),
            minimizationOptions: document.getElementById('minimization-options'),
            allowSplittingCheckbox: document.getElementById('allow-splitting-checkbox'),
            minSubgroupSizeContainer: document.getElementById('min-subgroup-size-container'),
            minSubgroupSizeInput: document.getElementById('min-subgroup-size'),
            stratificationFactorSelect: document.getElementById('stratification-factor-select'),
            minimizeSourceSelect: document.getElementById('minimize-source'),
            minimizeAnimalModelParams: document.getElementById('minimize-animal-model-params'),
            minimizeDatatableParams: document.getElementById('minimize-datatable-params'),
            minimizeAnalyteAmSelect: document.getElementById('minimize-analyte-am'),
            minimizeDatatableSelect: document.getElementById('minimize-datatable-select'),
            minimizeAnalyteDtSelect: document.getElementById('minimize-analyte-dt'),
            randomizationSummaryDiv: document.getElementById('randomization-summary')
        };

        // FIX: Use the config passed from main.js instead of re-parsing DOM
        this.animalModelsData = this.config.animalModels || [];

        this.init();
    }

    init() {
        if (!this.modalEl) return;

        // Bind Context
        this.showRandStep = this.showRandStep.bind(this);
        this.updateAvailableUnits = this.updateAvailableUnits.bind(this);
        this.addTreatmentGroup = this.addTreatmentGroup.bind(this);
        this.toggleBlindingFields = this.toggleBlindingFields.bind(this);
        this.updateAssignedUnits = this.updateAssignedUnits.bind(this);
        this.fetchGroupDataTables = this.fetchGroupDataTables.bind(this);
        this.submitRandomization = this.submitRandomization.bind(this);
        this.generatePreStatusSummary = this.generatePreStatusSummary.bind(this);

        // Listeners
        this.modalEl.addEventListener('show.bs.modal', () => this.onShow());

        this.elements.randomizeBySelect.addEventListener('change', this.updateAvailableUnits);
        this.elements.allowSplittingCheckbox.addEventListener('change', () => {
            this.elements.minSubgroupSizeContainer.style.display = this.elements.allowSplittingCheckbox.checked ? 'block' : 'none';
            this.updateAvailableUnits();
        });

        this.elements.useBlindingCheckbox.addEventListener('change', this.toggleBlindingFields);
        document.getElementById('add-treatment-group-btn')?.addEventListener('click', () => this.addTreatmentGroup());

        this.elements.assignmentMethodRadios.forEach(radio => {
            radio.addEventListener('change', () => {
                this.elements.minimizationOptions.style.display = (radio.value === 'Minimization') ? 'block' : 'none';
            });
        });

        this.elements.minimizeSourceSelect.addEventListener('change', (e) => this.handleMinimizeSourceChange(e));
        this.elements.minimizeDatatableSelect.addEventListener('change', (e) => this.handleDatatableSelectChange(e));

        // Navigation
        this.setupNavigation();

        // Summary Actions
        this.setupSummaryActions();
    }
    openSummary() {
        fetch(this.config.urls.getRandomizationSummary)
            .then(res => res.json())
            .then(summaryData => {
                this.populateSummaryModal(summaryData);
                const summaryModal = new bootstrap.Modal(document.getElementById('randomizationSummaryModal'));
                summaryModal.show();
            })
            .catch(error => console.error('Error fetching summary:', error));
    }

    onShow() {
        this.showRandStep('step1');

        const selectedModelId = $('#model_select').val();
        // Ensure ID types match (string vs int)
        const selectedModel = this.animalModelsData.find(m => String(m.id) === String(selectedModelId));

        // Reset Dropdowns
        this.elements.randomizeBySelect.innerHTML = '<option value="__individual__">Individual Animal</option>';
        this.elements.stratificationFactorSelect.innerHTML = '<option value="">None</option>';
        this.elements.minimizeAnalyteAmSelect.innerHTML = '';

        if (selectedModel && selectedModel.analytes) {
            selectedModel.analytes.forEach(analyte => {
                // Populate "Randomize By" with categorical/text fields (e.g., Cage, Sex)
                // Note: type values are usually lowercase in DB but might vary, convert to check
                const type = (analyte.data_type || analyte.type || '').toLowerCase();

                if (['text', 'category', 'int'].includes(type)) {
                    // Check if we actually have data for this field in the current group
                    const hasData = this.config.existingAnimalData.some(a =>
                        a[analyte.name] !== undefined && a[analyte.name] !== null && a[analyte.name] !== ''
                    );

                    if (hasData) {
                        this.elements.randomizeBySelect.add(new Option(analyte.name, analyte.name));
                        this.elements.stratificationFactorSelect.add(new Option(analyte.name, analyte.name));
                    }
                }

                // Populate Minimization params (Must be numeric)
                if (['float', 'int'].includes(type)) {
                    this.elements.minimizeAnalyteAmSelect.add(new Option(analyte.name, analyte.name));
                }
            });
        }

        this.updateAvailableUnits();
        this.elements.treatmentGroupsContainer.innerHTML = '';
        this.addTreatmentGroup('', 'Group A', 0);
        this.addTreatmentGroup('', 'Group B', 0);
        this.fetchGroupDataTables();
    }

    showRandStep(stepKey) {
        Object.values(this.elements.steps).forEach(s => { if (s) s.style.display = 'none'; });
        if (this.elements.steps[stepKey]) this.elements.steps[stepKey].style.display = 'block';
    }

    updateAvailableUnits() {
        // Récupérer les animaux depuis la table au lieu de this.config.existingAnimalData
        const tableEl = document.getElementById('animal-data-table');
        const tbody = tableEl.querySelector('tbody');
        const animalRows = tbody.querySelectorAll('tr');

        const animalData = Array.from(animalRows).map(row => {
            const rowData = {};
            row.querySelectorAll('input, select').forEach(input => {
                if (input.name && input.name.includes('_field_')) {
                    const parts = input.name.split('_field_');
                    if (parts.length === 2) {
                        rowData[parts[1]] = input.value;
                    }
                }
            });
            // Vérifier le status (mais dans la table, les animaux morts sont en rouge mais on n'a pas de champ status visible)
            // On suppose pour l'instant que tous les animaux dans la table sont vivants
            rowData.status = 'alive';
            return rowData;
        });

        const unitType = this.elements.randomizeBySelect.value;
        let count = 0;

        if (this.elements.allowSplittingCheckbox.checked || unitType === '__individual__') {
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

        this.elements.totalUnitsAvailableSpan.textContent = count;
        this.elements.totalUnitsAvailableStep2Span.textContent = count;

        if (unitType === '__individual__') {
            this.elements.allowSplittingCheckbox.checked = false;
            this.elements.allowSplittingCheckbox.disabled = true;
            this.elements.minSubgroupSizeContainer.style.display = 'none';
        } else {
            this.elements.allowSplittingCheckbox.disabled = false;
        }
    }

    addTreatmentGroup(actual = '', blinded = '', count = 0) {
        const groupTemplate = document.getElementById('treatment-group-template');
        if (!groupTemplate) return;
        const clone = groupTemplate.content.cloneNode(true);
        const row = clone.querySelector('.treatment-group-row');

        row.querySelector('.actual-name').value = actual;
        row.querySelector('.blinded-name').value = blinded;
        row.querySelector('.unit-count').value = count;

        // Auto-fill blinded name if empty based on index (A, B, C...)
        if (!blinded) {
            const existingRows = this.elements.treatmentGroupsContainer.querySelectorAll('.treatment-group-row');
            row.querySelector('.blinded-name').value = String.fromCharCode(65 + existingRows.length);
        }

        row.querySelector('.remove-treatment-group-btn').addEventListener('click', () => {
            row.remove();
            this.updateAssignedUnits();
        });
        row.querySelector('.unit-count').addEventListener('input', this.updateAssignedUnits);

        this.elements.treatmentGroupsContainer.appendChild(row);
        this.toggleBlindingFields();
        this.updateAssignedUnits();
    }

    toggleBlindingFields() {
        const useBlinding = this.elements.useBlindingCheckbox.checked;
        this.elements.treatmentGroupsContainer.querySelectorAll('.treatment-group-row').forEach((row, index) => {
            const blindedNameInput = row.querySelector('.blinded-name');
            const actualNameCol = row.querySelector('.actual-name-col');
            const blindedNameCol = row.querySelector('.blinded-name-col');

            if (useBlinding) {
                blindedNameInput.required = true;
                blindedNameCol.classList.remove('d-none');
                actualNameCol.classList.remove('col-8');
                actualNameCol.classList.add('col');
            } else {
                blindedNameInput.required = false;
                blindedNameCol.classList.add('d-none');
                actualNameCol.classList.remove('col');
                actualNameCol.classList.add('col-8');
            }
        });
    }

    updateAssignedUnits() {
        let totalAssigned = 0;
        this.elements.treatmentGroupsContainer.querySelectorAll('.unit-count').forEach(input => {
            totalAssigned += parseInt(input.value, 10) || 0;
        });
        this.elements.totalUnitsAssignedSpan.textContent = totalAssigned;
    }

    fetchGroupDataTables() {
        if (!this.config.urls.getGroupDatatablesForRandomization || this.config.urls.getGroupDatatablesForRandomization === '#') return;

        fetch(this.config.urls.getGroupDatatablesForRandomization)
            .then(res => res.json())
            .then(data => {
                this.datatableCache = data;
                this.elements.minimizeDatatableSelect.innerHTML = '<option value="">-- Select DataTable --</option>';
                data.forEach(dt => {
                    this.elements.minimizeDatatableSelect.add(new Option(dt.text, dt.id));
                });
            })
            .catch(error => console.error('Error fetching datatables:', error));
    }

    handleMinimizeSourceChange(e) {
        const isAM = e.target.value === 'animal_model';
        this.elements.minimizeAnimalModelParams.style.display = isAM ? 'block' : 'none';
        this.elements.minimizeDatatableParams.style.display = isAM ? 'none' : 'block';
        if (!isAM && this.datatableCache.length === 0) {
            this.fetchGroupDataTables();
        }
    }

    handleDatatableSelectChange(e) {
        const dtId = e.target.value;
        this.elements.minimizeAnalyteDtSelect.innerHTML = '';
        if (dtId) {
            // Find in cache
            // Note: ID types might mismatch (int vs string), use loose comparison or string conversion
            const selectedDt = this.datatableCache.find(dt => String(dt.id) === String(dtId));
            if (selectedDt && selectedDt.analytes) {
                selectedDt.analytes.forEach(analyte => {
                    this.elements.minimizeAnalyteDtSelect.add(new Option(analyte.name, analyte.name));
                });
            }
        }
    }

    setupNavigation() {
        document.getElementById('rand-next-to-step-2')?.addEventListener('click', () => this.showRandStep('step2'));
        document.getElementById('rand-back-to-step-1')?.addEventListener('click', () => this.showRandStep('step1'));

        document.getElementById('rand-next-to-step-3')?.addEventListener('click', () => {
            const totalAssigned = parseInt(this.elements.totalUnitsAssignedSpan.textContent, 10);
            const totalAvailable = parseInt(this.elements.totalUnitsAvailableStep2Span.textContent, 10);

            if (totalAssigned !== totalAvailable) {
                alert(`Count mismatch! You have ${totalAvailable} units available but assigned ${totalAssigned}.`);
                return;
            }
            this.showRandStep('step3');
        });
        document.getElementById('rand-back-to-step-2')?.addEventListener('click', () => this.showRandStep('step2'));

        // Step 3 -> 4 (Summary)
        document.getElementById('rand-next-to-step-4')?.addEventListener('click', () => this.generatePreStatusSummary());

        document.getElementById('rand-back-to-step-3')?.addEventListener('click', () => this.showRandStep('step3'));

        // Final Submit
        document.getElementById('rand-confirm-btn')?.addEventListener('click', (e) => this.submitRandomization(e));
    }

    generatePreStatusSummary() {
        let summary = [];

        // 1. Units
        const unitVal = this.elements.randomizeBySelect.value;
        const unitText = (unitVal === '__individual__') ? "Individual Animals" : `Clusters (${unitVal})`;
        summary.push(`<strong>Unit:</strong> ${unitText}`);

        // 2. Stratification
        const strat = this.elements.stratificationFactorSelect.value;
        if (strat) {
            summary.push(`<strong>Stratification:</strong> ${strat}`);
        }

        // 3. Method
        const method = document.querySelector('input[name="assignmentMethod"]:checked').value;
        let methodText = `<strong>Method:</strong> ${method}`;

        if (method === 'Minimization') {
            const source = this.elements.minimizeSourceSelect.value;
            const param = (source === 'animal_model')
                ? this.elements.minimizeAnalyteAmSelect.value
                : this.elements.minimizeAnalyteDtSelect.value;
            methodText += ` (Parameter: ${param})`;
        }
        summary.push(methodText);

        // 4. Groups
        summary.push(`<br><strong>Groups Configured:</strong>`);
        const ul = document.createElement('ul');
        this.elements.treatmentGroupsContainer.querySelectorAll('.treatment-group-row').forEach(row => {
            const actual = row.querySelector('.actual-name').value;
            const count = row.querySelector('.unit-count').value;
            let liText = `${actual}: ${count}`;
            if (this.elements.useBlindingCheckbox.checked) {
                const blinded = row.querySelector('.blinded-name').value;
                liText += ` (Blinded: ${blinded})`;
            }
            summary.push(`&nbsp;&nbsp;• ${liText}`);
        });

        this.elements.randomizationSummaryDiv.innerHTML = summary.join('<br>');
        this.showRandStep('step4');
    }

    submitRandomization(e) {
        const btn = e.target;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Processing...';

        // Construct Payload
        this.randomizationState = {
            randomization_unit: this.elements.randomizeBySelect.value,
            allow_splitting: this.elements.allowSplittingCheckbox.checked,
            min_subgroup_size: this.elements.minSubgroupSizeInput.value,
            stratification_factor: this.elements.stratificationFactorSelect.value,
            use_blinding: this.elements.useBlindingCheckbox.checked,
            assignment_method: document.querySelector('input[name="assignmentMethod"]:checked').value,
            treatment_groups: [],
            minimization_details: null
        };

        if (this.randomizationState.assignment_method === 'Minimization') {
            const source = this.elements.minimizeSourceSelect.value;
            const analyte = source === 'animal_model'
                ? this.elements.minimizeAnalyteAmSelect.value
                : this.elements.minimizeAnalyteDtSelect.value;

            this.randomizationState.minimization_details = { source: source, analyte: analyte };

            if (source === 'datatable') {
                this.randomizationState.minimization_details.datatable_id = this.elements.minimizeDatatableSelect.value;
            }
        }

        this.elements.treatmentGroupsContainer.querySelectorAll('.treatment-group-row').forEach(row => {
            this.randomizationState.treatment_groups.push({
                actual_name: row.querySelector('.actual-name').value.trim(),
                blinded_name: row.querySelector('.blinded-name').value.trim(),
                count: parseInt(row.querySelector('.unit-count').value, 10)
            });
        });

        // Send Request
        fetch(this.config.urls.randomizeGroup, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.config.csrfToken
            },
            body: JSON.stringify(this.randomizationState)
        })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    // Success - Reload page to see applied groups
                    window.location.reload();
                } else {
                    alert("Randomization Error: " + data.message);
                    btn.disabled = false;
                    btn.innerHTML = 'Confirm & Randomize';
                }
            })
            .catch(err => {
                console.error(err);
                alert("System Error during randomization.");
                btn.disabled = false;
                btn.innerHTML = 'Confirm & Randomize';
            });
    }

    populateSummaryModal(summaryData) {
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

    setupSummaryActions() {
        // Unblind Button
        const unblindBtn = document.getElementById('unblind-randomization-btn-dropdown');
        if (unblindBtn) {
            unblindBtn.addEventListener('click', () => {
                if (confirm("Are you sure? This will reveal actual group assignments to everyone.")) {
                    fetch(this.config.urls.unblindGroup, {
                        method: 'POST',
                        headers: { 'X-CSRFToken': this.config.csrfToken }
                    }).then(() => window.location.reload());
                }
            });
        }

        // Delete Randomization Button
        const deleteRandBtn = document.getElementById('delete-randomization-btn-dropdown');
        if (deleteRandBtn) {
            deleteRandBtn.addEventListener('click', () => {
                if (confirm("Are you sure? This will remove all group assignments.")) {
                    fetch(this.config.urls.deleteRandomization, {
                        method: 'POST',
                        headers: { 'X-CSRFToken': this.config.csrfToken }
                    }).then(() => window.location.reload());
                }
            });
        }

        // View Summary (Already Randomized)
        const viewSummaryBtn = document.getElementById('view-randomization-summary-btn-dropdown');
        if (viewSummaryBtn) {
            viewSummaryBtn.addEventListener('click', () => {
                fetch(this.config.urls.getRandomizationSummary)
                    .then(res => res.json())
                    .then(summaryData => {
                        this.populateSummaryModal(summaryData);
                        const summaryModal = new bootstrap.Modal(document.getElementById('randomizationSummaryModal'));
                        summaryModal.show();
                    })
                    .catch(error => console.error('Error fetching summary:', error));
            });
        }
    }
}
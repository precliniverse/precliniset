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
            minimizeDatatableParams: document.getElementById('minimize-datatable-params'),
            minimizeDatatableSelect: document.getElementById('minimize-datatable-select'),
            minimizeAnalyteDtSelect: document.getElementById('minimize-analyte-dt'),
            randomizationSummaryDiv: document.getElementById('randomization-summary')
        };

        // Validate Critical Elements
        for (const [key, el] of Object.entries(this.elements)) {
            if (!el && key !== 'steps') {
                // Silently fails if elements missing to avoid console noise, 
                // but real production apps might want a subtle error tracking here.
            }
        }

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
        this.onShow = this.onShow.bind(this);
        this.unblindRandomization = this.unblindRandomization.bind(this);
        this.deleteRandomization = this.deleteRandomization.bind(this);
        this.openSummary = this.openSummary.bind(this);

        // Listeners
        this.modalEl.addEventListener('show.bs.modal', this.onShow);

        if (this.elements.randomizeBySelect) {
            this.elements.randomizeBySelect.addEventListener('change', this.updateAvailableUnits);
        }

        if (this.elements.allowSplittingCheckbox) {
            this.elements.allowSplittingCheckbox.addEventListener('change', () => {
                this.elements.minSubgroupSizeContainer.style.display = this.elements.allowSplittingCheckbox.checked ? 'block' : 'none';
                this.updateAvailableUnits();
            });
        }

        if (this.elements.useBlindingCheckbox) {
            this.elements.useBlindingCheckbox.addEventListener('change', this.toggleBlindingFields);
        }

        document.getElementById('add-treatment-group-btn')?.addEventListener('click', () => this.addTreatmentGroup());

        this.elements.assignmentMethodRadios.forEach(radio => {
            radio.addEventListener('change', () => {
                this.elements.minimizationOptions.style.display = (radio.value === 'Minimization') ? 'block' : 'none';
            });
        });

        if (this.elements.minimizeDatatableSelect) {
            this.elements.minimizeDatatableSelect.addEventListener('change', (e) => this.handleDatatableSelectChange(e));
        }

        this.setupNavigation();
    }

    onShow() {
        this.showRandStep('step1');

        const selectedModelId = $('#model_select').val();
        if (!selectedModelId) {
            alert("Please select an Animal Model for the group before randomizing.");
            return;
        }

        const selectedModel = this.animalModelsData.find(m => String(m.id) === String(selectedModelId));

        // Reset Dropdowns
        this.elements.randomizeBySelect.innerHTML = '<option value="__individual__">Individual Animal</option>';
        this.elements.randomizeBySelect.value = '__individual__';
        this.elements.stratificationFactorSelect.innerHTML = '<option value="">None</option>';

        if (selectedModel && selectedModel.analytes) {
            selectedModel.analytes.forEach(analyte => {
                const type = (analyte.data_type || analyte.type || '').toLowerCase();
                const isCategorical = ['text', 'category', 'int', 'string'].includes(type);

                if (isCategorical) {
                    const hasData = this.config.existingAnimalData.some(a => {
                        const val = a[analyte.name];
                        return val !== undefined && val !== null && val !== '';
                    });

                    if (hasData) {
                        this.elements.randomizeBySelect.add(new Option(analyte.name, analyte.name));
                        this.elements.stratificationFactorSelect.add(new Option(analyte.name, analyte.name));
                    }
                }
            });
        }

        this.updateAvailableUnits();

        // Reset Treatment Groups
        this.elements.treatmentGroupsContainer.innerHTML = '';
        this.addTreatmentGroup('Group A', 'Group A', 0);
        this.addTreatmentGroup('Group B', 'Group B', 0);

        this.fetchGroupDataTables();
    }

    showRandStep(stepKey) {
        Object.values(this.elements.steps).forEach(s => { if (s) s.style.display = 'none'; });
        if (this.elements.steps[stepKey]) this.elements.steps[stepKey].style.display = 'block';
    }

    updateAvailableUnits() {
        const animalData = (this.config.existingAnimalData || [])
            .filter(a => (a.status || 'alive') === 'alive');

        if (animalData.length === 0) {
            this.elements.totalUnitsAvailableSpan.textContent = "0";
            return;
        }

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
        if (this.elements.totalUnitsAvailableStep2Span) {
            this.elements.totalUnitsAvailableStep2Span.textContent = count;
        }

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
            const val = parseInt(input.value, 10);
            totalAssigned += isNaN(val) ? 0 : val;
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

    handleDatatableSelectChange(e) {
        const dtId = e.target.value;
        this.elements.minimizeAnalyteDtSelect.innerHTML = '';
        if (dtId) {
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
            const totalAssigned = parseInt(this.elements.totalUnitsAssignedSpan.textContent, 10) || 0;
            const totalAvailable = parseInt(this.elements.totalUnitsAvailableStep2Span.textContent, 10) || 0;

            if (totalAssigned !== totalAvailable) {
                alert(`Count mismatch! You have ${totalAvailable} units available but assigned ${totalAssigned}.`);
                return;
            }
            this.showRandStep('step3');
        });
        document.getElementById('rand-back-to-step-2')?.addEventListener('click', () => this.showRandStep('step2'));
        document.getElementById('rand-next-to-step-4')?.addEventListener('click', () => this.generatePreStatusSummary());
        document.getElementById('rand-back-to-step-3')?.addEventListener('click', () => this.showRandStep('step3'));
        document.getElementById('rand-confirm-btn')?.addEventListener('click', (e) => this.submitRandomization(e));
    }

    generatePreStatusSummary() {
        let summary = [];
        const unitVal = this.elements.randomizeBySelect.value;
        const unitText = (unitVal === '__individual__') ? "Individual Animals" : `Clusters (${unitVal})`;
        summary.push(`<strong>Unit:</strong> ${unitText}`);

        const strat = this.elements.stratificationFactorSelect.value;
        if (strat) {
            summary.push(`<strong>Stratification:</strong> ${strat}`);
        }

        const method = document.querySelector('input[name="assignmentMethod"]:checked').value;
        let methodText = `<strong>Method:</strong> ${method}`;

        if (method === 'Minimization') {
            const param = this.elements.minimizeAnalyteDtSelect.value;
            methodText += ` (Parameter: ${param})`;
        }
        summary.push(methodText);

        summary.push(`<br><strong>Groups Configured:</strong>`);
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

        try {
            this.randomizationState = {
                randomization_unit: this.elements.randomizeBySelect.value,
                allow_splitting: this.elements.allowSplittingCheckbox.checked,
                min_subgroup_size: parseInt(this.elements.minSubgroupSizeInput.value, 10) || 2,
                stratification_factor: this.elements.stratificationFactorSelect.value,
                use_blinding: this.elements.useBlindingCheckbox.checked,
                assignment_method: document.querySelector('input[name="assignmentMethod"]:checked').value,
                treatment_groups: [],
                minimization_details: null
            };

            if (this.randomizationState.assignment_method === 'Minimization') {
                const analyte = this.elements.minimizeAnalyteDtSelect.value;
                if (!analyte) throw new Error("Minimization parameter (Analyte) is missing. Please select one.");

                this.randomizationState.minimization_details = { source: 'datatable', analyte: analyte };
                const dtId = this.elements.minimizeDatatableSelect.value;
                if (!dtId) throw new Error("Please select a valid DataTable.");
                this.randomizationState.minimization_details.datatable_id = dtId;
            }

            this.elements.treatmentGroupsContainer.querySelectorAll('.treatment-group-row').forEach(row => {
                const actual = row.querySelector('.actual-name').value.trim();
                const blinded = row.querySelector('.blinded-name').value.trim();
                const count = parseInt(row.querySelector('.unit-count').value, 10);

                if (!actual) throw new Error("Group name cannot be empty.");
                if (isNaN(count) || count < 0) throw new Error("Group count must be a valid number.");

                this.randomizationState.treatment_groups.push({
                    actual_name: actual,
                    blinded_name: blinded,
                    count: count
                });
            });

            fetch(this.config.urls.randomizeGroup, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.config.csrfToken
                },
                body: JSON.stringify(this.randomizationState)
            })
                .then(async res => {
                    if (!res.ok) {
                        const text = await res.text();
                        try {
                            const data = JSON.parse(text);
                            throw new Error(data.message || "Server Error");
                        } catch (e) {
                            throw new Error(`Server returned error ${res.status}: ${res.statusText}`);
                        }
                    }
                    return res.json();
                })
                .then(data => {
                    if (data.success) {
                        const url = new URL(window.location.href);
                        url.searchParams.set('randomized', '1');
                        window.location.href = url.toString();
                    } else {
                        alert("Randomization Error: " + data.message);
                        btn.disabled = false;
                        btn.innerHTML = 'Confirm & Randomize';
                    }
                })
                .catch(err => {
                    alert("System Error: " + err.message);
                    btn.disabled = false;
                    btn.innerHTML = 'Confirm & Randomize';
                });

        } catch (validationErr) {
            alert("Configuration Error: " + validationErr.message);
            btn.disabled = false;
            btn.innerHTML = 'Confirm & Randomize';
        }
    }

    populateSummaryModal(summaryData) {
        document.getElementById('summary-randomized-at').textContent = new Date(summaryData.randomized_at).toLocaleString();
        document.getElementById('summary-randomized-by').textContent = summaryData.randomized_by;

        const settingsUl = document.getElementById('summary-settings-list');
        settingsUl.innerHTML = '';
        let unitText = summaryData.unit_of_randomization;
        if (unitText === '__individual__') unitText = `Individual Animal`;
        if (summaryData.allow_splitting) unitText = `${unitText} (with cluster splitting allowed)`;
        settingsUl.innerHTML += `<li><strong>Randomization Unit:</strong> ${unitText}</li>`;
        if (summaryData.stratification_factor) {
            settingsUl.innerHTML += `<li><strong>Primary Stratification:</strong> ${summaryData.stratification_factor}</li>`;
        }
        settingsUl.innerHTML += `<li><strong>Balancing Method:</strong> ${summaryData.assignment_method}</li>`;

        const baselineContainer = document.getElementById('summary-baseline-data-container');
        if (summaryData.minimization_details && summaryData.minimization_details.source_name) {
            baselineContainer.style.display = 'block';
            document.getElementById('summary-baseline-data-details').innerHTML = `
                Source: <a href="${summaryData.minimization_details.source_url}" target="_blank">${summaryData.minimization_details.source_name}</a><br>
                Parameter: <strong>${summaryData.minimization_details.analyte}</strong>
            `;
        } else {
            baselineContainer.style.display = 'none';
        }

        const requestedUl = document.getElementById('summary-requested-group-sizes');
        requestedUl.innerHTML = '';
        if (summaryData.requested_group_sizes) {
            for (const [groupName, size] of Object.entries(summaryData.requested_group_sizes)) {
                requestedUl.innerHTML += `<li><strong>${groupName}:</strong> ${size}</li>`;
            }
        }

        const actualUl = document.getElementById('summary-actual-group-sizes');
        actualUl.innerHTML = '';
        if (summaryData.actual_group_sizes) {
            for (const [groupName, size] of Object.entries(summaryData.actual_group_sizes)) {
                actualUl.innerHTML += `<li><strong>${groupName}:</strong> ${size}</li>`;
            }
        }

        const minResultsDiv = document.getElementById('summary-minimization-results');
        const minResultsUl = document.getElementById('summary-minimization-list');
        if (summaryData.minimization_summary) {
            minResultsDiv.style.display = 'block';
            minResultsUl.innerHTML = '';
            for (const [groupName, stats] of Object.entries(summaryData.minimization_summary)) {
                minResultsUl.innerHTML += `<li><strong>${groupName}:</strong> ${stats.mean.toFixed(2)} ± ${stats.sem.toFixed(2)} (n=${stats.n})</li>`;
            }
        } else {
            minResultsDiv.style.display = 'none';
        }

        const unitDistDiv = document.getElementById('summary-unit-distribution');
        const unitDistContent = document.getElementById('summary-unit-distribution-content');
        if (summaryData.unit_distribution && Object.keys(summaryData.unit_distribution).length > 0) {
            unitDistDiv.style.display = 'block';
            unitDistContent.innerHTML = this._generateDistributionTable(summaryData.unit_distribution);
        } else {
            unitDistDiv.style.display = 'none';
        }

        const stratDistDiv = document.getElementById('summary-stratification-distribution');
        const stratDistContent = document.getElementById('summary-stratification-content');
        const stratTitle = document.getElementById('summary-stratification-title');
        if (summaryData.stratification_distribution && Object.keys(summaryData.stratification_distribution).length > 0) {
            stratDistDiv.style.display = 'block';
            if (stratTitle) stratTitle.textContent = `Distribution by ${summaryData.stratification_factor}:`;
            stratDistContent.innerHTML = this._generateDistributionTable(summaryData.stratification_distribution);
        } else {
            stratDistDiv.style.display = 'none';
        }

        const blindingKeyDiv = document.getElementById('summary-blinding-key');
        if (summaryData.blinding_key) {
            blindingKeyDiv.style.display = 'block';
            const blindingKeyUl = document.getElementById('summary-blinding-list');
            blindingKeyUl.innerHTML = '';
            for (const [blinded, actual] of Object.entries(summaryData.blinding_key)) {
                blindingKeyUl.innerHTML += `<li><strong>${blinded}:</strong> ${actual}</li>`;
            }
        } else {
            blindingKeyDiv.style.display = 'none';
        }
    }

    unblindRandomization() {
        if (confirm("Are you sure? This will reveal actual group assignments to everyone.")) {
            fetch(this.config.urls.unblindGroup, {
                method: 'POST',
                headers: { 'X-CSRFToken': this.config.csrfToken }
            }).then(() => window.location.reload());
        }
    }

    deleteRandomization() {
        if (confirm("Are you sure? This will remove all group assignments.")) {
            fetch(this.config.urls.deleteRandomization, {
                method: 'POST',
                headers: { 'X-CSRFToken': this.config.csrfToken }
            }).then(() => window.location.reload());
        }
    }

    openSummary() {
        fetch(this.config.urls.getRandomizationSummary)
            .then(res => res.json())
            .then(summaryData => {
                this.populateSummaryModal(summaryData);
                const modalDiv = document.getElementById('randomizationSummaryModal');
                const summaryModal = bootstrap.Modal.getOrCreateInstance(modalDiv);
                summaryModal.show();
            })
            .catch(error => {
                console.error('Error fetching summary:', error);
            });
    }

    _generateDistributionTable(distribution) {
        if (!distribution || Object.keys(distribution).length === 0) return '';
        const allColumns = new Set();
        Object.values(distribution).forEach(cols => {
            Object.keys(cols).forEach(c => allColumns.add(c));
        });
        const sortedColumns = Array.from(allColumns).sort();

        let html = '<table class="table table-sm table-bordered mt-2"><thead><tr><th>Group</th>';
        sortedColumns.forEach(c => html += `<th>${c}</th>`);
        html += '<th>Total</th></tr></thead><tbody>';

        for (const [groupName, cols] of Object.entries(distribution)) {
            let rowTotal = 0;
            html += `<tr><td><strong>${groupName}</strong></td>`;
            sortedColumns.forEach(c => {
                const count = cols[c] || 0;
                rowTotal += count;
                html += `<td>${count || '-'}</td>`;
            });
            html += `<td><strong>${rowTotal}</strong></td></tr>`;
        }
        html += '</tbody></table>';
        return html;
    }
}
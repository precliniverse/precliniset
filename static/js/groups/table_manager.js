export class AnimalTable {
    constructor(tableSelector, config) {
        this.table = document.querySelector(tableSelector);
        this.tbody = this.table.querySelector('tbody');
        this.config = config;
        this.nextRowIndex = 0;
        this.init();
    }

    init() {
        this.table.addEventListener('click', (e) => {
            const btn = e.target.closest('button');
            if (!btn) return;

            if (btn.classList.contains('remove-row-btn')) {
                btn.closest('tr').remove();
            } else if (btn.classList.contains('duplicate-row-btn')) {
                this.duplicateRow(btn.closest('tr'));
            }
        });

        this.table.addEventListener('change', (e) => {
            if (e.target.type === 'date') {
                this.calculateRowAge(e.target.closest('tr'));
            }
        });
    }

    updateTableHeader(fields) {
        this.currentFields = fields;
        const headerRow = this.table.querySelector('thead tr');

        // Reset header to base columns
        // 1. Actions, 2. ID, 3. Randomization (Conditional), 4. Age
        let html = `
            <th style="width: 80px;">Actions</th>
            <th style="width: 150px;">ID</th>
        `;

        // Re-inject Randomization Headers if needed (based on config)
        if (this.config.hasRandomization) {
            if (this.config.isBlinded) {
                html += `<th>Blinded Group</th>`;
                if (this.config.canViewUnblinded) {
                    html += `<th>Treatment Group</th>`;
                }
            } else {
                html += `<th>Treatment Group</th>`;
            }
        }

        html += `<th style="width: 120px;">Age (Days)</th>`;
        headerRow.innerHTML = html;

        // Define system fields to skip (Lower case comparison)
        const systemFields = ['id', 'uid', 'display_id', 'age_days', 'status', 'treatment_group', 'blinded_group', 'treatment group', 'blinded group', 'date of birth'];
        // Define explicit fields to render (date_of_birth, sex, genotype, treatment)
        const explicitFields = ['date_of_birth', 'sex', 'genotype', 'treatment'];

        // Render explicit fields first if they exist in the fields list
        explicitFields.forEach(explicitField => {
            const field = fields.find(f => f.name.toLowerCase() === explicitField);
            if (field) {
                const th = document.createElement('th');
                th.textContent = field.name + (field.unit ? ` (${field.unit})` : '');
                headerRow.appendChild(th);
            }
        });

        // Render other fields that are not system fields or explicit fields
        fields.forEach(field => {
            const name = field.name.toLowerCase();
            if (systemFields.includes(name) || explicitFields.includes(name)) {
                return;
            }

            const th = document.createElement('th');
            th.textContent = field.name + (field.unit ? ` (${field.unit})` : '');
            headerRow.appendChild(th);
        });
    }

    addAnimalRow(animalData = {}, fields = this.currentFields || []) {
        const row = document.createElement('tr');
        if (animalData.status === 'dead') row.classList.add('table-danger');

        // 1. Actions
        const actionsCell = row.insertCell();
        actionsCell.innerHTML = `
            <div class="btn-group btn-group-sm">
                <button type="button" class="btn btn-outline-primary duplicate-row-btn" title="Duplicate"><i class="fa-solid fa-copy"></i></button>
                <button type="button" class="btn btn-outline-danger remove-row-btn" title="Delete"><i class="fa-solid fa-trash"></i></button>
            </div>`;

        // 2. ID
        const idCell = row.insertCell();
        const displayId = animalData.display_id || animalData.ID || '';
        const dbId = animalData.id || '';
        idCell.innerHTML = `
            <input type="text" name="animal_${this.nextRowIndex}_field_display_id" class="form-control form-control-sm" value="${displayId}" required>
            <input type="hidden" name="animal_${this.nextRowIndex}_field_uid" value="${animalData.uid || ''}">
            <input type="hidden" name="animal_${this.nextRowIndex}_field_id" value="${dbId}">
        `;

        // 3. Randomization Columns (if applicable)
        if (this.config.hasRandomization) {
            if (this.config.isBlinded) {
                const blindedCell = row.insertCell();
                blindedCell.innerHTML = `<span class="badge bg-info">${animalData['blinded_group'] || '-'}</span>`;

                if (this.config.canViewUnblinded) {
                    const treatmentCell = row.insertCell();
                    treatmentCell.textContent = animalData['treatment_group'] || '-';
                }
            } else {
                const treatmentCell = row.insertCell();
                treatmentCell.textContent = animalData['treatment_group'] || '-';
            }
        }

        // 4. Age (and Date of Birth + Sex hidden logic)
        const ageCell = row.insertCell();
        ageCell.className = "text-center bg-body-tertiary";
        ageCell.innerHTML = `<span class="age-display">-</span>`;

        // Render explicit fields: date_of_birth, sex, genotype, treatment if they are in the fields list
        // We check if they exist in the fields list to ensure consistency with the table header
        const explicitFields = ['date_of_birth', 'sex', 'genotype', 'treatment'];
        explicitFields.forEach(explicitField => {
            const field = fields.find(f => f.name.toLowerCase() === explicitField);
            if (field) {
                const cell = row.insertCell();
                const type = (field.data_type || field.type || '').toUpperCase();
                let input;

                if (type === 'CATEGORY' && field.allowed_values) {
                    input = document.createElement('select');
                    input.className = 'form-select form-select-sm';
                    const defaultMsg = document.createElement('option');
                    defaultMsg.value = "";
                    defaultMsg.text = "";
                    input.appendChild(defaultMsg);
                    field.allowed_values.split(';').forEach(v => {
                        const opt = document.createElement('option');
                        opt.value = v.trim();
                        opt.text = v.trim();
                        input.appendChild(opt);
                    });
                } else {
                    input = document.createElement('input');
                    input.className = 'form-control form-control-sm';
                    if (type === 'DATE') input.type = 'date';
                    else if (type === 'FLOAT' || type === 'INT') {
                        input.type = 'number';
                        if (type === 'FLOAT') input.step = 'any';
                    } else input.type = 'text';
                }

                input.name = `animal_${this.nextRowIndex}_field_${field.name}`;

                // Value resolution
                let val = animalData[field.name] || animalData[field.name.toLowerCase()] || field.default_value || '';
                if (type === 'DATE' && val && val.includes('T')) val = val.split('T')[0];

                input.value = val;

                // Death Logic for DOB field
                if (explicitField === 'date_of_birth' && animalData.status === 'dead' && animalData.death_date) {
                    const div = document.createElement('div');
                    div.className = 'death-info small text-danger mt-1';
                    div.innerHTML = `Deceased: ${animalData.death_date.split('T')[0]}`;
                    cell.appendChild(input);
                    cell.appendChild(div);
                } else {
                    cell.appendChild(input);
                }
            }
        });

        // Render other fields that are not system fields or explicit fields
        const systemFieldsToSkipInLoop = ['id', 'uid', 'display_id', 'age_days', 'status', 'treatment_group', 'blinded_group'];
        fields.forEach(field => {
            const name = field.name.toLowerCase();
            if (systemFieldsToSkipInLoop.includes(name) || explicitFields.includes(name)) {
                return;
            }

            const cell = row.insertCell();
            const type = (field.data_type || field.type || '').toUpperCase();
            let input;

            if (type === 'CATEGORY' && field.allowed_values) {
                input = document.createElement('select');
                input.className = 'form-select form-select-sm';
                const defaultMsg = document.createElement('option');
                defaultMsg.value = "";
                defaultMsg.text = "";
                input.appendChild(defaultMsg);
                field.allowed_values.split(';').forEach(v => {
                    const opt = document.createElement('option');
                    opt.value = v.trim();
                    opt.text = v.trim();
                    input.appendChild(opt);
                });
            } else {
                input = document.createElement('input');
                input.className = 'form-control form-control-sm';
                if (type === 'DATE') input.type = 'date';
                else if (type === 'FLOAT' || type === 'INT') {
                    input.type = 'number';
                    if (type === 'FLOAT') input.step = 'any';
                } else input.type = 'text';
            }

            input.name = `animal_${this.nextRowIndex}_field_${field.name}`;

            // Value resolution
            let val = animalData[field.name] || animalData[name] || field.default_value || '';
            if (type === 'DATE' && val && val.includes('T')) val = val.split('T')[0];

            input.value = val;

            cell.appendChild(input);
        });

        this.tbody.appendChild(row);
        this.nextRowIndex++;
        this.calculateRowAge(row);
    }

    duplicateRow(sourceRow) {
        const rowData = {};
        sourceRow.querySelectorAll('input, select').forEach(input => {
            if (input.name && input.name.includes('_field_')) {
                const parts = input.name.split('_field_');
                if (parts.length === 2) {
                    const fieldName = parts[1];
                    if (fieldName !== 'uid' && fieldName !== 'id') {
                        rowData[fieldName] = input.value;
                    }
                }
            }
        });
        // Generate a temporary display ID
        rowData.display_id = (rowData.display_id || '') + '_copy';
        this.addAnimalRow(rowData);
    }

    calculateRowAge(row) {
        // Find input name containing date_of_birth
        const inputs = row.querySelectorAll('input[type="date"]');
        let dobInput = null;

        inputs.forEach(i => {
            if (i.name && i.name.toLowerCase().includes('date_of_birth')) {
                dobInput = i;
            }
        });

        const ageDisplay = row.querySelector('.age-display');
        if (!dobInput || !ageDisplay || !dobInput.value) return;

        const dob = new Date(dobInput.value);
        const today = new Date();
        const diff = Math.floor((today - dob) / (1000 * 60 * 60 * 24));
        if (!isNaN(diff) && diff >= 0) {
            const weeks = Math.floor(diff / 7);
            ageDisplay.textContent = `${diff}d (${weeks}w)`;
        } else {
            ageDisplay.textContent = '-';
        }
    }

    clearRows() {
        this.tbody.innerHTML = '';
        this.nextRowIndex = 0;
    }

    getData() {
        const data = [];
        this.tbody.querySelectorAll('tr').forEach(row => {
            const rowData = {};
            row.querySelectorAll('input, select').forEach(input => {
                if (input.name && input.name.includes('_field_')) {
                    const parts = input.name.split('_field_');
                    if (parts.length === 2) rowData[parts[1]] = input.value;
                }
            });
            // Capture age if computed
            const ageSpan = row.querySelector('.age-display');
            if (ageSpan) rowData['age_days'] = ageSpan.innerText;

            data.push(rowData);
        });
        return data;
    }
}
export class AnimalTable {
    constructor(tableSelector, config) {
        this.table = document.querySelector(tableSelector);
        this.tbody = this.table.querySelector('tbody');
        this.config = config;
        this.nextRowIndex = 0;
        this.init();
    }

    init() {
        // Délégation d'événements pour les boutons dans la table
        this.table.addEventListener('click', (e) => {
            const btn = e.target.closest('button');
            if (!btn) return;

            if (btn.classList.contains('remove-row-btn')) {
                btn.closest('tr').remove();
            } else if (btn.classList.contains('duplicate-row-btn')) {
                this.duplicateRow(btn.closest('tr'));
            }
        });

        // Calcul d'âge dynamique
        this.table.addEventListener('change', (e) => {
            if (e.target.type === 'date') {
                this.calculateRowAge(e.target.closest('tr'));
            }
        });
    }

    updateTableHeader(fields) {
        const headerRow = this.table.querySelector('thead tr');
        headerRow.innerHTML = `
            <th style="width: 80px;">Actions</th>
            <th style="width: 150px;">ID</th>
            <th style="width: 120px;">Age (Days)</th>
        `;

        fields.forEach(field => {
            const name = field.name.toLowerCase();
            if (['id', 'uid', 'display_id', 'age_days', 'status'].includes(name)) return;
            const th = document.createElement('th');
            th.textContent = field.name + (field.unit ? ` (${field.unit})` : '');
            headerRow.appendChild(th);
        });
    }

    addAnimalRow(animalData = {}, fields = []) {
        const row = document.createElement('tr');
        if (animalData.status === 'dead') row.classList.add('table-danger');

        // 1. Actions
        const actionsCell = row.insertCell();
        actionsCell.innerHTML = `
            <div class="btn-group btn-group-sm">
                <button type="button" class="btn btn-outline-primary duplicate-row-btn" title="Dupliquer"><i class="fa-solid fa-copy"></i></button>
                <button type="button" class="btn btn-outline-danger remove-row-btn" title="Supprimer"><i class="fa-solid fa-trash"></i></button>
            </div>`;

        // 2. ID (display_id) + UID caché + DB ID (Primary Key)
        const idCell = row.insertCell();
        const displayId = animalData.display_id || animalData.ID || '';
        // CRITICAL: Store the DB Integer ID to prevent data loss on rename
        const dbId = animalData.id || '';
        idCell.innerHTML = `
            <input type="text" name="animal_${this.nextRowIndex}_field_display_id" class="form-control form-control-sm" value="${displayId}" required>
            <input type="hidden" name="animal_${this.nextRowIndex}_field_uid" value="${animalData.uid || ''}">
            <input type="hidden" name="animal_${this.nextRowIndex}_field_id" value="${dbId}">
        `;

        // 3. Age
        const ageCell = row.insertCell();
        ageCell.className = "text-center bg-body-tertiary";
        ageCell.innerHTML = `<span class="age-display">-</span>`;

        // 4. Analytes
        fields.forEach(field => {
            const name = field.name.toLowerCase();
            if (['id', 'uid', 'display_id', 'age_days', 'status'].includes(name)) return;

            const cell = row.insertCell();
            const type = (field.data_type || field.type || '').toUpperCase();
            let input;

            if (type === 'CATEGORY' && field.allowed_values) {
                input = document.createElement('select');
                input.name = `animal_${this.nextRowIndex}_field_${field.name}`;
                input.className = 'form-select form-select-sm';

                // Add default empty option
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
                input.name = `animal_${this.nextRowIndex}_field_${field.name}`;
                input.className = 'form-control form-control-sm';
                input.setAttribute('autocomplete', 'off');

                if (type === 'DATE') input.type = 'date';
                else if (type === 'FLOAT' || type === 'INT') {
                    input.type = 'number';
                    if (type === 'FLOAT') input.step = 'any';
                } else input.type = 'text';
            }

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
            const parts = input.name.split('_field_');
            if (parts.length === 2) {
                const fieldName = parts[1];
                // On ne duplique pas les IDs uniques
                if (fieldName !== 'uid' && fieldName !== 'display_id' && fieldName !== 'id') {
                    rowData[fieldName] = input.value;
                }
            }
        });
        // On récupère les champs du modèle depuis la config globale
        const fields = JSON.parse(document.getElementById('group-config').dataset.config).modelFields;
        this.addAnimalRow(rowData, fields);
    }

    calculateRowAge(row) {
        const dobInput = row.querySelector('input[type="date"]');
        const ageDisplay = row.querySelector('.age-display');
        if (!dobInput || !ageDisplay || !dobInput.value) return;

        const dob = new Date(dobInput.value);
        const today = new Date();
        const diff = Math.floor((today - dob) / (1000 * 60 * 60 * 24));
        if (!isNaN(diff) && diff >= 0) {
            const weeks = Math.floor(diff / 7);
            ageDisplay.textContent = `${diff} d (${weeks} w)`;
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
                const parts = input.name.split('_field_');
                if (parts.length === 2) rowData[parts[1]] = input.value;
            });
            data.push(rowData);
        });
        return data;
    }
}
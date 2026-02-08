/**
 * static/js/groups/table_manager.js
 * Handles adding, removing, and initializing the animal data table rows.
 */
export class AnimalTable {
    constructor(tableSelector, config) {
        this.table = document.querySelector(tableSelector);
        this.tbody = this.table.querySelector('tbody');
        this.config = config;
        this.nextRowIndex = 0;
        this.rowTemplate = document.getElementById('animal-row-template');
        this.cellTemplate = document.getElementById('animal-cell-template');

        // Bind methods
        this.addAnimalRow = this.addAnimalRow.bind(this);
        this.handleTableClick = this.handleTableClick.bind(this);

        this.init();
    }

    init() {
        // Event Delegation for table actions
        this.table.addEventListener('click', this.handleTableClick);
        
        // Initialize existing rows count if any (not strictly needed if we always append, but good for id tracking)
        this.nextRowIndex = this.tbody.getElementsByTagName('tr').length;
    }

    /**
     * Creates and appends a new row based on templates
     * @param {Object} animalData - Data to populate (optional)
     * @param {Array} fields - Array of field definitions
     */
    addAnimalRow(animalData = {}, fields = []) {
        if (!this.rowTemplate || !this.cellTemplate) {
            console.error("Missing templates for AnimalTable");
            return;
        }

        const clone = this.rowTemplate.content.cloneNode(true);
        const tr = clone.querySelector('tr');
        if (animalData.id) {
            tr.dataset.animalId = animalData.id; // Store technical ID
        }
        
        // --- Insert display_id cell after action cell ---
        const actionCell = tr.querySelector('.action-cell');
        const displayIdCell = document.createElement('td');
        displayIdCell.dataset.fieldName = "display_id";
        displayIdCell.textContent = animalData['display_id'] || '';
        actionCell.after(displayIdCell);
        
        // --- 1. Handle Status styling ---
        if (animalData.status === 'dead') {
            tr.classList.add('table-danger');
            // Disable buttons in action cell
            const btns = tr.querySelectorAll('button');
            btns.forEach(b => b.disabled = true);
        }

        // --- 2. Handle Randomization Columns (if applicable) ---
        // Note: The template has these as d-none by default. We show them if config says so.
        if (this.config.hasRandomization) {
            const blindedCell = tr.querySelector('.blinded-cell');
            const treatmentCell = tr.querySelector('.treatment-cell');

            if (this.config.isBlinded) {
                blindedCell.classList.remove('d-none');
                blindedCell.querySelector('.blinded-value').textContent = animalData['blinded_group'] || '-';
                
                if (this.config.canViewUnblinded) {
                    treatmentCell.classList.remove('d-none');
                    treatmentCell.querySelector('.treatment-value').textContent = animalData['treatment_group'] || '-';
                }
            } else {
                treatmentCell.classList.remove('d-none');
                treatmentCell.querySelector('.treatment-value').textContent = animalData['treatment_group'] || '-';
            }
        }

        // --- 3. Handle Age Cell ---
        const ageSpan = tr.querySelector('.age-display');
        ageSpan.textContent = animalData['age_days'] || '-';
        const dob = animalData['date_of_birth'];
        if (dob) {
            // Store raw date for calculations
            ageSpan.dataset.birthDate = dob; 
        }

        // --- 4. Generate Dynamic Measurement Cells ---
        fields.forEach(field => {
            const lowFieldName = field.name.toLowerCase();
            // Skip fixed columns we already handled
            if (lowFieldName === 'age_days' || lowFieldName === 'age (days)' || 
                field.name === 'blinded_group' || field.name === 'treatment_group') return;

            // Check visibility based on sensitive blinding rules
            // Logic: if sensitive AND in a blinded group AND user cannot view unblinded -> hide
            const isSensitiveAndBlinded = this.config.hasRandomization && field.is_sensitive && !this.config.canViewUnblinded;
            if (isSensitiveAndBlinded) return;

            // Clone Cell Template
            const cellClone = this.cellTemplate.content.cloneNode(true);
            const input = cellClone.querySelector('input');
            const deathInfoContainer = cellClone.querySelector('.death-info-container'); // Placeholder

            // Configure Input
            input.name = `animal_${this.nextRowIndex}_field_${field.name}`;
            input.type = field.type === 'date' ? 'date' : 'text';
            
            // Set Value - Try exact match then lowercase
            let val = animalData[field.name];
            if (val === undefined || val === null) {
                val = animalData[lowFieldName];
            }
            if (val === undefined || val === null) val = field.default_value || '';
            
            if (field.type === 'date' && val) {
                 // Ensure YYYY-MM-DD format for date inputs
                 if (typeof val === 'string' && val.includes('T')) val = val.split('T')[0];
            }
            input.value = val;

            // Required/Disabled states
            if (lowFieldName === 'id' || lowFieldName === 'uid') input.required = true;
            if (animalData.status === 'dead') input.disabled = true;
            if (this.config.isReadOnly) input.disabled = true;

            // Handle Categories (Datalist)
            if (field.type === 'category' && field.allowed_values) {
                const listId = `datalist-${field.name.replace(/\s+/g, '-')}-${this.nextRowIndex}`;
                input.setAttribute('list', listId);
                
                // Create Datalist dynamically (template doesn't have it to keep it light)
                const datalist = document.createElement('datalist');
                datalist.id = listId;
                field.allowed_values.split(';').forEach(v => {
                    const opt = document.createElement('option');
                    opt.value = v.trim();
                    datalist.appendChild(opt);
                });
                // Append datalist to the cell (td)
                cellClone.querySelector('td').appendChild(datalist);
            }

            // Handle Death Info (only for date_of_birth field)
            if (lowFieldName === 'date_of_birth' && animalData.status === 'dead' && animalData.death_date) {
                const dDate = animalData.death_date.split('T')[0];
                deathInfoContainer.innerHTML = `
                    <small class="text-muted d-block">${this.config.i18n.deceased}: ${dDate}</small>
                `;
                deathInfoContainer.dataset.deathDate = animalData.death_date;
            }

            tr.appendChild(cellClone);
        });

        // --- 5. Euthanasia Fields (if any animal is dead in the group) ---
        // Optimization: checking global state might be slow if done per row, but robust
        // In the original, it checked 'hasDeadAnimals'. We'll assume the caller passes this info or we check the data.
        // For consistent column alignment, we should probably add these columns ONLY if the header exists.
        // But headers are rendered server-side.
        // We need to match the header structure.
        // If we are "blindly" appending cells, we assume the headers match 'fields'.
        // For Euthanasia columns, original code appended them dynamically at the end.
        
        if (this.config.showEuthanasiaCols) {
             const reasonCell = this.createInputCell(animalData.euthanasia_reason, 'euthanasia_reason', animalData.status !== 'dead');
             tr.appendChild(reasonCell);
             
             const severityCell = this.createInputCell(animalData.severity, 'severity', animalData.status !== 'dead');
             tr.appendChild(severityCell);
        }

        this.tbody.appendChild(tr);
        this.nextRowIndex++;
        
        // Recalculate age immediately after adding
        // (Assuming you have a helper function or method for this)
        // calculateRowAge(tr, this.config.experimentDate); 
    }
    
    // Helper to create simple text input cell (for euthanasia cols)
    createInputCell(value, fieldName, disabled) {
         // modifying the template might be cleaner, but simple createElement here is fast enough for just 2 cells
         const td = document.createElement('td');
         const input = document.createElement('input');
         input.type = 'text';
         input.className = 'form-control form-control-sm';
         input.value = value || '';
         if (disabled) input.disabled = true;
         td.appendChild(input);
         return td;
    }

    handleTableClick(e) {
        const target = e.target.closest('button');
        if (!target) return;

        if (target.classList.contains('remove-row-btn')) {
            const tr = target.closest('tr');
            if (tr) tr.remove();
        } else if (target.classList.contains('duplicate-row-btn')) {
            // Duplication logic (copy values from current row and add new)
            // Implementation left as an exercise or similar to existing
        }
    }
    
    /**
     * Updates the table header based on the selected model fields
     * @param {Array} fields - Array of field definitions
     */
    updateTableHeader(fields) {
        const headerRow = this.table.querySelector('thead tr');
        if (!headerRow) return;

        // Start with Actions column
        headerRow.innerHTML = `<th>${this.config.i18n.actions}</th>`;
        
        const displayIdTh = document.createElement('th');
        displayIdTh.textContent = "ID"; // Use "ID" for display_id
        displayIdTh.dataset.fieldName = "display_id";
        headerRow.appendChild(displayIdTh);

        // Conditionally add Blinding/Randomization
        if (this.config.hasRandomization) {
            if (this.config.isBlinded) {
                const blindedTh = document.createElement('th');
                blindedTh.textContent = "Blinded Group";
                blindedTh.dataset.fieldName = "blinded_group";
                headerRow.appendChild(blindedTh);
                
                if (this.config.canViewUnblinded) {
                    const treatmentTh = document.createElement('th');
                    treatmentTh.textContent = "Treatment Group";
                    treatmentTh.dataset.fieldName = "treatment_group";
                    headerRow.appendChild(treatmentTh);
                }
            } else {
                const treatmentTh = document.createElement('th');
                treatmentTh.textContent = "Treatment Group";
                treatmentTh.dataset.fieldName = "treatment_group";
                headerRow.appendChild(treatmentTh);
            }
        }

        // age_days is always visible
        const ageTh = document.createElement('th');
        ageTh.textContent = "Age (Days)";
        ageTh.dataset.fieldName = "age_days";
        ageTh.title = "Calculated automatically from Date of Birth";
        headerRow.appendChild(ageTh);

        // Add dynamic fields
        fields.forEach(field => {
            const lowFieldName = field.name.toLowerCase();
            const shouldShow = !this.config.isEditing || !this.config.hasRandomization || !field.is_sensitive || this.config.canViewUnblinded;
            if (shouldShow && lowFieldName !== 'age_days' && lowFieldName !== 'age (days)' && 
                field.name !== 'blinded_group' && field.name !== 'treatment_group') {
                const th = document.createElement('th');
                th.textContent = field.name + (field.unit ? ` (${field.unit})` : '');
                headerRow.appendChild(th);
            }
        });

        // Add euthanasia columns if needed (based on config or data check)
        if (this.config.showEuthanasiaCols) {
            const reasonTh = document.createElement('th');
            reasonTh.textContent = 'Euthanasia Reason';
            headerRow.appendChild(reasonTh);

            const severityTh = document.createElement('th');
            severityTh.textContent = 'Severity';
            headerRow.appendChild(severityTh);
        }
    }

    clearRows() {
        this.tbody.innerHTML = '';
        this.nextRowIndex = 0;
    }
    
    // ... Any other table management methods (reindex, etc.)
    /**
     * Extracts data from the table for saving
     * @returns {Array} Array of animal data objects
     */
    getData() {
        const data = [];
        const rows = this.tbody.querySelectorAll('tr');
        rows.forEach(row => {
            const rowData = {};
            // Inputs have names like animal_{index}_field_{fieldName}
            const inputs = row.querySelectorAll('input, select');
            inputs.forEach(input => {
                const parts = input.name.split('_field_');
                if (parts.length === 2) {
                    const fieldName = parts[1];
                    rowData[fieldName] = input.value;
                }
            });

            // Capture display_id from its dedicated cell
            const displayIdCell = row.querySelector('td[data-field-name="display_id"]');
            if (displayIdCell) {
                rowData['display_id'] = displayIdCell.textContent.trim();
            }
            
            // Capture the technical animal ID from the tr's dataset
            if (row.dataset.animalId) {
                rowData['id'] = parseInt(row.dataset.animalId);
            }
            
            // Also capture age text just in case (though backend should calc it)
            const ageSpan = row.querySelector('.age-display');
            if (ageSpan) {
                rowData['age_days'] = ageSpan.textContent.trim();
            }
            
            data.push(rowData);
        });
        return data;
    }
}

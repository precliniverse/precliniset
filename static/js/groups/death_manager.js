/**
 * static/js/groups/death_manager.js
 * Handles the logic for the "Declare Death" modal and submission.
 */

export class DeathManager {
    constructor() {
        this.modalEl = document.getElementById('declareDeadModal');
        this.submitDeadBtn = document.getElementById('submitDeclareDead');
        this.init();
    }

    init() {
        // Delegate click for "Declare Death" button (since it might be in a row or action bar)
        document.addEventListener('click', (e) => this.handleDeclareClick(e));

        // Submit Button
        if (this.submitDeadBtn) {
            // Remove existing listeners by cloning (if any legacy code interfered) or just add new one
            // In module system, we are likely the only ones binding.
            const newSubmitBtn = this.submitDeadBtn.cloneNode(true);
            this.submitDeadBtn.parentNode.replaceChild(newSubmitBtn, this.submitDeadBtn);
            this.submitDeadBtn = newSubmitBtn;
            
            this.submitDeadBtn.addEventListener('click', () => this.handleSubmit());
        }
        
        // Modal Event Cleaning
         if (this.modalEl) {
            this.modalEl.addEventListener('hidden.bs.modal', () => {
                const form = this.modalEl.querySelector('#declareDeadForm');
                if (form) form.reset();
                const table = this.modalEl.querySelector('#declareDeadAnimalsTable');
                if (table) {
                    table.querySelector('thead').innerHTML = '';
                    table.querySelector('tbody').innerHTML = '';
                }
            });
         }
    }

    handleDeclareClick(e) {
        if (!e.target.closest('.declare-dead-btn')) return;
        
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

                const modalInstance = new bootstrap.Modal(this.modalEl);
                const modalTitle = this.modalEl.querySelector('.modal-title');
                const modalGroupIdInput = this.modalEl.querySelector('#modalGroupId');
                const table = this.modalEl.querySelector('#declareDeadAnimalsTable');
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
                    if (['ID', 'Genotype', 'Cage'].includes(field.name)) {
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
                         if (['ID', 'Genotype', 'Cage'].includes(field.name)) {
                            cell = row.insertCell();
                            cell.textContent = animal[field.name] || '';
                        }
                    });

                    cell = row.insertCell();
                    if (animal.status === 'dead') cell.textContent = `Dead (${animal.death_date || 'N/A'})`;
                    // Note: If alive, cell is empty td by default or we can put 'Alive'

                    // Euthanasia Reason
                    cell = row.insertCell();
                    const reasonSelect = document.createElement('select');
                    reasonSelect.className = 'form-select form-select-sm';
                    reasonSelect.name = `euthanasia_reason_${index}`;
                    reasonSelect.innerHTML = `<option value="">-- Select --</option>
                        <option value="état de santé">état de santé</option>
                        <option value="fin de protocole">fin de protocole</option>
                        <option value="Point limite atteint">Point limite atteint</option>`;
                    if (animal.status === 'dead') reasonSelect.disabled = true;
                    cell.appendChild(reasonSelect);

                    // Severity
                    cell = row.insertCell();
                    const severitySelect = document.createElement('select');
                    severitySelect.className = 'form-select form-select-sm';
                    severitySelect.name = `severity_${index}`;
                    severitySelect.innerHTML = `<option value="">-- Select --</option>
                        <option value="légère">légère</option>
                        <option value="modérée">modérée</option>
                        <option value="sévère">sévère</option>`;
                     if (animal.status === 'dead') severitySelect.disabled = true;
                    cell.appendChild(severitySelect);
                });

                // Select All Listener
                selectAllCheckbox.addEventListener('change', function () {
                    body.querySelectorAll('input[name="animal_indices"]:not([disabled])').forEach(checkbox => {
                        checkbox.checked = this.checked;
                    });
                });
                
                // "Apply to Selected" Logic
                const applyBtn = this.modalEl.querySelector('#applyToSelectedBtn');
                // Clone to remove old listeners
                const newApplyBtn = applyBtn.cloneNode(true);
                applyBtn.parentNode.replaceChild(newApplyBtn, applyBtn);
                
                newApplyBtn.addEventListener('click', () => {
                     const globalReason = this.modalEl.querySelector('#global_euthanasia_reason').value;
                     const globalSeverity = this.modalEl.querySelector('#global_severity').value;
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

                            if (reasonSelect && !reasonSelect.disabled) reasonSelect.value = globalReason;
                            if (severitySelect && !severitySelect.disabled) severitySelect.value = globalSeverity;
                        });
                });

                modalInstance.show();
            })
            .catch(err => console.error(err));
    }

    handleSubmit() {
        const groupId = document.getElementById('modalGroupId').value;
        const form = document.getElementById('declareDeadForm');
        const death_date = form.querySelector('#death_date').value;

        if (!death_date) { alert("Please select a date of death."); return; }

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
                const modal = bootstrap.Modal.getInstance(this.modalEl);
                if (modal) modal.hide();
                window.location.reload();
            } else {
                alert("Error: " + data.message);
            }
        });
    }
}

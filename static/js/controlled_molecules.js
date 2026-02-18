/**
 * controlled_molecules.js
 * Handles dynamic interactions for controlled molecules management.
 * Specifically handles the selection of individual animals when recording usage.
 * Supports multiple forms on the same page.
 */

document.addEventListener('DOMContentLoaded', function () {
    const containers = document.querySelectorAll('.animal-selection-container');

    // Read from the unified config if available
    const configEl = document.getElementById('datatable-editor-config');
    const config = configEl ? JSON.parse(configEl.textContent) : {};
    const groupAnimals = config.animalData || window.GROUP_ANIMALS || [];

    if (containers.length === 0) {
        console.log('No molecule usage forms found.');
        return;
    }

    containers.forEach(container => {
        const targetId = container.dataset.targetField;
        const input = document.getElementById(targetId);
        const displayId = `num-animals-display-${targetId}`;
        const display = document.getElementById(displayId);

        if (!input) {
            console.error(`Target input not found for container: ${targetId}`);
            return;
        }

        renderCheckboxes(container, input, display, groupAnimals);
    });

    function renderCheckboxes(container, input, display, animals) {
        container.innerHTML = '';
        let currentIds = [];
        try {
            currentIds = JSON.parse(input.value || '[]');
        } catch (e) {
            console.error('Error parsing current IDs', e);
        }

        if (animals.length === 0) {
            container.innerHTML = '<p class="text-muted">No animals found in this group.</p>';
            return;
        }

        // Add "Select All" option
        const selectAllDiv = document.createElement('div');
        selectAllDiv.className = 'custom-control custom-checkbox mb-2 pb-2 border-bottom';
        const selectAllId = `select-all-${input.id}`;
        selectAllDiv.innerHTML = `
            <input type="checkbox" class="custom-control-input" id="${selectAllId}">
            <label class="custom-control-label font-weight-bold" for="${selectAllId}">Select All</label>
        `;
        container.appendChild(selectAllDiv);

        const selectAllCheckbox = selectAllDiv.querySelector('input');
        const checkboxes = [];

        animals.forEach(animal => {
            const div = document.createElement('div');
            div.className = 'custom-control custom-checkbox mb-1';

            // Access animal properties safely
            const animalId = animal.id || animal.animal_id || animal.ID;
            const displayId = animal.display_id || animal.ID || animal.animal_id || `Animal ${animalId}`;

            // Build info badges
            const sex = animal.sex || animal.Sex || '';
            const genotype = animal.genotype || animal.Genotype || '';
            const status = animal.status || '';
            const isDead = status === 'dead';

            // Build badge HTML
            let badges = '';
            if (sex) badges += `<span class="badge bg-secondary ms-1" style="font-size:0.7rem;">${sex}</span>`;
            if (genotype) badges += `<span class="badge bg-info text-dark ms-1" style="font-size:0.7rem;">${genotype}</span>`;
            if (isDead) badges += `<span class="badge bg-danger ms-1" style="font-size:0.7rem;">☠ Deceased</span>`;

            const id = `animal-${input.id}-${animalId}`;
            const isChecked = currentIds.includes(animalId);

            div.innerHTML = `
                <input type="checkbox" class="custom-control-input animal-checkbox" id="${id}" value="${animalId}" ${isChecked ? 'checked' : ''} ${isDead ? 'disabled' : ''}>
                <label class="custom-control-label" for="${id}">
                    <strong>${displayId}</strong>${badges}
                </label>
            `;
            container.appendChild(div);
            // Only push non-dead animals to the checkboxes array (dead ones are disabled)
            if (!isDead) checkboxes.push(div.querySelector('input'));
        });

        // Event listeners for individual checkboxes
        checkboxes.forEach(cb => {
            cb.addEventListener('change', () => {
                updateSelection();
                updateSelectAllState();
            });
        });

        // Event listener for Select All
        selectAllCheckbox.addEventListener('change', function () {
            const isChecked = this.checked;
            checkboxes.forEach(cb => cb.checked = isChecked);
            updateSelection();
        });

        // Initial state update
        updateSelection();
        updateSelectAllState();

        function updateSelectAllState() {
            const allChecked = checkboxes.length > 0 && checkboxes.every(cb => cb.checked);
            const someChecked = checkboxes.some(cb => cb.checked);
            selectAllCheckbox.checked = allChecked;
            selectAllCheckbox.indeterminate = someChecked && !allChecked;
        }

        function updateSelection() {
            const selectedIds = checkboxes.filter(cb => cb.checked).map(cb => cb.value); // Keep as strings to match JSON storage better
            input.value = JSON.stringify(selectedIds);

            // Also try to find any other field that should be synced (e.g. number_of_animals)
            const parentForm = input.closest('form');
            if (parentForm) {
                const countField = parentForm.querySelector('input[name*="number_of_animals"]');
                if (countField) {
                    countField.value = selectedIds.length;
                }

                // Ensure the molecule_id is also set in the prefixed field if it's missing
                const molIdField = parentForm.querySelector('input[name*="molecule_id"]');
                const rawMolId = parentForm.querySelector('input[name="molecule_id"]');
                if (molIdField && rawMolId && !molIdField.value) {
                    molIdField.value = rawMolId.value;
                }
            }

            if (display) {
                display.textContent = `${selectedIds.length} animal(s) selected`;
                display.className = `form-text ${selectedIds.length > 0 ? 'text-success' : 'text-muted'}`;
            }
        }
    }
});

/**
 * groups_common.js
 * Shared JavaScript for group management pages (list and edit).
 */
document.addEventListener('DOMContentLoaded', function () {
    // --- Declare Dead Modal Logic ---
    const declareDeadModalEl = document.getElementById('declareDeadModal');
    if (declareDeadModalEl) {
        const modalInstance = new bootstrap.Modal(declareDeadModalEl);
        const modalTitle = declareDeadModalEl.querySelector('.modal-title');
        const modalGroupIdInput = declareDeadModalEl.querySelector('#modalGroupId');
        const table = declareDeadModalEl.querySelector('#declareDeadAnimalsTable');
        const header = table.querySelector('thead');
        const body = table.querySelector('tbody');

        // Fix for modal backdrop issue
        declareDeadModalEl.addEventListener('hidden.bs.modal', function() {
            // Remove any remaining backdrop elements
            const backdrops = document.querySelectorAll('.modal-backdrop');
            backdrops.forEach(backdrop => {
                backdrop.remove();
            });
            // Remove modal-open class from body
            document.body.classList.remove('modal-open');
            // Reset body style
            document.body.style.paddingRight = '';
        });

        // Use event delegation for buttons that might not exist on page load
        document.body.addEventListener('click', function (event) {
            const declareDeadBtn = event.target.closest('.declare-dead-btn');
            if (!declareDeadBtn) return;

            const groupId = declareDeadBtn.dataset.groupId;
            const groupName = declareDeadBtn.dataset.groupName;
            const animalDataId = `animal-data-${groupId}`;
            const animalDataScript = document.getElementById(animalDataId);
            let animalData = [];

            if (!animalDataScript) {
                console.warn('Animal data script not found for group:', groupId);
                // Return only on Edit page where we expect the script
                if (window.location.pathname.includes('/groups/edit/')) return;
            } else {
                try {
                    animalData = JSON.parse(animalDataScript.textContent);
                } catch (e) {
                    console.error('Error parsing animal data:', e);
                }
            }

            let modelFields = [];
            try {
                // 1. Try to get fields from a script tag first (more reliable for large JSON on Edit page)
                const modelFieldsId = declareDeadBtn.dataset.modelFieldsId || `model-fields-${groupId}`;
                const modelFieldsScript = document.getElementById(modelFieldsId);

                if (modelFieldsScript) {
                    modelFields = JSON.parse(modelFieldsScript.textContent);
                } else {
                    // 2. Fallback to data attribute (Common for List page)
                    // Using jQuery's .data() is more robust for automatic JSON parsing and HTML unescaping
                    const dataFields = $(declareDeadBtn).data('modelFields');
                    if (dataFields) {
                        if (typeof dataFields === 'string') {
                            let rawStr = dataFields;
                            if (rawStr.includes("'") && !rawStr.includes('"')) {
                                rawStr = rawStr.replace(/'/g, '"');
                            }
                            modelFields = JSON.parse(rawStr);
                        } else {
                            modelFields = dataFields;
                        }
                    }
                }
            } catch (e) {
                console.error('Error parsing model fields:', e,
                    'Raw dataset value:', declareDeadBtn.dataset.modelFields,
                    'jQuery data value:', $(declareDeadBtn).data('modelFields'));
                modelFields = [];
            }

            modalTitle.textContent = `Declare Animal(s) as Dead for Group: ${groupName}`;
            modalGroupIdInput.value = groupId;

            // Clear previous content
            header.innerHTML = '';
            body.innerHTML = '';

            // Build Header
            const headerRow = header.insertRow();
            let th = headerRow.insertCell();
            const selectAllCheckbox = document.createElement('input');
            selectAllCheckbox.type = 'checkbox';
            selectAllCheckbox.id = 'selectAllAnimalsDeadModal';
            th.appendChild(selectAllCheckbox);

            modelFields.forEach(field => {
                if (field.name === 'ID' || field.name === 'Genotype' || field.name === 'Cage') { // Show only key fields
                    th = headerRow.insertCell();
                    th.textContent = field.name;
                }
            });
            th = headerRow.insertCell();
            th.textContent = 'Status';

            // Build Body
            animalData.forEach((animal, index) => {
                const row = body.insertRow();
                if (animal.status === 'dead') {
                    row.classList.add('table-danger');
                }

                let cell = row.insertCell();
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.name = 'animal_indices';
                checkbox.value = index;
                if (animal.status === 'dead') {
                    checkbox.disabled = true;
                }
                cell.appendChild(checkbox);

                modelFields.forEach(field => {
                    if (field.name === 'ID' || field.name === 'Genotype' || field.name === 'Cage') {
                        cell = row.insertCell();
                        cell.textContent = animal[field.name] || '';
                    }
                });

                cell = row.insertCell();
                if (animal.status === 'dead') {
                    cell.textContent = `Dead (${animal.death_date || 'N/A'})`;
                }
            });

            selectAllCheckbox.addEventListener('change', function () {
                body.querySelectorAll('input[name="animal_indices"]:not([disabled])').forEach(checkbox => {
                    checkbox.checked = this.checked;
                });
            });

            modalInstance.show();


        });

        const submitButton = document.getElementById('submitDeclareDead');
        if (submitButton) {
            submitButton.addEventListener('click', function () {
                const groupId = document.getElementById('modalGroupId').value;
                const form = document.getElementById('declareDeadForm');
                const animal_indices = Array.from(form.querySelectorAll('input[name="animal_indices"]:checked')).map(cb => cb.value);
                const death_date = form.querySelector('#death_date').value;

                if (!death_date) {
                    alert("Please select a date of death.");
                    return;
                }
                if (animal_indices.length === 0) {
                    alert("Please select at least one animal.");
                    return;
                }

                fetch(`/groups/declare_dead/${groupId}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': document.querySelector('input[name="csrf_token"]').value
                    },
                    body: JSON.stringify({
                        animal_indices: animal_indices,
                        death_date: death_date
                    })
                })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            location.reload();
                        } else {
                            alert("An error occurred: " + data.message);
                        }
                    });
            });
        }
    }
});

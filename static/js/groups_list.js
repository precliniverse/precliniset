/**
 * static/js/groups_list.js
 * Handles the Server-Side DataTable, Sidebar Navigation, and Batch Actions for Experimental Groups.
 */

document.addEventListener('DOMContentLoaded', function () {
    // 1. Load Configuration
    const configEl = document.getElementById('groups-list-config');
    if (!configEl) return;
    const CONFIG = JSON.parse(configEl.textContent);

    let currentProjectId = '';
    let selectAllMatchingMode = false;
    let totalRecordsFiltered = 0;

    // --- Helper: Debounce ---
    function debounce(func, wait) {
        let timeout;
        return function (...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    // --- Helper: Format Message ---
    function formatMsg(msg, value) {
        return msg.replace(/%s/g, value).replace(/\{\}/g, value).replace(/\{0\}/g, value);
    }

    // --- Helper: Get Selected IDs ---
    function getSelectedGroupIds() {
        return Array.from(document.querySelectorAll('.group-select-checkbox:checked')).map(cb => cb.value);
    }

    // --- 1. Sidebar & Archive Logic ---
    function syncArchiveState() {
        const showArchived = $('#showArchivedSidebar').is(':checked');

        // Sidebar visibility
        if (showArchived) $('.archived-node').show();
        else $('.archived-node').hide();

        // Table Filter
        const statusSelect = $('#status_filter');
        if (showArchived) {
            // If sidebar shows archived, switch table to "All" if it was "Active Only"
            if (statusSelect.val() === 'false') statusSelect.val('all');
        } else {
            // If sidebar hides archived, force table to "Active Only"
            statusSelect.val('false');
        }
        table.draw();
    }

    // NOTE: Sidebar search is now handled by inline script in project_sidebar.html component

    $('#showArchivedSidebar').on('change', syncArchiveState);

    $('.project-link').on('click', function (e) {
        e.preventDefault();
        $('.nav-link').removeClass('active');
        $(this).addClass('active');
        currentProjectId = $(this).data('projectId');
        $('#page-title').text($(this).text().trim());

        // Reset selection when changing context
        selectAllMatchingMode = false;
        $('#selectAllServer').prop('checked', false);
        updateSelectionUI();

        table.draw();
    });

    $('#viewAllLink').on('click', function (e) {
        e.preventDefault();
        $('.nav-link').removeClass('active');
        $(this).addClass('active');
        currentProjectId = '';
        $('#page-title').text('All Experimental Groups');

        // Reset selection
        selectAllMatchingMode = false;
        $('#selectAllServer').prop('checked', false);
        updateSelectionUI();

        table.draw();
    });

    // --- 2. Initialize DataTable (Server Side) ---
    const columnsConfig = [
        {
            "data": "id",
            "render": function (data, type, row) {
                return `<input type="checkbox" class="group-select-checkbox form-check-input" value="${row.id}">`;
            },
            "orderable": false,
            "searchable": false,
            "className": "no-row-click text-center"
        },
        { "data": "name" },
        { "data": "project_name" },
        { "data": "team_name" },
        { "data": "model_name" },
        { "data": "animal_count", "defaultContent": "0", "orderable": false, "className": "text-center" },
        {
            "data": "is_archived",
            "render": function (data, type, row) {
                return data ? '<span class="badge bg-warning text-dark">Archived</span>' : '<span class="badge bg-success">Active</span>';
            },
            "className": "text-center"
        },
        { "data": "actions", "orderable": false, "searchable": false, "className": "text-end no-row-click" }
    ];

    const table = $('#groupsServerTable').DataTable({
        "processing": true,
        "serverSide": true,
        "ajax": {
            "url": CONFIG.urls.serverSideData,
            "headers": {
                "X-CSRFToken": CONFIG.csrfToken
            },
            "data": function (d) {
                d.project_id = currentProjectId;
                d.team_id = $('#team_filter').val();
                d.model_id = $('#model_filter').val();
                d.is_archived = $('#status_filter').val();
            },
            "dataSrc": function (json) {
                totalRecordsFiltered = json.recordsFiltered;
                return json.data;
            }
        },
        "columns": columnsConfig,
        "order": [[6, "desc"]], // Default sort by updated_at
        "pageLength": 25,
        "language": {
            "processing": '<div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div>',
            "search": CONFIG.i18n.searchPlaceholder,
            "lengthMenu": "Show _MENU_",
            "info": "_START_ to _END_ of _TOTAL_",
            "paginate": {
                "first": "«",
                "last": "»",
                "next": "›",
                "previous": "‹"
            }
        },
        "createdRow": function (row, data, dataIndex) {
            $(row).addClass('clickable-row').attr('data-href', `/groups/edit/${data.id}`);
        },
        "drawCallback": function () {
            updateSelectionUI();

            // Re-attach event listeners for dynamically loaded buttons
            $('.archive-group-btn').off('click').on('click', function (e) {
                e.stopPropagation();
                const groupId = $(this).data('group-id');
                if (confirm(CONFIG.i18n.confirmArchive)) {
                    batchArchive([groupId], false);
                }
            });

            $('.delete-group-btn').off('click').on('click', function (e) {
                e.stopPropagation();
                const groupId = $(this).data('group-id');
                if (confirm(CONFIG.i18n.confirmDelete)) {
                    batchDelete([groupId], false);
                }
            });
        }
    });

    // --- 3. Live Filters ---
    const reloadTable = () => {
        selectAllMatchingMode = false;
        $('#selectAllServer').prop('checked', false);
        $('.group-select-checkbox').prop('checked', false);
        updateSelectionUI();
        table.draw();
    };

    $('.filter-input').on('change', reloadTable);

    // Sync sidebar if user manually changes status filter
    $('#status_filter').on('change', function () {
        const val = $(this).val();
        if (val === 'false') {
            $('#showArchivedSidebar').prop('checked', false);
            $('.archived-node').hide();
        } else {
            $('#showArchivedSidebar').prop('checked', true);
            $('.archived-node').show();
        }
        reloadTable();
    });

    // --- 4. Row Click Logic ---
    $('#groupsServerTable tbody').on('click', 'tr', function (e) {
        // Prevent navigation if clicking on checkbox, buttons, or links
        if ($(e.target).closest('.no-row-click, input[type="checkbox"], button, a').length) return;

        const url = $(this).data('href');
        if (url) {
            window.location.href = url;
        }
    });

    // --- 5. Selection Logic ---
    const selectAllCheckbox = document.getElementById('selectAllServer');
    const banner = document.getElementById('selectAllBanner');
    const bannerMsg = document.getElementById('selectAllMessage');
    const selectAllMatchingBtn = document.getElementById('selectAllMatchingBtn');
    const selectedCountSpan = document.getElementById('selectedCount');
    const batchActionsDiv = document.getElementById('batchActions');

    function updateSelectionUI() {
        const checkedOnPage = document.querySelectorAll('.group-select-checkbox:checked').length;

        selectedCountSpan.textContent = selectAllMatchingMode ? totalRecordsFiltered : checkedOnPage;

        if (checkedOnPage > 0 || selectAllMatchingMode) {
            $(batchActionsDiv).fadeIn(200);
        } else {
            $(batchActionsDiv).fadeOut(200);
        }

        if (selectAllCheckbox.checked && !selectAllMatchingMode && totalRecordsFiltered > 0) {
            banner.style.display = 'block';
            bannerMsg.textContent = formatMsg(CONFIG.i18n.allPageSelected, checkedOnPage);
            selectAllMatchingBtn.textContent = formatMsg(CONFIG.i18n.selectAllMatching, totalRecordsFiltered);
        } else if (selectAllMatchingMode) {
            banner.style.display = 'block';
            bannerMsg.textContent = formatMsg(CONFIG.i18n.allMatchingSelected, totalRecordsFiltered);
            selectAllMatchingBtn.textContent = CONFIG.i18n.clearSelection;
        } else {
            banner.style.display = 'none';
        }
    }

    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', function () {
            const checkboxes = document.querySelectorAll('.group-select-checkbox');
            checkboxes.forEach(cb => cb.checked = this.checked);
            if (!this.checked) selectAllMatchingMode = false;
            updateSelectionUI();
        });
    }

    $('#groupsServerTable tbody').on('change', '.group-select-checkbox', function () {
        updateSelectionUI();
    });

    if (selectAllMatchingBtn) {
        selectAllMatchingBtn.addEventListener('click', function (e) {
            e.preventDefault();
            if (selectAllMatchingMode) {
                selectAllMatchingMode = false;
                selectAllCheckbox.checked = false;
                document.querySelectorAll('.group-select-checkbox').forEach(cb => cb.checked = false);
            } else {
                selectAllMatchingMode = true;
            }
            updateSelectionUI();
        });
    }

    // --- 6. Batch Actions ---
    function getBatchPayload() {
        const payload = {};
        if (selectAllMatchingMode) {
            payload.select_all_matching = 'true';
            payload.search_value = table.search();
            payload.project_id = currentProjectId;
            payload.team_id = $('#team_filter').val();
            payload.model_id = $('#model_filter').val();
            payload.is_archived = $('#status_filter').val();
        } else {
            const ids = getSelectedGroupIds();
            if (ids.length === 0) {
                alert(CONFIG.i18n.noGroupsSelected);
                return null;
            }
            payload.group_ids = ids;
        }
        return payload;
    }

    function batchArchive(groupIds = null, isBatch = true) {
        let payload;
        if (isBatch) {
            payload = getBatchPayload();
            if (!payload) return;
        } else {
            payload = { group_ids: groupIds };
        }

        payload.csrf_token = CONFIG.csrfToken;

        fetch(CONFIG.urls.batchArchive, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CONFIG.csrfToken },
            body: JSON.stringify(payload)
        }).then(r => r.json()).then(data => {
            if (data.success) {
                table.draw(false);
            } else {
                alert(data.message);
            }
        }).catch(error => {
            console.error('Error:', error);
            alert(CONFIG.i18n.generalError);
        });
    }

    function batchUnarchive(groupIds = null, isBatch = true) {
        let payload;
        if (isBatch) {
            payload = getBatchPayload();
            if (!payload) return;
        } else {
            payload = { group_ids: groupIds };
        }
        payload.csrf_token = CONFIG.csrfToken;

        fetch(CONFIG.urls.batchUnarchive, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CONFIG.csrfToken },
            body: JSON.stringify(payload)
        }).then(r => r.json()).then(data => {
            if (data.success) {
                table.draw(false);
            } else {
                alert(data.message);
            }
        }).catch(error => {
            console.error('Error:', error);
            alert(CONFIG.i18n.generalError);
        });
    }

    function batchDelete(groupIds = null, isBatch = true) {
        if (!confirm(CONFIG.i18n.confirmDeleteBatch)) return;

        let payload;
        if (isBatch) {
            payload = getBatchPayload();
            if (!payload) return;
        } else {
            payload = { group_ids: groupIds };
        }
        payload.csrf_token = CONFIG.csrfToken;

        fetch(CONFIG.urls.batchDelete, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CONFIG.csrfToken },
            body: JSON.stringify(payload)
        }).then(r => r.json()).then(data => {
            if (data.success) {
                table.draw(false);
                alert(data.message);
            } else {
                alert(data.message);
            }
        }).catch(error => {
            console.error('Error:', error);
            alert(CONFIG.i18n.generalError);
        });
    }

    // Attach batch action event listeners
    $('#actionArchiveSelected').on('click', () => batchArchive());
    $('#actionUnarchiveSelected').on('click', () => batchUnarchive());
    $('#actionDeleteSelected').on('click', () => batchDelete());

    // Initialize Bootstrap tooltips for animal counts
    function initializeAnimalCountTooltips() {
        // Destroy existing tooltips first to avoid duplicates
        const existingTooltips = document.querySelectorAll('.animal-count[data-bs-toggle="tooltip"]');
        existingTooltips.forEach(function(el) {
            const tooltip = bootstrap.Tooltip.getInstance(el);
            if (tooltip) {
                tooltip.dispose();
            }
        });

        // Initialize tooltips on animal count elements
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('.animal-count[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl, {
                html: true,
                placement: 'top',
                boundary: 'window',
                customClass: 'animal-tooltip'
            });
        });
    }

    // Initialize tooltips when table is drawn
    table.on('draw', function() {
        // Small delay to ensure DOM is ready
        setTimeout(initializeAnimalCountTooltips, 100);
    });

    // Initialize tooltips on initial page load
    initializeAnimalCountTooltips();

    // --- Declare Death Button Logic ---
    $('#groupsServerTable tbody').on('click', '.declare-dead-btn', function (e) {
        e.stopPropagation();
        const btn = $(this);
        const groupId = btn.data('groupId');
        const groupName = btn.data('groupName');

        let modelFields = btn.data('modelFields');



        // If jQuery .data() automatically parsed it into an object, great.
        // If it's a string, we need to parse it.
        if (typeof modelFields === 'string') {
            try {
                // If it looks like it has single quotes instead of double quotes (invalid JSON), fix it
                // This handles cases where Python might have outputted string representation of list instead of JSON
                if (modelFields.includes("'")) {
                    modelFields = modelFields.replace(/'/g, '"');
                }
                modelFields = JSON.parse(modelFields);
            } catch (e) {
                console.error("Error parsing model fields JSON:", e);
                modelFields = [];
            }
        }

        if (!Array.isArray(modelFields)) {
            console.error("modelFields is not an array:", modelFields);
            modelFields = [];
        }

        // Fetch animal data
        fetch(`/groups/api/${groupId}/animal_data`)
            .then(r => r.json())
            .then(animalData => {
                if (animalData.error) {
                    alert(animalData.error);
                    return;
                }

                const modalEl = document.getElementById('declareDeadModal');
                const modalInstance = new bootstrap.Modal(modalEl);
                const modalTitle = modalEl.querySelector('.modal-title');
                const modalGroupIdInput = modalEl.querySelector('#modalGroupId');
                const table = modalEl.querySelector('#declareDeadAnimalsTable');
                const header = table.querySelector('thead');
                const body = table.querySelector('tbody');

                modalTitle.textContent = `Declare Animal(s) as Dead for Group: ${groupName}`;
                modalGroupIdInput.value = groupId;

                // Pre-fill defaults from group if available
                const defaultReason = btn.data('defaultEuthanasiaReason') || '';
                const defaultSeverity = btn.data('defaultSeverity') || '';

                if (defaultReason) {
                    modalEl.querySelector('#euthanasia_reason').value = defaultReason;
                }
                if (defaultSeverity) {
                    modalEl.querySelector('#severity').value = defaultSeverity;
                }

                // Clear previous
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
                    if (field.name === 'ID' || field.name === 'Genotype' || field.name === 'Cage') {
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
                        if (field.name === 'ID' || field.name === 'Genotype' || field.name === 'Cage') {
                            cell = row.insertCell();
                            cell.textContent = animal[field.name] || '';
                        }
                    });

                    cell = row.insertCell();
                    if (animal.status === 'dead') cell.textContent = `Dead (${animal.death_date || 'N/A'})`;

                    // Euthanasia Reason Cell
                    cell = row.insertCell();
                    const reasonSelect = document.createElement('select');
                    reasonSelect.className = 'form-select form-select-sm';
                    reasonSelect.name = `euthanasia_reason_${index}`;
                    reasonSelect.innerHTML = `
                        <option value="">-- Select --</option>
                        <option value="état de santé">état de santé</option>
                        <option value="fin de protocole">fin de protocole</option>
                        <option value="Point limite atteint">Point limite atteint</option>
                    `;
                    if (animal.status === 'dead') {
                        reasonSelect.disabled = true;
                        reasonSelect.value = animal.euthanasia_reason || '';
                    }
                    cell.appendChild(reasonSelect);

                    // Severity Cell
                    cell = row.insertCell();
                    const severitySelect = document.createElement('select');
                    severitySelect.className = 'form-select form-select-sm';
                    severitySelect.name = `severity_${index}`;
                    severitySelect.innerHTML = `
                        <option value="">-- Select --</option>
                        <option value="légère">légère</option>
                        <option value="modérée">modérée</option>
                        <option value="sévère">sévère</option>
                    `;
                    if (animal.status === 'dead') {
                        severitySelect.disabled = true;
                        severitySelect.value = animal.severity || '';
                    }
                    cell.appendChild(severitySelect);
                });

                selectAllCheckbox.addEventListener('change', function () {
                    body.querySelectorAll('input[name="animal_indices"]:not([disabled])').forEach(checkbox => {
                        checkbox.checked = this.checked;
                    });
                });

                // Apply to Selected Button Logic
                const applyToSelectedBtn = modalEl.querySelector('#applyToSelectedBtn');
                if (applyToSelectedBtn) {
                    applyToSelectedBtn.addEventListener('click', function() {
                        const globalReason = modalEl.querySelector('#global_euthanasia_reason').value;
                        const globalSeverity = modalEl.querySelector('#global_severity').value;

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

                            if (reasonSelect && !reasonSelect.disabled) {
                                reasonSelect.value = globalReason;
                            }
                            if (severitySelect && !severitySelect.disabled) {
                                severitySelect.value = globalSeverity;
                            }
                        });
                    });
                }

                // Ensure modal is properly disposed when hidden
                modalEl.addEventListener('hidden.bs.modal', function() {
                    // Reset form and clear dynamic content
                    const form = modalEl.querySelector('#declareDeadForm');
                    if (form) form.reset();
                    const table = modalEl.querySelector('#declareDeadAnimalsTable');
                    if (table) {
                        table.querySelector('thead').innerHTML = '';
                        table.querySelector('tbody').innerHTML = '';
                    }
                });

                modalInstance.show();
            })
            .catch(err => console.error(err));
    });

    // Submit handler for the modal (ensure it's bound only once)
    const submitDeadBtn = document.getElementById('submitDeclareDead');
    if (submitDeadBtn) {
        // Remove existing listener to prevent duplicates if re-initialized
        const newSubmitBtn = submitDeadBtn.cloneNode(true);
        submitDeadBtn.parentNode.replaceChild(newSubmitBtn, submitDeadBtn);

        newSubmitBtn.addEventListener('click', function () {
            const groupId = document.getElementById('modalGroupId').value;
            const form = document.getElementById('declareDeadForm');
            const death_date = form.querySelector('#death_date').value;

            if (!death_date) { alert("Please select a date of death."); return; }

            // Collect per-animal data
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

            fetch(`/groups/declare_dead/${groupId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CONFIG.csrfToken
                },
                body: JSON.stringify({
                    death_date: death_date,
                    animals: animalData
                })
            })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        bootstrap.Modal.getInstance(document.getElementById('declareDeadModal')).hide();
                        window.location.reload();
                    } else {
                        alert("Error: " + data.message);
                    }
                });
        });
    }
});

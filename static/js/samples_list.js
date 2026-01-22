/**
 * static/js/samples_list.js
 * Handles the Server-Side DataTable, Sidebar Navigation, and Batch Actions for the Samples Explorer.
 */

document.addEventListener('DOMContentLoaded', function () {
    // 1. Load Configuration
    const configEl = document.getElementById('samples-list-config');
    if (!configEl) return;
    const CONFIG = JSON.parse(configEl.textContent);

    let currentGroupId = '';
    let currentProjectSlug = '';
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
    function getSelectedSampleIds() {
        return Array.from(document.querySelectorAll('.sample-select-checkbox:checked')).map(cb => cb.value);
    }

    // --- Sidebar & Archive Logic ---
    function syncArchiveState() {
        const showArchived = $('#showArchivedSidebar').is(':checked');

        // 1. Toggle Sidebar Projects
        if (showArchived) $('.archived-node').show();
        else $('.archived-node').hide();

        // 2. Redraw table (server will handle filtering based on show_archived param)
        table.draw();
    }

    $('#showArchivedSidebar').on('change', syncArchiveState);

    // --- 1. Initialize DataTable (Server Side) ---
    const columnsConfig = [
        { "data": "0", "orderable": false, "searchable": false }, // Checkbox
        { "data": "1" }, // ID
        { "data": "2", "orderable": false }, // Animal
        { "data": "3" }, // Type
        { "data": "4", "orderable": false }, // Details
        { "data": "5" }, // Date
        { "data": "6" }, // Terminal
    ];

    if (CONFIG.storageId === null) {
        columnsConfig.push({ "data": "7", "orderable": false }); // Storage
    }

    columnsConfig.push(
        { "data": "8" }, // Status
        { "data": "9", "orderable": false }, // Notes
        { "data": "10", "orderable": false } // Actions
    );

    const table = $('#samplesServerTable').DataTable({
        "processing": true,
        "serverSide": true,
        "ajax": {
            "url": CONFIG.urls.serverSideData,
            "data": function (d) {
                // Context
                if (currentGroupId) {
                    d.group_id = currentGroupId;
                    d.project_slug = '';
                } else if (currentProjectSlug) {
                    d.project_slug = currentProjectSlug;
                    d.group_id = '';
                } else {
                    d.group_id = '';
                    d.project_slug = '';
                }

                d.storage_id = CONFIG.storageId;

                // Filters
                d.status_filter = $('#status_filter').val();
                d.sample_type = $('#type_filter').val();
                d.organ_id = $('#organ_filter').val();
                if ($('#storage_filter').length && $('#storage_filter').val()) {
                    d.storage_id = $('#storage_filter').val();
                }
                
                // New Filters
                d.condition_id = $('#condition_filter').val();
                d.staining_id = $('#staining_filter').val();
                d.anticoagulant_id = $('#anticoagulant_filter').val();
                d.derived_type_id = $('#derived_type_filter').val();

                d.date_from = $('#date_from').val();
                d.date_to = $('#date_to').val();

                // Archive State
                d.show_archived = $('#showArchivedSidebar').is(':checked');
            },
            "dataSrc": function (json) {
                totalRecordsFiltered = json.recordsFiltered;
                return json.data;
            }
        },
        "columns": columnsConfig,
        "order": [[5, "desc"]],
        "pageLength": 25,
        "language": {
            "processing": '<div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div>',
            "search": CONFIG.i18n.searchPlaceholder,
            "lengthMenu": CONFIG.i18n.lengthMenu,
            "info": CONFIG.i18n.info,
            "paginate": {
                "first": CONFIG.i18n.first,
                "last": CONFIG.i18n.last,
                "next": CONFIG.i18n.next,
                "previous": CONFIG.i18n.previous
            }
        },
        "drawCallback": function () {
            updateSelectionUI();
        }
    });

    // --- 2. Sidebar Navigation ---
    $('#sidebarSearch').on('keyup', function () {
        const val = $(this).val().toLowerCase();
        $('.project-item').each(function () {
            const text = $(this).text().toLowerCase();
            $(this).toggle(text.indexOf(val) > -1);
        });
        $('.team-section').each(function () {
            const visibleProjects = $(this).find('.project-item:visible').length;
            $(this).toggle(visibleProjects > 0);
        });
    });

    $('#viewAllLink').on('click', function (e) {
        e.preventDefault();
        $('.nav-link').removeClass('active');
        $(this).addClass('active');
        currentGroupId = '';
        currentProjectSlug = ''; // Clear project selection
        $('#current-context').text(CONFIG.i18n.viewingAll);
        table.draw();
    });

    $('.project-link').on('click', function (e) {
        e.preventDefault();
        $('.nav-link').removeClass('active');
        $(this).addClass('active');
        currentProjectSlug = $(this).data('projectSlug');
        currentGroupId = '';
        const projectName = $(this).text().trim();
        $('#current-context').text(`Project: ${projectName}`);
        table.draw();
    });

    // Note: Group links logic might need adjustment if groups are listed in sidebar
    // Currently sidebar only shows projects. If groups are added, add listener here.

    // --- 3. Live Filters ---
    const reloadTable = () => {
        selectAllMatchingMode = false;
        $('#selectAllServer').prop('checked', false);
        $('.sample-select-checkbox').prop('checked', false);
        updateSelectionUI();
        table.draw();
    };

    $('#date_from, #date_to').on('input', debounce(reloadTable, 500));
    $('#date_from, #date_to').on('input', debounce(reloadTable, 500));
    $('.filter-input').not('[multiple]').on('change', reloadTable);

    // Initialize Select2 for multiple selects
    $('.filter-input[multiple]').select2({
        theme: "bootstrap-5",
        width: '100%',
        allowClear: true,
        placeholder: function() {
            $(this).data('placeholder');
        }
    });
    // Trigger reload on select2 change
    $('.filter-input[multiple]').on('change', reloadTable);

    // --- 4. Selection Logic ---
    const selectAllCheckbox = document.getElementById('selectAllServer');
    const banner = document.getElementById('selectAllBanner');
    const bannerMsg = document.getElementById('selectAllMessage');
    const selectAllMatchingBtn = document.getElementById('selectAllMatchingBtn');
    const selectedCountSpan = document.getElementById('selectedCount');
    const batchActionsDiv = document.getElementById('batchActions');

    function updateSelectionUI() {
        const checkedOnPage = document.querySelectorAll('.sample-select-checkbox:checked').length;
        const totalOnPage = document.querySelectorAll('.sample-select-checkbox').length;

        selectedCountSpan.textContent = selectAllMatchingMode ? totalRecordsFiltered : checkedOnPage;
        batchActionsDiv.style.display = (checkedOnPage > 0 || selectAllMatchingMode) ? 'block' : 'none';

        if (selectAllCheckbox.checked && !selectAllMatchingMode && totalRecordsFiltered > totalOnPage) {
            if (banner) {
                banner.style.display = 'block';
                bannerMsg.textContent = formatMsg(CONFIG.i18n.allPageSelected, totalOnPage);
                selectAllMatchingBtn.textContent = formatMsg(CONFIG.i18n.selectAllMatching, totalRecordsFiltered);
            }
        } else if (selectAllMatchingMode) {
            if (banner) {
                banner.style.display = 'block';
                bannerMsg.textContent = formatMsg(CONFIG.i18n.allMatchingSelected, totalRecordsFiltered);
                selectAllMatchingBtn.textContent = CONFIG.i18n.clearSelection;
            }
        } else {
            if (banner) banner.style.display = 'none';
        }
    }

    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', function () {
            const checkboxes = document.querySelectorAll('.sample-select-checkbox');
            checkboxes.forEach(cb => cb.checked = this.checked);
            if (!this.checked) selectAllMatchingMode = false;
            updateSelectionUI();
        });
    }

    $('#samplesServerTable tbody').on('change', '.sample-select-checkbox', function () {
        updateSelectionUI();
    });

    if (selectAllMatchingBtn) {
        selectAllMatchingBtn.addEventListener('click', function () {
            if (selectAllMatchingMode) {
                selectAllMatchingMode = false;
                selectAllCheckbox.checked = false;
                document.querySelectorAll('.sample-select-checkbox').forEach(cb => cb.checked = false);
            } else {
                selectAllMatchingMode = true;
            }
            updateSelectionUI();
        });
    }

    // --- 5. Batch Actions ---
    function getBatchPayload() {
        const payload = {};
        if (selectAllMatchingMode) {
            payload.select_all_matching = 'true';

            if (currentGroupId) payload.group_id = currentGroupId;
            else if (currentProjectSlug) payload.project_slug = currentProjectSlug;

            if (CONFIG.storageId) payload.storage_id = CONFIG.storageId;

            payload.status_filter = $('#status_filter').val();
            payload.sample_type = $('#type_filter').val();
            payload.organ_id = $('#organ_filter').val();

            if ($('#storage_filter').length && $('#storage_filter').val()) {
                payload.storage_id = $('#storage_filter').val();
            }

            payload.condition_id = $('#condition_filter').val();
            payload.date_from = $('#date_from').val();
            payload.date_to = $('#date_to').val();
            payload.search_value = table.search();

            // Pass archive state
            payload.show_archived = $('#showArchivedSidebar').is(':checked');
        } else {
            const ids = getSelectedSampleIds();
            payload.sample_ids = ids.join(',');
        }
        return payload;
    }

    // Change Storage
    const newStorageLocationSelect = document.getElementById('newStorageLocation');
    const changeStorageModalEl = document.getElementById('changeStorageModal');
    let changeStorageModal = null;
    if (changeStorageModalEl) {
        changeStorageModal = new bootstrap.Modal(changeStorageModalEl);
    }

    const actionChangeStorageBtn = document.getElementById('actionChangeStorage');
    if (actionChangeStorageBtn) {
        actionChangeStorageBtn.addEventListener('click', function () {
            if (getSelectedSampleIds().length === 0 && !selectAllMatchingMode) {
                alert(CONFIG.i18n.selectSamplesFirst);
                return;
            }

            if (changeStorageModal) changeStorageModal.show();

            fetch(CONFIG.urls.getStorageLocations)
                .then(r => r.json())
                .then(data => {
                    if (newStorageLocationSelect) {
                        newStorageLocationSelect.innerHTML = '';
                        if (data.success && data.storage_locations.length > 0) {
                            data.storage_locations.forEach(loc => {
                                const opt = document.createElement('option');
                                opt.value = loc.id;
                                opt.textContent = loc.name;
                                newStorageLocationSelect.appendChild(opt);
                            });
                        }
                    }
                });
        });
    }

    const confirmChangeStorageBtn = document.getElementById('confirmChangeStorage');
    if (confirmChangeStorageBtn) {
        confirmChangeStorageBtn.addEventListener('click', function () {
            const payload = getBatchPayload();
            if (!payload.sample_ids && !payload.select_all_matching) return;

            const storageId = newStorageLocationSelect ? newStorageLocationSelect.value : null;
            if (!storageId) return;

            const jsonPayload = { ...payload, new_storage_location_id: storageId };
            if (jsonPayload.sample_ids) jsonPayload.sample_ids = jsonPayload.sample_ids.split(',').map(Number);

            fetch(CONFIG.urls.batchChangeStorage, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CONFIG.csrfToken },
                body: JSON.stringify(jsonPayload)
            }).then(r => r.json()).then(data => {
                if (data.success) {
                    if (changeStorageModal) changeStorageModal.hide();
                    table.draw(false);
                    alert(data.message);
                } else { alert(data.message); }
            });
        });
    }

    // Generic Status Update
    function updateStatus(newStatus, destination = null) {
        const payload = getBatchPayload();
        if (!payload.sample_ids && !payload.select_all_matching) return;

        const formData = new FormData();
        formData.append('csrf_token', CONFIG.csrfToken);
        for (const key in payload) formData.append(key, payload[key]);

        let url = "";
        if (newStatus === 'SHIPPED') {
            url = CONFIG.urls.batchShip;
            formData.append('destination', destination);
        } else if (newStatus === 'DESTROYED') {
            url = CONFIG.urls.batchDestroy;
        } else if (newStatus === 'NOT_COLLECTED') {
            url = CONFIG.urls.batchNotCollected;
        } else if (newStatus === 'STORED') {
            url = CONFIG.urls.batchStore;
        }

        fetch(url, { method: 'POST', body: formData }).then(r => r.json()).then(data => {
            if (data.success) { table.draw(false); alert(data.message); }
            else { alert(data.message); }
        });
    }

    const actionShipBtn = document.getElementById('actionShip');
    if (actionShipBtn) {
        actionShipBtn.addEventListener('click', function () {
            const dest = prompt(CONFIG.i18n.enterDestination);
            if (dest) updateStatus('SHIPPED', dest);
        });
    }

    const actionDestroyBtn = document.getElementById('actionDestroy');
    if (actionDestroyBtn) {
        actionDestroyBtn.addEventListener('click', function () {
            if (confirm(CONFIG.i18n.confirmDestroy)) updateStatus('DESTROYED');
        });
    }

    const actionStoreBtn = document.getElementById('actionStore');
    if (actionStoreBtn) {
        actionStoreBtn.addEventListener('click', function () {
            updateStatus('STORED');
        });
    }

    const actionNotCollectedBtn = document.getElementById('actionNotCollected');
    if (actionNotCollectedBtn) {
        actionNotCollectedBtn.addEventListener('click', function () {
            if (confirm('Are you sure you want to mark these samples as NOT COLLECTED?')) {
                updateStatus('NOT_COLLECTED');
            }
        });
    }

    const actionDownloadBtn = document.getElementById('actionDownloadXLSX');
    if (actionDownloadBtn) {
        actionDownloadBtn.addEventListener('click', function () {
            const payload = getBatchPayload();
            if (payload.select_all_matching) {
                alert("Bulk download for 'Select All Matching' is not yet implemented via this button.");
            } else if (payload.sample_ids) {
                window.location.href = CONFIG.urls.downloadFile + `?sample_ids=${payload.sample_ids}&format=excel`;
            }
        });
    }
});
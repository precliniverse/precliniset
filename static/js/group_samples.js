/**
 * static/js/group_samples.js
 * Handles Server-Side DataTable and Batch Actions for a specific Group.
 */

document.addEventListener('DOMContentLoaded', function () {
    // 1. Load Configuration
    const configEl = document.getElementById('group-samples-config');
    if (!configEl) return;
    const CONFIG = JSON.parse(configEl.textContent);

    let selectAllMatchingMode = false;
    let totalRecordsFiltered = 0;

    // --- Helper: Debounce ---
    function debounce(func, wait) {
        let timeout;
        return function(...args) {
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

    // --- 1. Initialize DataTable (Server Side) ---
    const table = $('#groupSamplesTable').DataTable({
        "processing": true,
        "serverSide": true,
        "ajax": {
            "url": CONFIG.urls.serverSideData,
            "data": function (d) {
                // Context: Fixed Group ID
                d.group_id = CONFIG.groupId;
                
                // Filters
                d.status_filter = $('#status_filter').val();
                d.sample_type = $('#type_filter').val();
                d.organ_id = $('#organ_filter').val();
                d.storage_id = $('#storage_filter').val();
                d.storage_id = $('#storage_filter').val();
                
                // New Filters (Arrays)
                d.condition_id = $('#condition_filter').val();
                d.staining_id = $('#staining_filter').val();
                d.anticoagulant_id = $('#anticoagulant_filter').val();
                d.derived_type_id = $('#derived_type_filter').val();

                d.date_from = $('#date_from').val();
                d.date_to = $('#date_to').val();
                
                // Handle multi-select status from the top filter if it exists
                const topStatusFilter = $('#status_filter_select').val();
                if (topStatusFilter && !d.status_filter) {
                     if (topStatusFilter.includes('all')) d.status_filter = 'all';
                     else d.status_filter = topStatusFilter.join(',');
                }
            },
            "dataSrc": function(json) {
                totalRecordsFiltered = json.recordsFiltered;
                return json.data;
            }
        },
        "columns": [
            { "data": "0", "orderable": false, "searchable": false }, // Checkbox
            { "data": "1" }, // ID
            { "data": "2", "orderable": false }, // Animal
            { "data": "3" }, // Type
            { "data": "4", "orderable": false }, // Details
            { "data": "5" }, // Date
            { "data": "6" }, // Terminal
            { "data": "7", "orderable": false }, // Storage
            { "data": "8" }, // Status
            { "data": "9", "orderable": false }, // Notes
            { "data": "10", "orderable": false } // Actions
        ],
        "order": [[ 5, "desc" ]],
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
        "drawCallback": function() { 
            updateSelectionUI(); 
        }
    });

    // --- 2. Live Filters ---
    const reloadTable = () => {
        selectAllMatchingMode = false;
        $('#selectAllServer').prop('checked', false);
        $('.sample-select-checkbox').prop('checked', false);
        updateSelectionUI();
        table.draw();
    };

    $('#date_from, #date_to').on('input', debounce(reloadTable, 500));
    $('.filter-input').on('change', reloadTable);
    $('#status_filter_select').on('change', reloadTable); // Top filter

    $('#status_filter_select').on('change', reloadTable); // Top filter

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

    // --- 3. Selection Logic ---
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
        batchActions.style.display = (checkedOnPage > 0 || selectAllMatchingMode) ? 'block' : 'none';

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
        selectAllCheckbox.addEventListener('change', function() {
            const checkboxes = document.querySelectorAll('.sample-select-checkbox');
            checkboxes.forEach(cb => cb.checked = this.checked);
            if (!this.checked) selectAllMatchingMode = false;
            updateSelectionUI();
        });
    }

    $('#groupSamplesTable tbody').on('change', '.sample-select-checkbox', function() {
        updateSelectionUI();
    });

    if (selectAllMatchingBtn) {
        selectAllMatchingBtn.addEventListener('click', function() {
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

    // --- 4. Batch Actions ---
    function getBatchPayload() {
        const payload = {};
        if (selectAllMatchingMode) {
            payload.select_all_matching = 'true';
            payload.group_id = CONFIG.groupId;
            payload.status_filter = $('#status_filter').val() || $('#status_filter_select').val()?.join(',');
            payload.sample_type = $('#type_filter').val();
            payload.organ_id = $('#organ_filter').val();
            payload.storage_id = $('#storage_filter').val();
            payload.condition_id = $('#condition_filter').val();
            payload.date_from = $('#date_from').val();
            payload.date_to = $('#date_to').val();
            payload.search_value = table.search();
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
        actionChangeStorageBtn.addEventListener('click', function() {
            if (getSelectedSampleIds().length === 0 && !selectAllMatchingMode) {
                alert(CONFIG.i18n.selectSamplesFirst);
                return;
            }
            
            // Explicitly show the modal
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
                        } else {
                            // No storage locations returned or success is false.
                        }
                    } else {
                        // newStorageLocationSelect element not found in modal.
                    }
                });
        });
    }

    const confirmChangeStorageBtn = document.getElementById('confirmChangeStorage');
    if (confirmChangeStorageBtn) {
        confirmChangeStorageBtn.addEventListener('click', function() {
            const payload = getBatchPayload();
            if (!payload.sample_ids && !payload.select_all_matching) {
                // Early exit - No samples selected.
                return;
            }
            
            const storageId = newStorageLocationSelect ? newStorageLocationSelect.value : null; // Use newStorageLocationSelect defined earlier
            if (!storageId) {
                // Early exit - storageId is null or empty.
                return;
            }

            const jsonPayload = { ...payload, new_storage_location_id: storageId };
            if (jsonPayload.sample_ids) jsonPayload.sample_ids = jsonPayload.sample_ids.split(',').map(Number);

            fetch(CONFIG.urls.batchChangeStorage, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': CONFIG.csrfToken},
                body: JSON.stringify(jsonPayload)
            }).then(r => r.json()).then(data => {
                if(data.success) {
                    if (changeStorageModal) changeStorageModal.hide();
                    table.draw(false);
                    alert(data.message);
                } else { alert(data.message); }
            });
        });
    }

    // Generic Status Update
    function updateStatus(newStatus, destination=null) {
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
            if(data.success) { table.draw(false); alert(data.message); }
            else { alert(data.message); }
        });
    }

    const actionShipBtn = document.getElementById('actionShip');
    if (actionShipBtn) {
        actionShipBtn.addEventListener('click', function() {
            const dest = prompt(CONFIG.i18n.enterDestination);
            if (dest) updateStatus('SHIPPED', dest);
        });
    }

    const actionDestroyBtn = document.getElementById('actionDestroy');
    if (actionDestroyBtn) {
        actionDestroyBtn.addEventListener('click', function() {
            if (confirm(CONFIG.i18n.confirmDestroy)) updateStatus('DESTROYED');
        });
    }

    const actionStoreBtn = document.getElementById('actionStore');
    if (actionStoreBtn) {
        actionStoreBtn.addEventListener('click', function() {
            updateStatus('STORED');
        });
    }

    const actionNotCollectedBtn = document.getElementById('actionNotCollected');
    if (actionNotCollectedBtn) {
        actionNotCollectedBtn.addEventListener('click', function() {
            if (confirm('Are you sure you want to mark these samples as NOT COLLECTED?')) {
                updateStatus('NOT_COLLECTED');
            }
        });
    }
    
    const actionDownloadBtn = document.getElementById('actionDownloadXLSX');
    if (actionDownloadBtn) {
        actionDownloadBtn.addEventListener('click', function() {
            const payload = getBatchPayload();
            if (payload.select_all_matching) {
                alert("Bulk download for 'Select All Matching' is not yet implemented via this button.");
            } else if (payload.sample_ids) {
                window.location.href = CONFIG.urls.downloadFile + `?sample_ids=${payload.sample_ids}&format=excel`;
            }
        });
    }

    // --- Action: Derive (Subsample/Slide) ---
    const actionDeriveBtn = document.getElementById('actionDerive');
    if (actionDeriveBtn) {
        actionDeriveBtn.addEventListener('click', function() {
            const payload = getBatchPayload();
            
            if (payload.select_all_matching) {
                alert(CONFIG.i18n.selectSamplesFirst || "Please select specific samples to derive from (Select All Matching not supported for derivation yet).");
                return;
            }

            if (!payload.sample_ids) {
                alert(CONFIG.i18n.selectSamplesFirst);
                return;
            }

            // Redirect to the derivation page with parent IDs
            window.location.href = CONFIG.urls.logDerivedSamples + `?parent_sample_ids=${payload.sample_ids}`;
        });
    }
});
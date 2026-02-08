/**
 * static/js/datatables_list.js
 * Handles the Server-Side DataTable, Sidebar Navigation, and Batch Actions for DataTables.
 */

document.addEventListener('DOMContentLoaded', function () {
    // 1. Load Configuration
    const configEl = document.getElementById('datatables-list-config');
    if (!configEl) return;
    const CONFIG = JSON.parse(configEl.textContent);

    let currentProjectId = '';
    // PERSISTENT SELECTION SET
    let selectedIds = new Set();

    // --- Helper: Debounce ---
    function debounce(func, wait) {
        let timeout;
        return function (...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    // --- Sidebar & Archive Logic ---
    function syncArchiveState() {
        const showArchived = $('#showArchivedSidebar').is(':checked');

        // 1. Toggle Sidebar Projects
        if (showArchived) $('.archived-node').show();
        else $('.archived-node').hide();

        // 2. Update Table Filter
        const statusSelect = $('#status_filter');
        if (statusSelect.length) {
            if (showArchived) {
                if (statusSelect.val() === 'false') statusSelect.val('all');
            } else {
                statusSelect.val('false');
            }
        }

        // 3. Redraw
        table.draw();
    }

    $('#sidebarSearch').on('keyup', function () {
        const val = $(this).val().toLowerCase();
        $('.project-item').each(function () {
            const text = $(this).text().toLowerCase();
            $(this).toggle(text.indexOf(val) > -1);
        });
        // Also filter team sections
        $('.team-section').each(function () {
            const visibleProjects = $(this).find('.project-item:visible').length;
            $(this).toggle(visibleProjects > 0);
        });
    });

    $('#showArchivedSidebar').on('change', syncArchiveState);

    $('.project-link').on('click', function (e) {
        e.preventDefault();
        $('.nav-link').removeClass('active');
        $(this).addClass('active');
        currentProjectId = $(this).data('projectId');
        $('#dt-page-title').text($(this).text().trim());

        table.draw();
    });

    $('#viewAllLink').on('click', function (e) {
        e.preventDefault();
        $('.nav-link').removeClass('active');
        $(this).addClass('active');
        currentProjectId = '';
        $('#dt-page-title').text('All DataTables');
        table.draw();
    });

    // --- DataTable ---
    const table = $('#datatablesServerTable').DataTable({
        "processing": true,
        "serverSide": true,
        "ajax": {
            "url": CONFIG.urls.serverSideData,
            "headers": {
                "X-CSRFToken": CONFIG.csrfToken
            },
            "data": function (d) {
                d.project_id = currentProjectId;
                // Fix: Send group_id if present in config (for group-specific view)
                if (CONFIG.groupId) {
                    d.group_id = CONFIG.groupId;
                }
                d.is_archived = $('#status_filter').val();
                d.protocol_id = $('#protocol_filter').val();
                d.date_from = $('#date_from').val();
                d.date_to = $('#date_to').val();
            }
        },
        "columns": [
            {
                "data": "id",
                "orderable": false,
                "className": "no-row-click text-center",
                "render": function (data) {
                    const checked = selectedIds.has(data.toString()) ? 'checked' : '';
                    return `<input type="checkbox" class="dt-select-cb form-check-input" value="${data}" ${checked}>`;
                }
            },
            { "data": "date" },
            { "data": "protocol_name" },
            { "data": "group_name" },
            { "data": "project_name" },
            { "data": "actions", "orderable": false, "className": "text-end no-row-click" }
        ],
        "order": [[1, "desc"]],
        "createdRow": function (row, data) {
            $(row).addClass('clickable-row').attr('data-href', `/datatables/view/${data.id}`);
        },
        "drawCallback": function () {
            updateBatchUI();

            // Re-attach delete listeners (no longer needed for individual buttons, handled by form)
            // Add a generic confirmation for forms with class 'confirm-delete-form'
            $(document).off('submit', 'form.confirm-delete-form').on('submit', 'form.confirm-delete-form', function (e) {
                const message = $(this).data('confirm-message') || CONFIG.i18n.confirmDelete || 'Are you sure you want to delete this item?';
                if (!confirm(message)) {
                    e.preventDefault();
                }
            });

            // Update CSRF tokens for dynamically added delete forms
            $('form.confirm-delete-form').each(function () {
                $(this).find('input[name="csrf_token"]').val(CONFIG.csrfToken);
            });

            // Update state of selectAllServer checkbox
            const $allCheckboxes = $('.dt-select-cb');
            const $checkedCheckboxes = $allCheckboxes.filter(':checked');
            $('#selectAllServer').prop('checked', $allCheckboxes.length > 0 && $allCheckboxes.length === $checkedCheckboxes.length);
        }
    });

    // --- Select All Checkbox ---
    $('#selectAllServer').on('click', function () {
        const isChecked = this.checked;
        $('.dt-select-cb').each(function () {
            $(this).prop('checked', isChecked);
            const id = this.value;
            if (isChecked) selectedIds.add(id);
            else selectedIds.delete(id);
        });
        updateBatchUI();
    });

    // --- Live Filters ---
    $('#status_filter').on('change', function () {
        const val = $(this).val();
        if (val === 'false') {
            $('#showArchivedSidebar').prop('checked', false);
            $('.archived-node').hide();
        } else {
            $('#showArchivedSidebar').prop('checked', true);
            $('.archived-node').show();
        }
        table.draw();
    });

    $('#protocol_filter, #date_from, #date_to').on('change', () => table.draw());

    // --- Persistent Selection Logic ---
    $('#datatablesServerTable tbody').on('change', '.dt-select-cb', function () {
        const id = this.value;
        if (this.checked) selectedIds.add(id);
        else selectedIds.delete(id);
        updateBatchUI();
    });

    function updateBatchUI() {
        const count = selectedIds.size;
        $('#dtSelectedCount').text(count);
        if (count > 0) $('#dtBatchActions').fadeIn(200);
        else $('#dtBatchActions').fadeOut(200);
    }

    $('#btnClearSelection').on('click', function () {
        selectedIds.clear();
        $('.dt-select-cb').prop('checked', false);
        updateBatchUI();
    });

    // --- Batch Actions ---
    function submitBatchForm(url) {
        const form = $('#batchDownloadForm');
        form.attr('action', url);
        form.find('input[name="selected_datatable_ids[]"]').remove(); // Clear old

        selectedIds.forEach(id => {
            form.append(`<input type="hidden" name="selected_datatable_ids[]" value="${id}">`);
        });
        form.submit();
    }

    $('#btnDownloadMerged').on('click', () => submitBatchForm(CONFIG.urls.downloadMerged));
    $('#btnDownloadTransposed').on('click', () => submitBatchForm(CONFIG.urls.downloadTransposed));

    // Analyze (GET request usually, or POST with redirect)
    $('#btnAnalyzeBatch').on('click', () => submitBatchForm(CONFIG.urls.analyzeBatch));

    // Delete (Fetch)
    $('#btnDeleteBatch').on('click', function () {
        if (!confirm("Delete selected datatables?")) return;
        fetch(CONFIG.urls.deleteBatch, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CONFIG.csrfToken },
            body: JSON.stringify({ datatable_ids: Array.from(selectedIds) })
        }).then(r => r.json()).then(data => {
            if (data.success) {
                selectedIds.clear();
                table.draw();
                alert(data.message);
            } else {
                alert(data.message);
            }
        });
    });

    // --- Row Click ---
    $('#datatablesServerTable tbody').on('click', 'tr', function (e) {
        if ($(e.target).closest('.no-row-click, input, button, a').length) return;
        const url = $(this).data('href');
        if (url) window.location.href = url;
    });

    // --- Creation Form Logic ---

    // 1. Initialize Generic Select2 (Protocol, Assignee) - Exclude Group
    $('.select2-enable').not('#group').select2({
        theme: "bootstrap-5",
        width: '100%',
        allowClear: true,
        placeholder: function () { return $(this).data('placeholder'); }
    });

    // 2. Initialize AJAX Select2 for Group (Optimized)
    $('#group').select2({
        theme: "bootstrap-5",
        width: '100%',
        placeholder: CONFIG.i18n.selectGroup,
        allowClear: true,
        ajax: {
            url: CONFIG.urls.searchGroups,
            dataType: 'json',
            delay: 250,
            data: function (params) {
                return {
                    q: params.term,
                    page: params.page || 1
                };
            },
            processResults: function (data, params) {
                params.page = params.page || 1;
                return {
                    results: data.results,
                    pagination: {
                        more: (params.page * 15) < data.total_count
                    }
                };
            },
            cache: true
        },
        minimumInputLength: 0
    });

    // 3. Toggle Creation Form
    $('#toggle-creation-form').on('click', function () {
        $('#creation-form-container').slideToggle();
        $(this).find('i.fas').toggleClass('fa-chevron-down fa-chevron-up');
    });

    $('#group').on('select2:select', function (e) {
        const groupId = e.params.data.id;
        refreshAssignableUsers(groupId);
    });

    function refreshAssignableUsers(groupId) {
        const assigneeSelect = $('select[name="assigned_to_id"]');
        if (!assigneeSelect.length) return;

        // Fetch using the new endpoint
        const url = CONFIG.urls.getAssignableUsers.replace('__GROUP_ID__', groupId);
        
        fetch(url)
            .then(response => response.json())
            .then(users => {
                // Keep the Unassigned option
                assigneeSelect.empty().append('<option value="">-- Unassigned --</option>');
                users.forEach(user => {
                    assigneeSelect.append(new Option(user.email, user.id));
                });
                assigneeSelect.trigger('change');
            })
            .catch(err => {
                console.error("Error fetching assignable users:", err);
            });
    }

    // 4. Auto-open if prefill param exists in URL
    const urlParams = new URLSearchParams(window.location.search);
    const prefillGroupId = urlParams.get('group_id_prefill');
    if (prefillGroupId) {
        $('#creation-form-container').show();
        $('#toggle-creation-form').find('i.fas').removeClass('fa-chevron-down').addClass('fa-chevron-up');
        refreshAssignableUsers(prefillGroupId);
    }
});
/**
 * datatables_edit.js
 * Handles interactions for editing DataTables (file uploads, metadata toggle).
 */

document.addEventListener('DOMContentLoaded', function () {
    // 1. Load Configuration
    const configEl = document.getElementById('datatable-editor-config');
    if (!configEl) return;
    const CONFIG = JSON.parse(configEl.textContent);

    // --- Select2 Initialization ---
    $('#housing_condition_set_id').select2({
        theme: "bootstrap-5",
        placeholder: CONFIG.i18n.selectHousing,
        allowClear: true
    });

    $('#assigned_to_id').select2({
        theme: "bootstrap-5",
        placeholder: CONFIG.i18n.unassigned,
        allowClear: true
    });

    // --- Grouping Parameters Select2 ---
    const groupByParamsSelect = $('#group_by_params');
    if (groupByParamsSelect.length) {
        groupByParamsSelect.select2({
            theme: "bootstrap-5",
            placeholder: "Select grouping parameters...",
            allowClear: true,
            width: '100%'
        });
    }

    // --- Apply Grouping Button ---
    // Build URL manually to handle multiple values correctly (Select2 + GET form issue)
    const applyGroupingBtn = document.getElementById('applyGroupingBtn');
    if (applyGroupingBtn) {
        applyGroupingBtn.addEventListener('click', function () {
            const select = document.getElementById('group_by_params');
            if (!select) return;

            const selectedValues = Array.from(select.selectedOptions).map(opt => opt.value);
            const baseUrl = window.location.pathname;
            const params = new URLSearchParams();
            selectedValues.forEach(val => params.append('group_by_params', val));

            window.location.href = baseUrl + (params.toString() ? '?' + params.toString() : '');
        });
    }


    // --- Metadata Toggle ---
    const toggleButton = document.getElementById('toggle-metadata');
    const table = document.getElementById('data-table-edit');
    let metadataVisible = false;

    if (toggleButton && table) {
        toggleButton.addEventListener('click', function () {
            metadataVisible = !metadataVisible;
            const headers = table.querySelectorAll('th.metadata-col');
            const cells = table.querySelectorAll('td.metadata-col');

            if (metadataVisible) {
                headers.forEach(th => th.style.display = 'table-cell');
                cells.forEach(td => td.style.display = 'table-cell');
                toggleButton.textContent = CONFIG.i18n.hideMetadata;
            } else {
                headers.forEach(th => th.style.display = 'none');
                cells.forEach(td => td.style.display = 'none');
                toggleButton.textContent = CONFIG.i18n.showMetadata;
            }
        });
    }

    // --- File Upload Toggle ---
    const addFileBtn = document.getElementById('add-file-btn');
    const fileUploadContainer = document.getElementById('file-upload-container');

    if (addFileBtn) {
        addFileBtn.addEventListener('click', function () {
            const fileInput = document.getElementById('worksheet-files-input');
            if (fileInput) {
                fileInput.click();
            }
        });
    }

    // --- Auto-Submit on File Selection ---
    const worksheetFilesInput = document.getElementById('worksheet-files-input');
    if (worksheetFilesInput) {
        worksheetFilesInput.addEventListener('change', function () {
            if (this.files.length > 0) {
                document.getElementById('edit-datatable-form').submit();
            }
        });
    }

    // --- Delete Confirmation ---
    document.querySelectorAll('.confirm-delete-form').forEach(form => {
        form.addEventListener('submit', function (event) {
            if (!confirm(CONFIG.i18n.confirmDelete)) {
                event.preventDefault();
            }
        });
    });
});
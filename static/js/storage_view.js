/**
 * static/js/storage_view.js
 * Handles Server-Side DataTable and Summary Interaction for Storage View.
 */

document.addEventListener('DOMContentLoaded', function () {
    const configEl = document.getElementById('storage-view-config');
    if (!configEl) return;
    const CONFIG = JSON.parse(configEl.textContent);

    let currentProjectSlug = '';
    let currentSampleType = '';

    // --- 1. Initialize DataTable (Server Side) ---
    const table = $('#storageSamplesTable').DataTable({
        "processing": true,
        "serverSide": true,
        "ajax": {
            "url": CONFIG.urls.serverSideData,
            "data": function (d) {
                // Context: Fixed Storage ID
                d.storage_id = CONFIG.storageId;
                // Only show stored samples by default in this view
                d.status_filter = 'STORED'; 
                
                // Dynamic Filters
                if (currentProjectSlug) d.project_slug = currentProjectSlug;
                if (currentSampleType) d.sample_type = currentSampleType;
            }
        },
        "columns": [
            { "data": "1" }, // ID
            { "data": "2", "orderable": false }, // Animal
            { "data": "3" }, // Type
            { "data": "4", "orderable": false }, // Details
            { "data": "5" }, // Date
            { "data": "9", "orderable": false }, // Notes
            { "data": "10", "orderable": false } // Actions
        ],
        "order": [[ 4, "desc" ]], // Sort by Date
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
        }
    });

    // --- 2. Summary Table Interaction ---
    $('.summary-row').on('click', function() {
        // Highlight selected row
        $('.summary-row').removeClass('table-active');
        $(this).addClass('table-active');

        // Update filters
        currentProjectSlug = $(this).data('project-slug');
        currentSampleType = $(this).data('sample-type');

        // Update Dropdown UI to match
        $('#projectFilter').val(currentProjectSlug);

        // Reload Table
        table.draw();
        
        // Scroll to table
        document.getElementById('storageSamplesTable').scrollIntoView({behavior: 'smooth'});
    });

    // --- 3. Project Filter Dropdown ---
    $('#projectFilter').on('change', function() {
        currentProjectSlug = this.value;
        currentSampleType = ''; // Reset type filter when project changes manually
        
        // Reset summary highlight
        $('.summary-row').removeClass('table-active');
        
        table.draw();
    });

    // --- 4. Reset Filters Button ---
    $('#resetFiltersBtn').on('click', function() {
        currentProjectSlug = '';
        currentSampleType = '';
        $('#projectFilter').val('');
        $('.summary-row').removeClass('table-active');
        table.draw();
    });
});
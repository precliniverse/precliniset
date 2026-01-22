// reference_ranges_list.js
document.addEventListener('DOMContentLoaded', function () {
    // Delete confirmation forms
    document.querySelectorAll('.delete-confirm-form').forEach(form => {
        form.addEventListener('submit', function (event) {
            const message = this.dataset.confirmMessage || 'Are you sure?';
            if (!confirm(message)) {
                event.preventDefault();
            }
        });
    });
    
    // Make list-group-items clickable, but ignore clicks on nested interactive elements
    document.querySelectorAll('.list-group-item-action[data-href]').forEach(item => {
        item.addEventListener('click', function (event) {
            // Check if the click target or any of its ancestors is an <a>, <button>, or <form>
            if (event.target.closest('a') || event.target.closest('button') || event.target.closest('form')) {
                return; // Do nothing if an interactive element inside the row was clicked
            }
            window.location.href = this.dataset.href;
        });
    });

});

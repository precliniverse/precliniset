/**
 * static/js/analysis/api.js
 * Handles API calls (Fetch Levels, Analysis Polling)
 */

const API = {
    // Polls the status of the Celery task
    pollAnalysisStatus: function (taskId, onComplete, onError) {
        const pollUrl = CONFIG.urls.analysisStatus.replace('TASK_ID', taskId);

        const poller = setInterval(() => {
            fetch(pollUrl)
                .then(response => response.json())
                .then(data => {
                    if (data.state === 'SUCCESS') {
                        clearInterval(poller);
                        onComplete(data);
                    } else if (data.state === 'FAILURE') {
                        clearInterval(poller);
                        onError(data.status);
                    } else {
                        // Update status message if available
                        if (data.status) {
                            const statusEl = document.getElementById('analysis-progress-message');
                            if (statusEl) statusEl.textContent = data.status;
                        }
                    }
                })
                .catch(err => {
                    clearInterval(poller);
                    onError(err.message);
                });
        }, 2000); // Poll every 2s
    },

    // Fetches unique levels for selected grouping columns (for Control/Dunnett selector)
    fetchGroupLevels: async function (groupCols) {
        // Handle Merged Analysis (datatableId is null)
        let url;
        let payload = { groups: groupCols };

        if (CONFIG.datatableId) {
            url = `/datatables/api/group_levels/${CONFIG.datatableId}`;
        } else {
            // Merged Analysis: Use merged endpoint
            url = `/datatables/api/group_levels/merged`;
            // Need pass list of IDs. They should be in formData from server
            if (CONFIG.formData && CONFIG.formData.selected_datatable_ids) {
                payload.datatable_ids = CONFIG.formData.selected_datatable_ids;
            } else {
                console.warn("Merged analysis but no IDs found in CONFIG.");
                return [];
            }
        }

        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('input[name="csrf_token"]').value
                },
                body: JSON.stringify(payload)
            });
            const data = await response.json();
            return data.levels || [];
        } catch (e) {
            console.warn("Failed to fetch group levels:", e);
            return [];
        }
    }
};

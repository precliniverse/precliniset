/**
 * static/js/analysis/plots.js
 * Wrapper for Plotly rendering
 */

const Plots = {
    render: function (elementId, graphData) {
        if (!graphData) return;

        try {
            const data = typeof graphData === 'string' ? JSON.parse(graphData) : graphData;
            Plotly.newPlot(elementId, data.data, data.layout, { responsive: true });
        } catch (e) {
            console.error("Plotting Error:", e);
            document.getElementById(elementId).innerHTML = `<div class="alert alert-danger p-2">Failed to render plot: ${e.message}</div>`;
        }
    },

    // Specific renderer for Survival (if different)
    renderSurvival: function (elementId, graphData) {
        // Survival plots might have specific layout needs (steps), but Plotly JSON handles it.
        this.render(elementId, graphData);
    }
};

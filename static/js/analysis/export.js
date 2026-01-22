/**
 * static/js/analysis/export.js
 * Optimized PDF export using native browser print capabilities.
 * This ensures vector quality and perfect alignment.
 */

const Export = {
    init: function () {
        const btn = document.getElementById('btn-export-pdf');
        if (btn) {
            btn.addEventListener('click', () => this.triggerPrint());
        }
    },

    triggerPrint: async function () {
        const element = document.getElementById('show-results-stage');
        if (!element) return;

        // --- 1. Preparation: Expand all accordions ---
        const accordions = element.querySelectorAll('.accordion-collapse');
        const originalStates = [];

        accordions.forEach(acc => {
            originalStates.push({
                element: acc,
                wasOpen: acc.classList.contains('show')
            });
            if (!acc.classList.contains('show')) {
                acc.classList.add('show');
            }
        });

        // Small delay to ensure Plotly charts resize to their full containers
        // before the print dialog captures the page.
        const plotlyDivs = element.querySelectorAll('.plotly-graph-div');
        plotlyDivs.forEach(div => {
            if (window.Plotly) Plotly.Plots.resize(div);
        });

        // Wait for DOM stability
        setTimeout(() => {
            // --- 2. Trigger Native Print ---
            window.print();

            // --- 3. Cleanup: Restore original accordion states ---
            originalStates.forEach(state => {
                if (!state.wasOpen) {
                    state.element.classList.remove('show');
                }
            });

            // Re-resize Plotly for the screen view
            plotlyDivs.forEach(div => {
                if (window.Plotly) Plotly.Plots.resize(div);
            });
        }, 500);
    }
};

document.addEventListener('DOMContentLoaded', () => {
    Export.init();
});

/**
 * static/js/analysis/main.js
 * Entry Point
 */

document.addEventListener('DOMContentLoaded', function () {
    UI.init();

    // --- Event Handlers ---

    // Propose Workflow Button
    const btnPropose = document.getElementById('btn-propose-workflow');
    if (btnPropose) {
        btnPropose.addEventListener('click', function () {
            // Validation
            const numSelected = document.querySelectorAll('.numerical-param-checkbox:checked').length;
            const survivalChecked = document.getElementById('enable_survival')?.checked;

            if (numSelected === 0 && !survivalChecked) {
                alert("Please select at least one parameter to analyze OR enable Survival analysis.");
                return;
            }

            // Show Loading
            // Submit Form via API (or form submit?)
            // The original app used form submit. Let's stick to standard submit for the transition to Stage 2 (Propose)
            // But wait, the original `analysis_view.js` used AJAX/Celery for execution, but standard POST for stage transition?
            // Actually `routes_analysis.py` renders template.
            // Let's just submit the form.
            document.getElementById('analysis-form').submit();
        });
    }

    // Edit Parameters Button
    document.getElementById('btn-edit-parameters-results')?.addEventListener('click', () => {
        // Show Stage 1, Hide Results
        document.getElementById('initial-selection-stage').style.display = 'block';
        document.getElementById('show-results-stage').style.display = 'none';
        window.scrollTo(0, 0);
    });

    // Re-Run Button
    document.getElementById('btn-reanalyze-this-table')?.addEventListener('click', () => {
        // Reload page clean
        window.location.reload();
    });

    // --- Render Plots if Results are present ---
    // Plots are now rendered via inline scripts in the accordion/results partials
    // to properly handle the data injection from Jinja.
    if (CONFIG.analysisStage === 'show_results') {
        console.log("Analysis results displayed. Graphs rendered via inline fragments.");
    }
});

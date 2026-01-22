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
    // Plots are embedded in the accordion. Check for divs starting with 'plotlyChart-'
    if (CONFIG.analysisStage === 'show_results') {
        const graphs = document.querySelectorAll('.plotly-graph-div');
        graphs.forEach(div => {
            // We need the data. In the monolithic design, data was injected via JS block per item.
            // But in my partial `_results_accordion.html`, I didn't inject the JSON into a global var.
            // I need to find the data. 
            // BETTER APPROACH: The `_results_accordion.html` should probably render a <script> block next to the div
            // calling `Plots.render(...)`.
            // HOWEVER, executing scripts in partials is efficient.
            // Let's adhere to the pattern: The data is in the template.
            // I will instruct the template to output a script tag.
            // See `_results_accordion.html` update in next step? 
            // Or, I can parse it from a data attribute.
        });

        // Wait! The `_results_accordion.html` generated in Step 95 creates the div. 
        // It does NOT inject the script to render it. I missed that.
        // I need to update `_results_accordion.html` to include the script block.
    }
});

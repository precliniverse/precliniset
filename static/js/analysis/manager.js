/**
 * static/js/analysis/manager.js
 * Alpine.js Component for Analysis State Management
 */

document.addEventListener('alpine:init', () => {
    Alpine.data('analysisManager', () => ({
        // --- State ---
        currentStage: (window.CONFIG && window.CONFIG.analysisStage) ? window.CONFIG.analysisStage : 'initial_selection', // No flash!

        // Data populated from DOM (server-side injection)
        allGroupingParams: [],
        allSelectableParams: [], // Array of objects {name: '...', type: 'numerical'|'categorical'}

        // Selections
        selectedGroupings: [],
        selectedNumericals: [],
        groupingSelectedCount: 0,

        // Advanced Options
        excludeOutliers: false,
        outlierMethod: 'iqr',
        isRepeatedMeasures: false,
        showRepeatedMeasures: false, // UI helper

        // --- Lifecycle ---
        init() {
            // 1. Load Config from DOM
            const configEl = document.getElementById('analysis-config');
            if (configEl) {
                const formData = JSON.parse(configEl.dataset.formData || '{}');
                const numericalCols = JSON.parse(configEl.dataset.numericalColumns || '[]');
                const categoricalCols = JSON.parse(configEl.dataset.categoricalColumns || '[]');

                // Build allSelectableParams
                this.allSelectableParams = [
                    ...numericalCols.map(c => ({ name: c, type: 'numerical' })),
                    ...categoricalCols.map(c => ({ name: c, type: 'categorical' }))
                ];

                // Build allGroupingParams (both numerical and categorical can be grouping)
                this.allGroupingParams = [...numericalCols, ...categoricalCols].sort();

                // Restore State from FormData (if returning from Step 2 or Results)
                this.currentStage = formData.analysis_stage || 'initial_selection';

                // Restore Selections
                this.selectedGroupings = formData.grouping_params || [];
                this.selectedNumericals = formData.numerical_params || [];

                // Restore Advanced Options
                this.excludeOutliers = formData.exclude_outliers === true || formData.exclude_outliers === 'true';
                this.outlierMethod = formData.outlier_method || 'iqr';
                this.isRepeatedMeasures = formData.is_repeated_measures === true || formData.is_repeated_measures === 'true';

                // Trigger initial side effects
                this.updateGroupingCount();
                this.checkRepeatedMeasures();

                // If we have existing selections, we might need to populate dynamic dropdowns
                if (this.selectedGroupings.length > 0) {
                    this.$nextTick(() => {
                        this.updateControlGroupOptions();
                        this.initSplittingOptions(formData.splitting_param, formData.random_effect_param);
                    });
                } else {
                    this.initSplittingOptions(formData.splitting_param, formData.random_effect_param);
                }
            }

            console.log("Analysis Manager Initialized", this.currentStage);
        },

        // --- Actions ---

        // Grouping Toggles
        isGroupingSelected(param) {
            return this.selectedGroupings.includes(param);
        },

        toggleGrouping(param) {
            if (this.selectedGroupings.includes(param)) {
                this.selectedGroupings = this.selectedGroupings.filter(p => p !== param);
            } else {
                this.selectedGroupings.push(param);
            }
            this.updateGroupingCount();
            this.updateControlGroupOptions();
        },

        updateGroupingCount() {
            this.groupingSelectedCount = this.selectedGroupings.length;
        },

        // Numerical Toggles
        isNumericalSelected(param) {
            return this.selectedNumericals.includes(param);
        },

        toggleNumerical(param) {
            if (this.selectedNumericals.includes(param)) {
                this.selectedNumericals = this.selectedNumericals.filter(p => p !== param);
            } else {
                this.selectedNumericals.push(param);
            }
            this.checkRepeatedMeasures();
        },

        selectAllNumerical() {
            this.selectedNumericals = this.allSelectableParams.map(p => p.name);
            this.checkRepeatedMeasures();
        },

        clearAllNumerical() {
            this.selectedNumericals = [];
            this.checkRepeatedMeasures();
        },

        // Logic Helpers
        checkRepeatedMeasures() {
            // Heuristic: multiple parameters often implies repeated measures if they are timepoints
            // But user must explicitly confirm. We just show a badge.
            this.showRepeatedMeasures = this.selectedNumericals.length > 1;
        },

        // --- API & Dropdowns ---

        updateControlGroupOptions() {
            const controlSelect = document.getElementById('control_group_param');
            if (!controlSelect) return;

            // Save current selection if possible
            const currentVal = controlSelect.value || (document.getElementById('analysis-config').dataset.formData ? JSON.parse(document.getElementById('analysis-config').dataset.formData).control_group_param : '');

            if (this.selectedGroupings.length === 0) {
                controlSelect.innerHTML = '<option value="">-- None / Auto --</option>';
                return;
            }

            // Use global API object (assumed loaded via api.js)
            if (typeof API !== 'undefined' && API.fetchGroupLevels) {
                controlSelect.innerHTML = '<option value="">Loading...</option>';

                API.fetchGroupLevels(this.selectedGroupings).then(levels => {
                    controlSelect.innerHTML = '<option value="">-- None / Auto --</option>';
                    levels.forEach(lvl => {
                        const isSel = lvl === currentVal;
                        controlSelect.appendChild(new Option(lvl, lvl, isSel, isSel));
                    });
                }).catch(err => {
                    controlSelect.innerHTML = `<option value="">Error loading groups: ${err.message || 'Unknown error'}</option>`;
                    console.error("Control Group Fetch Error:", err);
                });
            } else {
                console.error("API module not found.");
            }
        },

        initSplittingOptions(savedSplit, savedRandom) {
            // Splitting and Random Effect use all categorical columns (plus numericals if discrete? usually just categorical)
            // Just use allSelectableParams where type is categorical? or allGroupingParams?
            // ui_interactions used categoricalColumns.

            const categoricalCols = this.allSelectableParams.filter(p => p.type === 'categorical').map(p => p.name);

            const splittingSelect = document.getElementById('splitting_param');
            const randomSelect = document.getElementById('random_effect_param');
            const covariateSelect = document.getElementById('covariate_param');

            // Helper
            const populate = (select, opts, current) => {
                if (!select) return;
                // Keep first option (placeholder)
                const first = select.options[0];
                select.innerHTML = '';
                select.appendChild(first);

                opts.forEach(opt => {
                    const isSel = opt === current;
                    select.appendChild(new Option(opt, opt, isSel, isSel));
                });
            };

            populate(splittingSelect, categoricalCols, savedSplit);
            populate(randomSelect, categoricalCols, savedRandom);

            // Covariate is usually numerical (or categorical with levels).
            // Let's use allSelectableParams names for broad compatibility
            const allNames = this.allSelectableParams.map(p => p.name).sort();
            const savedCov = JSON.parse(document.getElementById('analysis-config').dataset.formData || '{}').covariate_param;
            populate(covariateSelect, allNames, savedCov);
        },

        // --- Navigation ---

        submitForm() {
            // Set Hidden Input for Stage
            const stageInput = document.getElementById('analysis_stage');
            if (stageInput) stageInput.value = 'propose_workflow'; // Move to next stage

            // Native Form Submit
            document.getElementById('analysis-form').submit();
        },

        submitAnalysis() {
            // Confirm Stage 2 -> 3
            // Alpine for Stage 2 is minimal, mainly display.
            // We set hidden input to execute_analysis
            const stageInput = document.getElementById('analysis_stage');
            if (stageInput) stageInput.value = 'execute_analysis';

            document.getElementById('analysis-form').submit();
        },

        goToStep1() {
            // Switch back to step 1 — Alpine x-show directives handle visibility automatically
            this.currentStage = 'initial_selection';

            // The results stage div is not controlled by Alpine x-show, hide it manually
            const resultsStage = document.getElementById('show-results-stage');
            if (resultsStage) resultsStage.style.display = 'none';

            // Update the hidden stage input so next submit goes to step 2
            const stageInput = document.getElementById('analysis_stage');
            if (stageInput) stageInput.value = 'initial_selection';

            // Scroll to top of form
            const form = document.getElementById('analysis-form');
            if (form) form.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }));
});

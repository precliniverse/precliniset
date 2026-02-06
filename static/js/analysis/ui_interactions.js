/**
 * static/js/analysis/ui_interactions.js
 * Handles Form UI, Checkbox Grids, and Advanced Option Toggles
 */

const UI = {
    init: function () {
        this.initGroupingCheckboxes();
        this.initNumericalCheckboxes();
        this.initAdvancedOptions();
        this.initReferenceRangeSelect();
        this.initTooltips();
        this.initPopovers();
    },

    initPopovers: function () {
        var popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'))
        var popoverList = popoverTriggerList.map(function (popoverTriggerEl) {
            return new bootstrap.Popover(popoverTriggerEl)
        })
    },

    initReferenceRangeSelect: function () {
        const refSelect = document.getElementById('reference_range_id');
        if (!refSelect) return;

        if (!CONFIG.urls.availableRanges) {
            refSelect.options[0].text = "-- URL Error --";
            return;
        }

        const originalText = refSelect.options[0].text;
        refSelect.options[0].text = "-- Loading... --";

        fetch(CONFIG.urls.availableRanges)
            .then(res => {
                if (!res.ok) throw new Error("HTTP " + res.status);
                return res.json();
            })
            .then(data => {
                const currentVal = CONFIG.formData.reference_range_id;

                // Clear except first
                while (refSelect.options.length > 1) {
                    refSelect.remove(1);
                }

                if (data.length === 0) {
                    refSelect.options[0].text = "-- No Ranges Found --";
                } else {
                    refSelect.options[0].text = originalText;
                    data.forEach(range => {
                        const isSelected = String(range.id) === String(currentVal);
                        refSelect.appendChild(new Option(range.name, range.id, isSelected, isSelected));
                    });
                }
            })
            .catch(err => {
                console.error("Error fetching reference ranges:", err);
                refSelect.options[0].text = "-- Error: " + err.message + " --";
            });
    },

    initTooltips: function () {
        var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
        var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl)
        })
    },

    // --- Grouping Parameters (New Grid) ---
    initGroupingCheckboxes: function () {
        const container = document.getElementById('grouping-params-checkboxes');
        const hiddenSelect = document.getElementById('grouping_params');
        const countSpan = document.getElementById('grouping-selected-count');
        const controlGroupSelect = document.getElementById('control_group_param');

        if (!container || !hiddenSelect) return;

        container.innerHTML = '';
        const currentSelected = CONFIG.formData.grouping_params || [];

        CONFIG.categoricalColumns.forEach((param, index) => {
            const isSelected = currentSelected.includes(param);

            // Add to hidden select
            hiddenSelect.appendChild(new Option(param, param, isSelected, isSelected));

            // Create Checkbox UI
            const colDiv = document.createElement('div');
            colDiv.className = 'col';

            const checkDiv = document.createElement('div');
            checkDiv.className = 'form-check d-flex align-items-center p-2 border rounded h-100 position-relative transition-all';
            checkDiv.style.cursor = 'pointer';

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'form-check-input grouping-param-checkbox me-2';
            checkbox.id = `grpParam_${index}`;
            checkbox.value = param;
            checkbox.checked = isSelected;

            const label = document.createElement('label');
            label.className = 'form-check-label small text-break cursor-pointer stretched-link';
            label.htmlFor = `grpParam_${index}`;
            label.textContent = param;

            checkDiv.appendChild(checkbox);
            checkDiv.appendChild(label);
            colDiv.appendChild(checkDiv);
            container.appendChild(colDiv);

            // Update Visuals
            const updateVisuals = () => {
                if (checkbox.checked) {
                    checkDiv.classList.remove('bg-white');
                    checkDiv.classList.add('bg-primary', 'bg-opacity-10', 'border-primary');
                } else {
                    checkDiv.classList.add('bg-white');
                    checkDiv.classList.remove('bg-primary', 'bg-opacity-10', 'border-primary');
                }
            };
            updateVisuals();

            // Event Listener
            checkbox.addEventListener('change', () => {
                updateVisuals();

                // Sync Hidden Select
                Array.from(hiddenSelect.options).forEach(opt => {
                    if (opt.value === param) opt.selected = checkbox.checked;
                });

                // Update Count
                const count = document.querySelectorAll('.grouping-param-checkbox:checked').length;
                countSpan.textContent = `${count} selected`;

                // Trigger update for Control Group Options
                this.updateControlGroupOptions();
            });
        });

        // Initial update
        const count = document.querySelectorAll('.grouping-param-checkbox:checked').length;
        countSpan.textContent = `${count} selected`;
        this.updateControlGroupOptions(); // Populate control group initially
        this.updateSplittingOptions(); // Populate splitting options
    },

    // --- Splitting Parameter Logic ---
    updateSplittingOptions: function () {
        const splittingSelect = document.getElementById('splitting_param');
        if (!splittingSelect) return;

        // Save current selection
        const currentVal = CONFIG.formData.splitting_param;

        // Clear (keep first "No split" option)
        splittingSelect.innerHTML = '<option value="">' + (splittingSelect.options[0]?.text || "Do not split analysis") + '</option>';

        // Populate with all categorical columns (or just selected grouping params? Usually any categorical)
        // User asked "split by" dropdown is not populated. 
        // Usually splitting is done by ANY categorical column.
        CONFIG.categoricalColumns.forEach(col => {
            const isSel = col === currentVal;
            splittingSelect.appendChild(new Option(col, col, isSel, isSel));
        });
    },

    // --- Control Group Logic ---
    updateControlGroupOptions: function () {
        const controlSelect = document.getElementById('control_group_param');
        if (!controlSelect) return;

        const selectedGroups = Array.from(document.querySelectorAll('.grouping-param-checkbox:checked')).map(cb => cb.value);
        const currentVal = CONFIG.formData.control_group_param || controlSelect.value;

        controlSelect.innerHTML = '<option value="">-- None / Auto --</option>';

        if (selectedGroups.length === 0) return;


        if (selectedGroups.length > 0) {
            API.fetchGroupLevels(selectedGroups).then(levels => {
                controlSelect.innerHTML = '<option value="">-- None / Auto --</option>';
                levels.forEach(lvl => {
                    const isSel = lvl === currentVal;
                    controlSelect.appendChild(new Option(lvl, lvl, isSel, isSel));
                });
            });
        }
    },

    // --- Numerical Parameters (Analyte Checkbox Grid) ---
    // NOW INCLUDES CATEGORICAL for categorical analysis support
    initNumericalCheckboxes: function () {
        const container = document.getElementById('numerical-params-checkboxes');
        const hiddenSelect = document.getElementById('numerical_params');

        if (!container || !hiddenSelect) return;

        container.innerHTML = '';
        const currentSelected = CONFIG.formData.numerical_params || [];

        // Combine numerical and categorical columns for unified selection
        // Numerical columns come first, then categorical
        const allSelectableParams = [
            ...CONFIG.numericalColumns.map(col => ({name: col, type: 'numerical'})),
            ...CONFIG.categoricalColumns.map(col => ({name: col, type: 'categorical'}))
        ];

        allSelectableParams.forEach((paramObj, index) => {
            const param = paramObj.name;
            const paramType = paramObj.type;
            const isSelected = currentSelected.includes(param);

            // Add to hidden select
            hiddenSelect.appendChild(new Option(param, param, isSelected, isSelected));

            // Create Checkbox
            const colDiv = document.createElement('div');
            colDiv.className = 'col';

            const checkDiv = document.createElement('div');
            checkDiv.className = 'form-check d-flex align-items-center p-2 border rounded h-100 position-relative transition-all';
            checkDiv.style.cursor = 'pointer';

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'form-check-input numerical-param-checkbox me-2';
            checkbox.id = `numParam_${index}`;
            checkbox.value = param;
            checkbox.checked = isSelected;
            checkbox.dataset.paramType = paramType;  // Store type for later use

            // Add icon based on type
            const icon = document.createElement('span');
            icon.className = 'me-1';
            icon.style.fontSize = '0.9em';
            if (paramType === 'numerical') {
                icon.textContent = '📊';  // Chart icon for numerical
                icon.title = 'Numerical variable';
            } else {
                icon.textContent = '🔤';  // Text icon for categorical
                icon.title = 'Categorical variable';
            }

            const label = document.createElement('label');
            label.className = 'form-check-label small text-break cursor-pointer stretched-link';
            label.htmlFor = `numParam_${index}`;
            label.textContent = param;
            label.title = param;

            // Truncate visually if VERY long (though text-break helps)
            if (param.length > 25) {
                label.textContent = param.substring(0, 23) + '...';
            }

            checkDiv.appendChild(checkbox);
            checkDiv.appendChild(icon);
            checkDiv.appendChild(label);
            colDiv.appendChild(checkDiv);
            container.appendChild(colDiv);

            // Update Visuals
            const updateVisuals = () => {
                if (checkbox.checked) {
                    checkDiv.classList.remove('bg-white');
                    checkDiv.classList.add('bg-primary', 'bg-opacity-10', 'border-primary');
                } else {
                    checkDiv.classList.add('bg-white');
                    checkDiv.classList.remove('bg-primary', 'bg-opacity-10', 'border-primary');
                }
            };
            updateVisuals();

            checkbox.addEventListener('change', () => {
                updateVisuals();
                Array.from(hiddenSelect.options).forEach(opt => {
                    if (opt.value === param) opt.selected = checkbox.checked;
                });
            });
        });

        // Select All / Clear All
        document.getElementById('select-all-numerical')?.addEventListener('click', () => {
            document.querySelectorAll('.numerical-param-checkbox').forEach(cb => { cb.checked = true; cb.dispatchEvent(new Event('change')); });
        });
        document.getElementById('deselect-all-numerical')?.addEventListener('click', () => {
            document.querySelectorAll('.numerical-param-checkbox').forEach(cb => { cb.checked = false; cb.dispatchEvent(new Event('change')); });
        });
    },

    // --- Advanced Options ---
    initAdvancedOptions: function () {
        // Survival Toggle
        const survivalCheck = document.getElementById('enable_survival');
        const survivalOptions = document.getElementById('survival-options');
        if (survivalCheck && survivalOptions) {
            survivalCheck.addEventListener('change', () => {
                survivalOptions.style.display = survivalCheck.checked ? 'flex' : 'none';
            });
            // Initial state
            survivalOptions.style.display = survivalCheck.checked ? 'flex' : 'none';
        }

        // Repeated Measures Highlight
        const rmCheck = document.getElementById('is_repeated_measures');
        const rmContainer = document.getElementById('repeated-measures-container');
        if (rmCheck && rmContainer) {
            const updateRmVisuals = () => {
                if (rmCheck.checked) {
                    rmContainer.classList.remove('bg-white');
                    rmContainer.classList.add('bg-primary', 'bg-opacity-10', 'border-primary');
                } else {
                    rmContainer.classList.add('bg-white');
                    rmContainer.classList.remove('bg-primary', 'bg-opacity-10', 'border-primary');
                }
            };
            // Init and Listen
            updateRmVisuals();
            rmCheck.addEventListener('change', updateRmVisuals);
        }

        // Outlier Method Toggle
        const excludeCheck = document.getElementById('exclude_outliers');
        const methodContainer = document.getElementById('outlier_method_container');
        const methodSelect = document.getElementById('outlier_method');
        const thresholdInput = document.getElementById('outlier_threshold');

        if (excludeCheck && methodContainer) {
            excludeCheck.addEventListener('change', () => {
                methodContainer.style.display = excludeCheck.checked ? 'block' : 'none';
            });
        }
        
        if (methodSelect && thresholdInput) {
             methodSelect.addEventListener('change', () => {
                 // Set reasonable defaults for threshold based on method
                 if (methodSelect.value === 'iqr') thresholdInput.value = 1.5;
                 else if (methodSelect.value === 'std') thresholdInput.value = 3.0;
                 else if (methodSelect.value === 'grubbs') thresholdInput.value = 0.05; // alpha
             });
        }

        // Populate Dropdowns (Covariate, Survival Cols)
        // These are subsets of Numerical or Categorical columns
        const timeSelect = document.getElementById('survival_time_col');
        const statusSelect = document.getElementById('survival_event_col');
        const covariateSelect = document.getElementById('covariate_param');

        // Populate Numerical Options (Time, Covariate)
        if (timeSelect && covariateSelect) {
            CONFIG.numericalColumns.forEach(col => {
                // Survival Time
                let isSel = CONFIG.formData.survival_time_col === col;
                timeSelect.appendChild(new Option(col, col, isSel, isSel));

                // Covariate
                isSel = CONFIG.formData.covariate_param === col;
                covariateSelect.appendChild(new Option(col, col, isSel, isSel));
            });
        }

        // Populate Categorical Options (Status)
        if (statusSelect) {
            // For Status, we might want Categorical OR Numerical (if 0/1). 
            // We'll show both combined for maximum flexibility.
            const allCols = [...CONFIG.categoricalColumns, ...CONFIG.numericalColumns];
            allCols.sort().forEach(col => {
                const isSel = CONFIG.formData.survival_event_col === col;
                statusSelect.appendChild(new Option(col, col, isSel, isSel));
            });
        }
    }
};

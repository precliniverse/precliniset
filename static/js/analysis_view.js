/**
 * app/static/js/analysis_view.js
 * Handles interaction, plotting, and async polling for the Analysis Results page.
 */

document.addEventListener('DOMContentLoaded', function () {
    // 1. Load Configuration
    const configEl = document.getElementById('analysis-config');
    if (!configEl) return;
    const CONFIG = JSON.parse(configEl.textContent);

    // --- Helper: Match Python's ID cleaning logic ---
    function cleanParamName(name) {
        if (!name) return "";
        let cleaned = name.replace(/[^\w-]/g, '-');
        cleaned = cleaned.replace(/-+/g, '-');
        return cleaned.replace(/^-+|-+$/g, '');
    }

    // --- DOM Elements ---
    const analysisForm = document.getElementById('analysis-form');
    const analysisStageInput = document.getElementById('analysis_stage');

    // Select Inputs
    const groupingSelect = $('#grouping_params');
    const numericalSelect = $('#numerical_params');
    const splittingSelect = $('#splitting_param');
    const refRangeSelect = $('#reference_range_id');

    // Containers/Buttons
    const numericalParamsError = document.getElementById('numerical-params-error');
    const repeatedMeasuresContainer = $('#repeated-measures-container');
    const isRepeatedCheckbox = $('#is_repeated_measures');
    const selectAllNumericalBtn = document.getElementById('select-all-numerical');
    const executeBtn = document.getElementById('btn-execute-analysis');

    // --- 1. Initialize Select2 Inputs (for grouping and splitting, not numerical) ---
    function initSelect2(element, data, selected, placeholder, allowClear = false) {
        if (!element.length) return;
        element.empty();
        if (allowClear && placeholder) {
            element.append(new Option(placeholder, "", false, false));
        }
        data.forEach(item => {
            const isSelected = Array.isArray(selected) ? selected.includes(item) : (selected === item);
            element.append(new Option(item, item, isSelected, isSelected));
        });
        element.select2({
            theme: "bootstrap-5",
            placeholder: placeholder,
            allowClear: allowClear,
            width: '100%'
        });
    }

    initSelect2(groupingSelect, CONFIG.categoricalColumns, CONFIG.formData.grouping_params, CONFIG.i18n.selectGrouping, true);
    initSelect2(splittingSelect, CONFIG.categoricalColumns, CONFIG.formData.splitting_param, CONFIG.i18n.noSplit, true);

    // --- 1b. Initialize Numerical Parameters as Checkbox Grid ---
    function initNumericalCheckboxes() {
        const container = document.getElementById('numerical-params-checkboxes');
        const hiddenSelect = document.getElementById('numerical_params');
        const countSpan = document.getElementById('numerical-selected-count');

        if (!container || !hiddenSelect) return;

        container.innerHTML = '';

        // Populate hidden select and checkboxes
        CONFIG.numericalColumns.forEach((param, index) => {
            const isSelected = CONFIG.formData.numerical_params.includes(param);

            // Add to hidden select
            const option = new Option(param, param, isSelected, isSelected);
            hiddenSelect.appendChild(option);

            // Create checkbox
            const colDiv = document.createElement('div');
            colDiv.className = 'col';

            const checkDiv = document.createElement('div');
            checkDiv.className = 'form-check';

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'form-check-input numerical-param-checkbox';
            checkbox.id = `numParam_${index}`;
            checkbox.value = param;
            checkbox.checked = isSelected;

            const label = document.createElement('label');
            label.className = 'form-check-label small';
            label.htmlFor = `numParam_${index}`;
            label.textContent = param;
            label.title = param; // Tooltip for long names

            // Truncate long labels
            if (param.length > 20) {
                label.textContent = param.substring(0, 18) + '...';
            }

            checkDiv.appendChild(checkbox);
            checkDiv.appendChild(label);
            colDiv.appendChild(checkDiv);
            container.appendChild(colDiv);

            // Sync checkbox with hidden select
            checkbox.addEventListener('change', function () {
                syncCheckboxesToSelect();
            });
        });

        updateNumericalCount();
    }

    function syncCheckboxesToSelect() {
        const hiddenSelect = document.getElementById('numerical_params');
        const checkboxes = document.querySelectorAll('.numerical-param-checkbox:checked');
        const selectedValues = Array.from(checkboxes).map(cb => cb.value);

        // Update hidden select
        Array.from(hiddenSelect.options).forEach(opt => {
            opt.selected = selectedValues.includes(opt.value);
        });

        // Trigger change for any listeners (like repeated measures toggle)
        $(hiddenSelect).trigger('change');

        updateNumericalCount();
    }

    function updateNumericalCount() {
        const countSpan = document.getElementById('numerical-selected-count');
        const checkboxes = document.querySelectorAll('.numerical-param-checkbox:checked');
        if (countSpan) {
            countSpan.textContent = checkboxes.length;
        }
    }

    // Initialize the checkboxes
    initNumericalCheckboxes();

    $('.graph-select').select2({ theme: "bootstrap-5", minimumResultsForSearch: Infinity });
    $('.test-select').select2({ theme: "bootstrap-5", width: '100%' });

    // --- 2. UI Interactivity ---
    function toggleRepeatedMeasures() {
        const selected = numericalSelect.val() || [];
        if (selected.length > 1) {
            repeatedMeasuresContainer.slideDown();
        } else {
            repeatedMeasuresContainer.slideUp(() => {
                if (isRepeatedCheckbox.is(':checked')) {
                    isRepeatedCheckbox.prop('checked', false).trigger('change');
                }
            });
        }
    }
    numericalSelect.on('change', toggleRepeatedMeasures);
    toggleRepeatedMeasures();

    // Select All button
    if (selectAllNumericalBtn) {
        selectAllNumericalBtn.addEventListener('click', function () {
            document.querySelectorAll('.numerical-param-checkbox').forEach(cb => {
                cb.checked = true;
            });
            syncCheckboxesToSelect();
        });
    }

    // Deselect All button
    const deselectAllBtn = document.getElementById('deselect-all-numerical');
    if (deselectAllBtn) {
        deselectAllBtn.addEventListener('click', function () {
            document.querySelectorAll('.numerical-param-checkbox').forEach(cb => {
                cb.checked = false;
            });
            syncCheckboxesToSelect();
        });
    }

    // --- 3. Form Submission & Async Polling ---

    window.handleStageSubmit = function (nextStage) {
        if (!analysisForm) return;

        if (nextStage === 'propose_workflow') {
            const selectedNum = numericalSelect.val() || [];
            if (selectedNum.length === 0) {
                if (numericalParamsError) numericalParamsError.style.display = 'block';
                numericalSelect.next('.select2-container').find('.select2-selection').addClass('border-danger');
                return;
            } else {
                if (numericalParamsError) numericalParamsError.style.display = 'none';
                numericalSelect.next('.select2-container').find('.select2-selection').removeClass('border-danger');
            }
        }

        analysisStageInput.value = nextStage;

        // Ensure reference range ID is passed
        const refId = refRangeSelect.val();
        let refInput = analysisForm.querySelector('input[name="reference_range_id"]');
        if (!refInput) {
            refInput = document.createElement('input');
            refInput.type = 'hidden';
            refInput.name = 'reference_range_id';
            analysisForm.appendChild(refInput);
        }
        refInput.value = refId;

        // ASYNC HANDLING for Execution
        if (nextStage === 'execute_analysis') {
            startAsyncAnalysis();
        } else {
            // Standard submit for other stages
            document.querySelectorAll('.btn').forEach(b => b.classList.add('disabled'));
            analysisForm.submit();
        }
    };

    function startAsyncAnalysis() {
        if (executeBtn) {
            executeBtn.disabled = true;
            executeBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> ' + CONFIG.i18n.analyzing;
        }

        const formData = new FormData(analysisForm);
        formData.append('is_async', 'true'); // Explicitly signal async request

        fetch(analysisForm.action, {
            method: 'POST',
            body: formData,
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'submitted') {
                    pollTaskStatus(data.task_id);
                } else {
                    alert("Error starting analysis: " + (data.error || "Unknown error"));
                    resetExecuteBtn();
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert("Network error starting analysis.");
                resetExecuteBtn();
            });
    }

    function pollTaskStatus(taskId) {
        const pollInterval = setInterval(() => {
            fetch(`/datatables/analysis/status/${taskId}`)
                .then(response => response.json())
                .then(data => {
                    if (data.state === 'SUCCESS') {
                        clearInterval(pollInterval);
                        // Redirect to clean GET request to show results
                        // Using window.location.href with the same base URL ensures a GET request
                        // which will pick up the session-stored results
                        const baseUrl = window.location.pathname;
                        window.location.href = baseUrl;
                    } else if (data.state === 'FAILURE') {
                        clearInterval(pollInterval);
                        alert("Analysis Failed: " + data.status);
                        resetExecuteBtn();
                    } else {
                        // Still pending...
                        if (executeBtn) executeBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> ' + CONFIG.i18n.analyzing + '...';
                    }
                })
                .catch(error => {
                    clearInterval(pollInterval);
                    console.error('Polling Error:', error);
                    alert("Error checking analysis status.");
                    resetExecuteBtn();
                });
        }, 2000);
    }

    function resetExecuteBtn() {
        if (executeBtn) {
            executeBtn.disabled = false;
            executeBtn.innerHTML = CONFIG.i18n.execute; // You might need to pass this string in config
        }
    }

    // Wire up buttons
    document.getElementById('btn-propose-workflow')?.addEventListener('click', () => handleStageSubmit('propose_workflow'));
    document.getElementById('btn-back-to-initial-selection')?.addEventListener('click', () => handleStageSubmit('initial_selection'));
    document.getElementById('btn-execute-analysis')?.addEventListener('click', () => handleStageSubmit('execute_analysis'));
    document.getElementById('btn-edit-parameters-results')?.addEventListener('click', () => handleStageSubmit('initial_selection'));
    document.getElementById('btn-reanalyze-this-table')?.addEventListener('click', function () { window.location.href = this.dataset.url; });
    document.getElementById('btn-start-new-analysis')?.addEventListener('click', function () { window.location.href = this.dataset.url; });


    // --- 4. Plotly Chart Rendering ---
    if (CONFIG.analysisStage === 'show_results' && CONFIG.analysisResults) {
        const results = CONFIG.analysisResults;

        document.querySelectorAll('.plotly-graph-div').forEach(div => {
            const divId = div.id;
            let graphData = null;

            if (results.results_by_split && Object.keys(results.results_by_split).length > 0) {
                for (const [splitVal, splitData] of Object.entries(results.results_by_split)) {
                    const cleanSplit = cleanParamName(splitVal);
                    if (divId.includes(cleanSplit)) {
                        for (const [paramKey, paramData] of Object.entries(splitData.results_by_parameter)) {
                            const cleanParam = cleanParamName(paramKey);
                            const expectedId = `plotlyChart-${cleanSplit}-${cleanParam}`;
                            if (divId === expectedId) {
                                graphData = paramData.graph_data;
                                break;
                            }
                        }
                    }
                    if (graphData) break;
                }
            } else if (results.results_by_parameter) {
                for (const [paramKey, paramData] of Object.entries(results.results_by_parameter)) {
                    const cleanParam = cleanParamName(paramKey);
                    const expectedId = `plotlyChart-${cleanParam}`;
                    if (divId === expectedId) {
                        graphData = paramData.graph_data;
                        break;
                    }
                }
            }

            if (graphData) {
                try {
                    const plotData = typeof graphData === 'string' ? JSON.parse(graphData) : graphData;
                    Plotly.newPlot(div, plotData.data, plotData.layout, { responsive: true });
                } catch (e) {
                    console.error("Plotly Render Error:", e);
                    div.innerHTML = `<div class="alert alert-danger small">Error rendering graph: ${e.message}</div>`;
                }
            } else {
                div.innerHTML = `<div class="text-muted small p-3 text-center">No graph data available.</div>`;
            }
        });
    }

    // --- 5. Reference Range Modal Logic ---
    const refRangeModal = document.getElementById('referenceRangeModal');
    if (refRangeModal && CONFIG.urls.availableRanges) {
        const refFetchBtn = document.getElementById('fetchReferenceDataBtn');
        const refLoading = document.getElementById('ref-loading-spinner');
        const refIgnoreAge = document.getElementById('refIgnoreAge');
        const refAgeTolerance = document.getElementById('refAgeTolerance');
        let availableRangesCache = [];

        $('#refRangeSelect').select2({
            theme: "bootstrap-5",
            dropdownParent: $('#referenceRangeModal'),
            placeholder: CONFIG.i18n.selectRange,
            width: '100%'
        });

        refRangeModal.addEventListener('show.bs.modal', function () {
            fetch(CONFIG.urls.availableRanges)
                .then(r => r.json())
                .then(data => {
                    availableRangesCache = data;
                    const select = $('#refRangeSelect');
                    select.empty().append(new Option(CONFIG.i18n.selectRange, ""));
                    data.forEach(r => {
                        select.append(new Option(r.name, r.id));
                    });
                });
        });

        refIgnoreAge.addEventListener('change', function () {
            refAgeTolerance.disabled = this.checked;
        });

        refFetchBtn.addEventListener('click', function () {
            const rangeId = $('#refRangeSelect').val();
            if (!rangeId) {
                alert(CONFIG.i18n.selectRange);
                return;
            }

            const selectedRange = availableRangesCache.find(r => r.id == rangeId);
            const currentAgeRange = CONFIG.analysisResults ? CONFIG.analysisResults.age_range : null;

            if (selectedRange && selectedRange.min_age && currentAgeRange && !refIgnoreAge.checked) {
                const currentMinAge = parseInt(currentAgeRange.split(/[-\s]/)[0]);
                if (!isNaN(currentMinAge)) {
                    if (currentMinAge < selectedRange.min_age || (selectedRange.max_age && currentMinAge > selectedRange.max_age)) {
                        if (!confirm(CONFIG.i18n.ageWarning)) return;
                    }
                }
            }

            refLoading.style.display = 'block';
            refFetchBtn.disabled = true;

            const payload = {
                reference_range_id: parseInt(rangeId),
                age_tolerance_days: refIgnoreAge.checked ? null : parseInt(refAgeTolerance.value)
            };

            fetch(CONFIG.urls.calculateRange, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CONFIG.csrfToken
                },
                body: JSON.stringify(payload)
            })
                .then(r => r.json())
                .then(data => {
                    if (data.error) { alert("Error: " + data.error); return; }
                    updateTableWithRefData(data.stats);
                    bootstrap.Modal.getInstance(refRangeModal).hide();
                })
                .catch(e => { console.error(e); alert("Network error"); })
                .finally(() => {
                    refLoading.style.display = 'none';
                    refFetchBtn.disabled = false;
                });
        });
    }

    function updateTableWithRefData(stats) {
        const table = document.getElementById('mainDataTable');
        if (!table) return;

        const headerRow = table.querySelector('thead tr');
        const bodyRows = table.querySelectorAll('tbody tr:not(.group-separator)');

        headerRow.querySelectorAll('.ref-range-header').forEach(e => e.remove());
        bodyRows.forEach(row => row.querySelectorAll('.ref-range-cell').forEach(e => e.remove()));

        for (const [param, stat] of Object.entries(stats)) {
            let targetIndex = -1;
            Array.from(headerRow.children).forEach((th, idx) => {
                if (th.textContent.trim() === param) targetIndex = idx;
            });

            if (targetIndex > -1) {
                const th = document.createElement('th');
                th.className = 'ref-range-header bg-light text-secondary fst-italic';
                th.innerHTML = `${param}<br><small>(Ref)</small>`;
                headerRow.insertBefore(th, headerRow.children[targetIndex + 1]);

                bodyRows.forEach(row => {
                    const td = document.createElement('td');
                    td.className = 'ref-range-cell text-secondary small';
                    if (stat.std > 0) {
                        const low = (stat.mean - 2 * stat.std).toFixed(2);
                        const high = (stat.mean + 2 * stat.std).toFixed(2);
                        td.textContent = `${low} - ${high}`;
                    } else {
                        td.textContent = 'N/A';
                    }
                    row.insertBefore(td, row.children[targetIndex + 1]);
                });
            }
        }
    }
});
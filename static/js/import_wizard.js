/**
 * import_wizard.js
 * Handles the multi-step import processes.
 */

document.addEventListener('DOMContentLoaded', function () {
    const modal = document.getElementById('importWizardModal');
    if (!modal) return;

    // Configuration from HTML
    const configEl = document.getElementById('datatable-editor-config');
    const config = configEl ? JSON.parse(configEl.textContent) : {};
    const dataTableId = config.dataTableId;
    const protocolId = config.protocolId;
    const groupId = config.groupId;
    const animalData = config.animalData || [];

    // UI Elements
    const importBtn = document.getElementById('btn-import-raw');
    const fileInput = document.getElementById('import-file');
    const templateSelect = document.getElementById('import-template-select');
    const nextBtn = document.getElementById('import-next-btn');
    const prevBtn = document.getElementById('import-prev-btn');
    const finalizeBtn = document.getElementById('import-finalize-btn');
    const mappingTableBody = document.getElementById('mapping-table-body');
    const validationResults = document.getElementById('validation-results');
    const summaryText = document.getElementById('import-summary-text');
    const templateNameInput = document.getElementById('new-template-name');
    const saveTemplateCheck = document.getElementById('save-as-template');
    const templateNameContainer = document.getElementById('template-name-container');
    const exportTemplateBtn = document.getElementById('export-template-btn');
    const importTemplateBtn = document.getElementById('import-template-btn');
    const templateFileInput = document.getElementById('template-file-input');
    const pipelineSelect = document.getElementById('import-pipeline-select');
    const pipelineContainer = document.getElementById('pipeline-selection-container');
    const advancedOptions = document.getElementById('advanced-parse-options');

    let currentStep = 1;
    let fileData = null;
    let analytes = [];
    let templates = [];
    let pipelines = [];

    // Helper to get headers with CSRF
    function getHeaders(contentType = null) {
        const headers = {
            'Authorization': `Bearer ${localStorage.getItem('token')}`
        };
        const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
        if (csrf) headers['X-CSRFToken'] = csrf;
        if (contentType) headers['Content-Type'] = contentType;
        return headers;
    }

    // Initialize: Listen for the modal to be shown
    modal.addEventListener('show.bs.modal', () => {
        resetWizard();
        loadTemplates();
    });

    function resetWizard() {
        currentStep = 1;
        fileData = null;
        fileInput.value = '';
        saveTemplateCheck.checked = false;
        templateNameContainer.classList.add('d-none');
        templateNameInput.value = '';
        goToStep(1);
    }

    // Export Template Handler
    if (exportTemplateBtn) {
        exportTemplateBtn.addEventListener('click', async () => {
            const templateId = templateSelect.value;
            if (!templateId) {
                alert("Please select or save a template first to export it.");
                return;
            }

            try {
                const resp = await fetch(`/api/v1/import_wizard/templates/${templateId}/export`, {
                    headers: getHeaders()
                });
                const blob = await resp.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                const tName = templates.find(t => t.id == templateId)?.name || 'template';
                a.href = url;
                a.download = `${tName.replace(/\s+/g, '_')}.json`;
                document.body.appendChild(a);
                a.click();
                a.remove();
            } catch (e) {
                alert("Export failed: " + e.message);
            }
        });
    }

    // Import Template Handler
    if (importTemplateBtn) {
        importTemplateBtn.addEventListener('click', () => templateFileInput.click());
    }

    if (templateFileInput) {
        templateFileInput.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;

            const reader = new FileReader();
            reader.onload = async (event) => {
                try {
                    const data = JSON.parse(event.target.result);
                    const resp = await fetch(`/api/v1/import_wizard/templates/import/${protocolId}`, {
                        method: 'POST',
                        headers: getHeaders('application/json'),
                        body: JSON.stringify(data)
                    });
                    if (resp.ok) {
                        alert("Template imported successfully!");
                        await loadTemplates();
                        templateFileInput.value = '';
                    } else {
                        throw new Error(await resp.text());
                    }
                } catch (err) {
                    alert("Import failed: " + err.message);
                }
            };
            reader.readAsText(file);
        });
    }

    nextBtn.addEventListener('click', () => {
        if (currentStep === 1) handleStep1();
        else if (currentStep === 2) handleStep2();
        else if (currentStep === 3) handleStep3();
    });

    prevBtn.addEventListener('click', () => {
        goToStep(currentStep - 1);
    });

    saveTemplateCheck.addEventListener('change', function () {
        templateNameContainer.classList.toggle('d-none', !this.checked);
    });

    if (pipelineSelect) {
        pipelineSelect.addEventListener('change', function () {
            const hasPipeline = !!this.value;
            if (advancedOptions) {
                if (hasPipeline) {
                    const collapse = bootstrap.Collapse.getInstance(advancedOptions);
                    if (collapse) collapse.hide();
                    advancedOptions.classList.add('d-none');
                } else {
                    advancedOptions.classList.remove('d-none');
                }
            }
            // Also hide/disable template select if pipeline is used?
            if (templateSelect) {
                templateSelect.parentElement.classList.toggle('d-none', hasPipeline);
            }
        });
    }

    finalizeBtn.addEventListener('click', finalizeImport);

    async function loadTemplates() {
        try {

            const templatesResponse = await fetch(`/api/v1/import_wizard/templates/${protocolId}`, {
                headers: getHeaders()
            });

            if (!templatesResponse.ok) throw new Error(`Failed to fetch templates: ${templatesResponse.statusText}`);
            templates = await templatesResponse.json();
            templateSelect.innerHTML = '<option value="">-- No template / Manual mapping --</option>';
            templates.forEach(t => {
                const opt = document.createElement('option');
                opt.value = t.id;
                opt.textContent = t.name;
                templateSelect.appendChild(opt);
            });

            // Fetch pipelines
            if (pipelineSelect) {
                const pipelinesResponse = await fetch(`/api/v1/import_wizard/pipelines/${protocolId}`, {
                    headers: getHeaders()
                });
                if (pipelinesResponse.ok) {
                    pipelines = await pipelinesResponse.json();
                    pipelineSelect.innerHTML = '<option value="">-- No Pipeline --</option>';
                    pipelines.forEach(p => {
                        const opt = document.createElement('option');
                        opt.value = p.id;
                        opt.textContent = p.name;
                        pipelineSelect.appendChild(opt);
                    });
                    if (pipelines.length > 0) {
                        pipelineContainer.classList.remove('d-none');
                    } else {
                        pipelineContainer.classList.add('d-none');
                    }
                }
            }

            // Fetch datatable details to get protocol and animal model IDs

            const dtResp = await fetch(`/api/v1/groups/datatables/${dataTableId}`, {
                headers: getHeaders()
            });

            if (!dtResp.ok) throw new Error(`Failed to fetch datatable details: ${dtResp.statusText}`);
            const dtData = await dtResp.json();


            const pId = dtData.protocol_id;
            const amId = dtData.group ? dtData.group.model_id : null;


            const analytePromises = [];
            if (pId) {
                const pUrl = `/api/v1/protocols/${pId}`;

                analytePromises.push(
                    fetch(pUrl, { headers: getHeaders() })
                        .then(res => res.ok ? res.json() : Promise.resolve({ analytes: [] }))
                );
            }
            if (amId) {
                const amUrl = `/api/v1/animal_models/${amId}`;

                analytePromises.push(
                    fetch(amUrl, { headers: getHeaders() })
                        .then(res => res.ok ? res.json() : Promise.resolve({ analytes: [] }))
                );
            }

            const results = await Promise.all(analytePromises);


            let combinedAnalytes = [];
            results.forEach(result => {
                if (result && result.analytes) {
                    combinedAnalytes = combinedAnalytes.concat(result.analytes);
                }
            });


            // Remove duplicates based on ID
            const uniqueAnalytes = combinedAnalytes.filter((analyte, index, self) =>
                analyte.id && index === self.findIndex((a) => a.id === analyte.id)
            );

            analytes = uniqueAnalytes;


        } catch (e) {

            alert("Could not load necessary data for the import wizard. Please check the console and refresh. Error: " + e.message);
        }
    }

    async function handleStep1() {
        if (!fileInput.files[0]) {
            alert("Please select a file first.");
            return;
        }

        const skipRows = document.getElementById('import-skip-rows').value || 0;
        const anchorText = document.getElementById('import-anchor-text').value || '';
        const anchorOffset = document.getElementById('import-anchor-offset').value || 0;
        const rowInterval = document.getElementById('import-row-interval').value || 1;
        const pipelineId = pipelineSelect ? pipelineSelect.value : null;

        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        if (pipelineId) {
            formData.append('pipeline_id', pipelineId);
        } else {
            formData.append('skip_rows', skipRows);
            formData.append('anchor_text', anchorText);
            formData.append('anchor_offset', anchorOffset);
            formData.append('row_interval', rowInterval);
        }

        nextBtn.disabled = true;
        nextBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Parsing...';

        try {
            const response = await fetch('/api/v1/import_wizard/parse', {
                method: 'POST',
                headers: getHeaders(),
                body: formData
            });

            if (!response.ok) throw new Error(await response.text());

            fileData = await response.json();
            fileData.skip_rows = skipRows;
            fileData.anchor_text = anchorText;
            fileData.anchor_offset = anchorOffset;
            fileData.row_interval = rowInterval;
            fileData.pipeline_id = pipelineId;

            if (pipelineId) {
                // Pipeline Flow
                if (!fileData.headers.includes('uid')) {
                    alert("Pipeline output validation failed: The script must return a list of rows containing a 'uid' column.");
                    return;
                }

                // Auto-map headers to Analyte IDs
                const autoMapping = {};
                fileData.headers.forEach(header => {
                    // Try exact match first
                    let match = analytes.find(a => a.name === header);
                    if (match) {
                        autoMapping[header] = match.id;
                    }
                });

                fileData.animal_id_column = 'uid';
                fileData.mapping = autoMapping;
                fileData.advanced_logic = {};

                // Trigger Step 3 validation immediately
                handleStep2();
            } else {
                buildMappingTable();
                goToStep(2);
            }
        } catch (e) {
            alert("Error parsing file: " + e.message);
        } finally {
            nextBtn.disabled = false;
            nextBtn.innerHTML = 'Next';
        }
    }

    function buildMappingTable() {
        mappingTableBody.innerHTML = '';

        // Auto-detect template if selected
        const tId = templateSelect.value;
        const template = tId ? templates.find(t => t.id == tId) : null;
        const templateMapping = template ? template.mapping_json : {};
        const templateLogic = template ? (template.advanced_logic || {}) : {};

        // If template selected, update advanced inputs (Step 1 might have been skipped or changed)
        if (template) {
            document.getElementById('import-skip-rows').value = template.skip_rows || 0;
            document.getElementById('import-anchor-text').value = template.anchor_text || '';
            document.getElementById('import-anchor-offset').value = template.anchor_offset || 0;
            document.getElementById('import-row-interval').value = template.row_interval || 1;
        }

        fileData.headers.forEach(header => {
            const row = document.createElement('tr');

            // Header Name
            const tdHeader = document.createElement('td');
            tdHeader.innerHTML = `<strong>${header}</strong>`;
            row.appendChild(tdHeader);

            // Mapping Dropdown
            const tdMap = document.createElement('td');
            const select = document.createElement('select');
            select.className = 'form-select form-select-sm analyte-map-select';
            select.dataset.column = header;

            // Add options: None, Animal ID, and all Analytes
            select.innerHTML = `<option value="">-- Ignore --</option>`;

            analytes.forEach(a => {
                const opt = document.createElement('option');
                opt.value = a.id;
                opt.textContent = a.name;

                // Auto-select 'ID' if header contains 'id'
                // Auto-select 'uid' if header contains 'id' or 'uid'
                if (a.name === 'uid' && (header.toLowerCase().includes('id') || header.toLowerCase().includes('uid'))) {
                    opt.selected = true;
                }

                // Auto-match by name from template or header
                if (templateMapping[header] == a.id || header.toLowerCase() === a.name.toLowerCase()) {
                    opt.selected = true;
                }
                select.appendChild(opt);
            });

            tdMap.appendChild(select);

            // Advanced Logic Input (Formula)
            const logicDiv = document.createElement('div');
            logicDiv.className = 'mt-1 advanced-logic-container d-none';
            const analyteId = select.value;
            const formula = templateLogic[analyteId] || '';

            logicDiv.innerHTML = `
                <div class="input-group input-group-sm">
                    <span class="input-group-text">f(x)=</span>
                    <input type="text" class="form-control advanced-logic-input" placeholder="e.g. x * 1000" value="${formula}">
                </div>
            `;
            tdMap.appendChild(logicDiv);

            // Toggle logic visibility based on selection
            select.addEventListener('change', () => {
                const isAnalyte = select.value && select.value !== 'ANIMAL_ID';
                logicDiv.classList.toggle('d-none', !isAnalyte);
            });
            if (select.value && select.value !== 'ANIMAL_ID') logicDiv.classList.remove('d-none');

            row.appendChild(tdMap);

            // Preview
            const tdPreview = document.createElement('td');
            tdPreview.className = 'small text-muted';
            tdPreview.textContent = fileData.preview.map(r => r[header]).join(', ');
            row.appendChild(tdPreview);

            mappingTableBody.appendChild(row);
        });
    }

    async function handleStep2() {
        // Collect mapping and logic
        let mapping = {};
        let advancedLogic = {};
        let animalIdCol = null;

        if (fileData.pipeline_id) {
            // Pipeline already populated this in Step 1
            mapping = fileData.mapping;
            advancedLogic = fileData.advanced_logic;
            animalIdCol = fileData.animal_id_column;
        } else {
            // Manual Parsing: Scrape the UI
            const idAnalyte = analytes.find(a => a.name === 'uid');
            const idAnalyteId = idAnalyte ? idAnalyte.id : null;

            document.querySelectorAll('.analyte-map-select').forEach(sel => {
                const val = sel.value;
                const col = sel.dataset.column;
                const logicInput = sel.parentElement.querySelector('.advanced-logic-input');

                if (val && parseInt(val) === idAnalyteId) {
                    animalIdCol = col;
                } else if (val) {
                    const analyteId = parseInt(val);
                    mapping[col] = analyteId;
                    if (logicInput && logicInput.value.trim()) {
                        advancedLogic[analyteId] = logicInput.value.trim();
                    }
                }
            });

            fileData.mapping = mapping;
            fileData.advanced_logic = advancedLogic;
            fileData.animal_id_column = animalIdCol;
        }

        if (!animalIdCol) {
            alert("Please map one column to 'uid'.");
            return;
        }

        // Save template if requested
        if (saveTemplateCheck.checked) {
            const name = templateNameInput.value || `Template for ${fileInput.files[0].name}`;
            await fetch(`/api/v1/import_wizard/templates/${protocolId}`, {
                method: 'POST',
                headers: getHeaders('application/json'),
                body: JSON.stringify({
                    name,
                    mapping_json: mapping,
                    skip_rows: fileData.skip_rows,
                    anchor_text: fileData.anchor_text,
                    anchor_offset: fileData.anchor_offset,
                    row_interval: fileData.row_interval,
                    advanced_logic: advancedLogic
                })
            });
        }

        // Validate Animals
        validationResults.innerHTML = '<div class="alert alert-info"><i class="fas fa-spinner fa-spin me-2"></i>Validating animal IDs...</div>';
        goToStep(3);

        try {
            const resp = await fetch('/api/v1/import_wizard/validate_animals', {
                method: 'POST',
                headers: getHeaders('application/json'),
                body: JSON.stringify({
                    file_path: fileData.file_path,
                    group_id: groupId,
                    animal_id_column: animalIdCol,
                    pipeline_id: document.getElementById('import-pipeline-select')?.value
                })
            });
            const vData = await resp.json();

            if (vData.valid) {
                validationResults.innerHTML = `
                    <div class="alert alert-success">
                        <i class="fas fa-check-circle me-2"></i>
                        All ${vData.total_found} animal IDs found in group.
                    </div>
                `;
            } else {
                validationResults.innerHTML = `
                    <div class="alert alert-danger">
                        <i class="fas fa-times-circle me-2"></i>
                        Found ${vData.total_found} labels, but ${vData.missing_ids.length} IDs are missing from the group:
                        <ul class="mt-2 text-start">
                            ${vData.missing_ids.slice(0, 10).map(id => `<li>${id}</li>`).join('')}
                            ${vData.missing_ids.length > 10 ? '<li>...</li>' : ''}
                        </ul>
                    </div>
                `;
            }
        } catch (e) {
            validationResults.innerHTML = `<div class="alert alert-danger">Error validating: ${e.message}</div>`;
        }
    }

    function handleStep3() {
        summaryText.textContent = `Ready to import ${fileData.total_rows} rows from ${fileInput.files[0].name}.`;
        goToStep(4);
    }

    async function finalizeImport() {
        finalizeBtn.disabled = true;
        finalizeBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Importing...';

        try {
            const resp = await fetch('/api/v1/import_wizard/import', {
                method: 'POST',
                headers: getHeaders('application/json'),
                body: JSON.stringify({
                    file_path: fileData.file_path,
                    data_table_id: dataTableId,
                    mapping: fileData.mapping,
                    animal_id_column: fileData.animal_id_column,
                    row_interval: fileData.row_interval,
                    advanced_logic: fileData.advanced_logic,
                    row_interval: fileData.row_interval,
                    advanced_logic: fileData.advanced_logic,
                    pipeline_id: document.getElementById('import-pipeline-select')?.value
                })
            });

            if (!resp.ok) throw new Error(await resp.text());

            const result = await resp.json();
            alert(result.message);
            window.location.reload();
        } catch (e) {
            alert("Final import failed: " + e.message);
            finalizeBtn.disabled = false;
            finalizeBtn.innerHTML = 'Import Now';
        }
    }

    function goToStep(step) {
        currentStep = step;
        document.querySelectorAll('.import-step').forEach((el, idx) => {
            el.classList.toggle('d-none', (idx + 1) !== step);
        });
        document.querySelectorAll('.step').forEach((el, idx) => {
            el.classList.toggle('active', (idx + 1) === step);
        });

        prevBtn.disabled = step === 1;
        nextBtn.classList.toggle('d-none', step === 4);
        finalizeBtn.classList.toggle('d-none', step !== 4);
    }
});

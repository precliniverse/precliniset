/**
 * static/js/groups/concatenation_manager.js
 * Handles Analyte Concatenation, Graphing, and Global Measurements.
 */

export class ConcatenationManager {
    constructor(config) {
        this.config = config;
        this.concatenatedData = null;
        this.availableAnalytes = [];
        this.init();
    }

    init() {
        this.injectUI();
        this.bindEvents();
    }

    injectUI() {
        // Add concatenation button to action bar (only when editing)
        let showConcatenationBtn = document.getElementById('show-concatenation-btn');
        if (!showConcatenationBtn && this.config.isEditing) {
            const actionBar = document.querySelector('.d-flex.align-items-center');
            if (actionBar) {
                showConcatenationBtn = document.createElement('button');
                showConcatenationBtn.type = 'button';
                showConcatenationBtn.className = 'btn btn-info ms-2';
                showConcatenationBtn.id = 'show-concatenation-btn';
                showConcatenationBtn.title = 'Analyte Concatenation & Analysis';
                showConcatenationBtn.innerHTML = '<i class="fas fa-chart-line"></i> Concatenation';
                actionBar.appendChild(showConcatenationBtn);
            }
        }

        // Show concatenation card
        let concatenationCard = document.getElementById('analyte-concatenation-card');
        if (!concatenationCard) {
            concatenationCard = document.createElement('div');
            concatenationCard.id = 'analyte-concatenation-card';
            concatenationCard.className = 'card mt-4';
            concatenationCard.style.display = 'none';
            concatenationCard.innerHTML = `
                <div class="card-header d-flex justify-content-between align-items-center">
                    <h5 class="mb-0">Analyte Concatenation & Analysis</h5>
                    <button type="button" class="btn btn-sm btn-outline-secondary" id="toggle-concatenation-btn">
                        <i class="fas fa-eye-slash"></i> Hide
                    </button>
                </div>
                <div class="card-body">
                    <p class="text-muted">Concatenate and analyze analytes from all datatables linked to this group chronologically.</p>

                    <div class="mb-3">
                        <label for="analyte-selector" class="form-label">Select Analytes to Concatenate</label>
                        <select id="analyte-selector" class="form-select" multiple style="min-height: 100px;"></select>
                        <small class="form-text text-muted">Select one or more analytes. Hold Ctrl/Cmd to select multiple.</small>
                    </div>

                    <button type="button" class="btn btn-primary mb-3" id="load-concatenation-btn">
                        <i class="fas fa-sync"></i> Load Concatenated Data
                    </button>

                    <div id="concatenated-data-container" style="display: none;">
                        <h6>Chronological Analyte Data</h6>
                        <div class="table-responsive" style="max-height: 400px; overflow-y: auto;">
                            <table class="table table-sm table-bordered table-striped" id="concatenated-data-table">
                                <thead class="table-light" style="position: sticky; top: 0; background: white;">
                                    <tr>
                                        <th>Animal ID</th>
                                        <th>Analyte</th>
                                        <th>Date</th>
                                        <th>Value</th>
                                        <th>Protocol</th>
                                    </tr>
                                </thead>
                                <tbody></tbody>
                            </table>
                        </div>

                        <!-- Global Measurement Tools -->
                        <div class="mt-4">
                            <h6>Global Measurement Tools</h6>
                            <div class="row g-3">
                                <div class="col-md-3">
                                    <label for="global-analyte-select" class="form-label">Select Analyte</label>
                                    <select id="global-analyte-select" class="form-select">
                                        <option value="">Choose Analyte</option>
                                    </select>
                                </div>
                                <div class="col-md-3">
                                    <label for="measurement-type-select" class="form-label">Measurement Type</label>
                                    <select id="measurement-type-select" class="form-select">
                                        <option value="baseline-reduction">Baseline Reduction %</option>
                                        <option value="time-reduction">Time-based Reduction</option>
                                        <option value="threshold-check">Threshold Check</option>
                                    </select>
                                </div>
                                <div class="col-md-2">
                                    <label for="measurement-value" class="form-label">Value</label>
                                    <input type="number" id="measurement-value" class="form-control" placeholder="20">
                                </div>
                                <div class="col-md-2">
                                    <label for="measurement-unit" class="form-label">Unit</label>
                                    <select id="measurement-unit" class="form-select">
                                        <option value="%">%</option>
                                        <option value="days">days</option>
                                        <option value="absolute">absolute</option>
                                    </select>
                                </div>
                                <div class="col-md-2">
                                    <label class="form-label">Action</label>
                                    <button type="button" class="btn btn-outline-info w-100" id="run-global-measurement-btn">
                                        <i class="fas fa-calculator"></i> Run
                                    </button>
                                </div>
                            </div>

                            <div id="global-measurement-results" class="mt-3" style="display: none;">
                                <div class="alert alert-info">
                                    <h6>Global Measurement Results</h6>
                                    <div id="global-measurement-output"></div>
                                </div>
                            </div>
                        </div>

                        <!-- Evolution Graph -->
                        <div class="mt-4">
                            <h6>Evolution Graph</h6>
                            <div class="row g-3">
                                <div class="col-md-4">
                                    <label for="graph-analyte-select" class="form-label">Select Analyte for Graph</label>
                                    <select id="graph-analyte-select" class="form-select">
                                        <option value="">Choose Analyte</option>
                                    </select>
                                </div>
                                <div class="col-md-4">
                                    <label class="form-label">Action</label>
                                    <button type="button" class="btn btn-outline-success w-100" id="generate-graph-btn">
                                        <i class="fas fa-chart-line"></i> Generate Graph
                                    </button>
                                </div>
                                <div class="col-md-4">
                                    <label class="form-label">Export</label>
                                    <button type="button" class="btn btn-outline-primary w-100" id="export-concatenated-btn">
                                        <i class="fas fa-download"></i> Export XLSX
                                    </button>
                                </div>
                            </div>
                            <div id="graph-container" class="mt-3" style="display: none;">
                                <canvas id="evolution-chart" width="400" height="200"></canvas>
                            </div>
                        </div>

                         <div class="mt-4">
                            <h6>Statistical Analysis</h6>
                            <div class="row g-3">
                                <div class="col-md-6">
                                    <label for="stats-analyte-select" class="form-label">Select Analyte for Stats</label>
                                    <select id="stats-analyte-select" class="form-select">
                                        <option value="">Choose Analyte</option>
                                    </select>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">Action</label>
                                    <button type="button" class="btn btn-outline-success w-100" id="calculate-stats-btn">
                                        <i class="fas fa-chart-line"></i> Calculate Statistics
                                    </button>
                                </div>
                            </div>
                            <div id="stats-results" class="mt-3" style="display: none;">
                                <div class="alert alert-success">
                                    <h6>Statistical Results</h6>
                                    <div id="stats-output"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            const saveButtonContainer = document.querySelector('.mt-4');
            if (saveButtonContainer && saveButtonContainer.parentNode) {
                saveButtonContainer.parentNode.insertBefore(concatenationCard, saveButtonContainer);
            } else {
                document.querySelector('.container').appendChild(concatenationCard);
            }
        }
    }

    bindEvents() {
        const showBtn = document.getElementById('show-concatenation-btn');
        const card = document.getElementById('analyte-concatenation-card');
        const hideBtn = document.getElementById('toggle-concatenation-btn');

        if (showBtn && card) {
            showBtn.addEventListener('click', () => {
                card.style.display = 'block';
                showBtn.style.display = 'none';
                this.loadAnalytes();
            });
        }
        if (hideBtn && card) {
            hideBtn.addEventListener('click', () => {
                card.style.display = 'none';
                if (showBtn) showBtn.style.display = 'inline-block';
            });
        }
        
        document.getElementById('load-concatenation-btn')?.addEventListener('click', () => this.loadConcatenatedData());
        document.getElementById('run-global-measurement-btn')?.addEventListener('click', () => this.runGlobalMeasurement());
        document.getElementById('generate-graph-btn')?.addEventListener('click', () => this.generateGraph());
        document.getElementById('calculate-stats-btn')?.addEventListener('click', () => this.calculateStats());
        document.getElementById('export-concatenated-btn')?.addEventListener('click', () => this.exportConcatenated());
    }

    loadAnalytes() {
        if (!this.config.groupId) return;
        fetch(`/groups/api/${this.config.groupId}/concatenated_analytes`)
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    alert(data.error);
                    return;
                }
                this.availableAnalytes = Object.values(data.analytes);
                const selector = document.getElementById('analyte-selector');
                selector.innerHTML = '';
                this.availableAnalytes.forEach(analyte => {
                    const option = document.createElement('option');
                    option.value = analyte.id;
                    option.textContent = `${analyte.name} (${analyte.unit || 'N/A'})`;
                    selector.appendChild(option);
                });
                this.concatenatedData = data;
            })
            .catch(err => console.error(err));
    }

    loadConcatenatedData() {
        const selectedOptions = Array.from(document.getElementById('analyte-selector').selectedOptions);
        if (selectedOptions.length === 0) {
            alert('Please select at least one analyte.');
            return;
        }

        const selectedAnalytes = selectedOptions.map(opt => {
            const analyteId = parseInt(opt.value);
            return this.availableAnalytes.find(a => a.id === analyteId).name;
        });

        this.populateTableAndSelectors(selectedAnalytes);
        document.getElementById('concatenated-data-container').style.display = 'block';
    }

    populateTableAndSelectors(selectedAnalytes) {
        const tbody = document.querySelector('#concatenated-data-table tbody');
        tbody.innerHTML = '';

        const globalSelect = document.getElementById('global-analyte-select');
        const graphSelect = document.getElementById('graph-analyte-select');
        const statsSelect = document.getElementById('stats-analyte-select');

        // Populate selects
        [globalSelect, graphSelect, statsSelect].forEach(sel => {
            if (!sel) return;
            const currentVal = sel.value;
            sel.innerHTML = '<option value="">Choose Analyte</option>';
            selectedAnalytes.forEach(name => {
                const opt = document.createElement('option');
                opt.value = name;
                opt.textContent = name;
                sel.appendChild(opt);
            });
            sel.value = currentVal;
        });

        // Populate Table
        Object.entries(this.concatenatedData.animal_data).forEach(([animalId, analytes]) => {
            selectedAnalytes.forEach(analyteName => {
                const values = analytes[analyteName] || [];
                values.forEach(entry => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td>${animalId}</td>
                        <td>${analyteName}</td>
                        <td>${entry.date}</td>
                        <td>${entry.value}</td>
                        <td>${entry.protocol || '-'}</td>
                    `;
                    tbody.appendChild(tr);
                });
            });
        });
    }

    runGlobalMeasurement() {
        const analyteName = document.getElementById('global-analyte-select').value;
        const type = document.getElementById('measurement-type-select').value;
        const value = parseFloat(document.getElementById('measurement-value').value);
        const unit = document.getElementById('measurement-unit').value;

        if (!analyteName || isNaN(value)) {
            alert("Please select an analyte and enter a valid value.");
            return;
        }

        const resultsContainer = document.getElementById('global-measurement-results');
        const output = document.getElementById('global-measurement-output');
        output.innerHTML = '';
        resultsContainer.style.display = 'block';

        const summary = [];

        Object.entries(this.concatenatedData.animal_data).forEach(([animalId, analytes]) => {
            const data = analytes[analyteName];
            if (!data || data.length === 0) return;

            // Sort by date just in case
            data.sort((a, b) => new Date(a.date) - new Date(b.date));

            if (type === 'baseline-reduction') {
                const baseline = data[0].value;
                const last = data[data.length - 1].value;
                const reduction = ((baseline - last) / baseline) * 100;
                if (reduction >= value) {
                    summary.push(`Animal <strong>${animalId}</strong>: ${reduction.toFixed(1)}% reduction (Target: ${value}%)`);
                }
            } else if (type === 'threshold-check') {
                const breached = data.some(d => d.value > value);
                if (breached) {
                    summary.push(`Animal <strong>${animalId}</strong>: Threshold of ${value} breached.`);
                }
            }
        });

        if (summary.length === 0) {
            output.innerHTML = "No animals matched the criteria.";
        } else {
            output.innerHTML = `<ul class="mb-0"><li>${summary.join('</li><li>')}</li></ul>`;
        }
    }

    generateGraph() {
        const analyteName = document.getElementById('graph-analyte-select').value;
        if (!analyteName) {
            alert("Please select an analyte for the graph.");
            return;
        }

        const container = document.getElementById('graph-container');
        container.style.display = 'block';

        const canvas = document.getElementById('evolution-chart');
        if (!canvas) return;
        
        const ctx = canvas.getContext('2d');
        
        // Destroy existing chart if any
        if (this.chart) {
            this.chart.destroy();
        }

        const datasets = [];
        const colors = [
            '#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b', 
            '#fd7e14', '#6610f2', '#6f42c1', '#e83e8c', '#20c997'
        ];
        let colorIdx = 0;

        Object.entries(this.concatenatedData.animal_data).forEach(([animalId, analytes]) => {
            const data = analytes[analyteName];
            if (!data || data.length === 0) return;

            // Sort by date
            const sortedData = [...data].sort((a, b) => new Date(a.date) - new Date(b.date));

            datasets.push({
                label: `Animal ${animalId}`,
                data: sortedData.map(d => ({ x: d.date, y: d.value })),
                borderColor: colors[colorIdx % colors.length],
                backgroundColor: colors[colorIdx % colors.length],
                fill: false,
                tension: 0.1
            });
            colorIdx++;
        });

        this.chart = new Chart(ctx, {
            type: 'line',
            data: { datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        type: 'time',
                        time: {
                            unit: 'day',
                            displayFormats: { day: 'MM-dd' }
                        },
                        title: { display: true, text: 'Date' }
                    },
                    y: {
                        title: { display: true, text: analyteName }
                    }
                },
                plugins: {
                    legend: { position: 'bottom' }
                }
            }
        });
    }

    calculateStats() {
        const analyteName = document.getElementById('stats-analyte-select').value;
        if (!analyteName) {
            alert("Please select an analyte for statistics.");
            return;
        }

        const resultsContainer = document.getElementById('stats-results');
        const output = document.getElementById('stats-output');
        output.innerHTML = '';
        resultsContainer.style.display = 'block';

        const allValues = [];
        Object.values(this.concatenatedData.animal_data).forEach(analytes => {
            const data = analytes[analyteName];
            if (data) {
                data.forEach(d => {
                    const val = parseFloat(d.value);
                    if (!isNaN(val)) allValues.push(val);
                });
            }
        });

        if (allValues.length === 0) {
            output.innerHTML = "No numeric data available for the selected analyte.";
            return;
        }

        const mean = allValues.reduce((a, b) => a + b, 0) / allValues.length;
        const sorted = [...allValues].sort((a, b) => a - b);
        const median = sorted.length % 2 === 0 
            ? (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2 
            : sorted[Math.floor(sorted.length / 2)];
        
        const variance = allValues.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / allValues.length;
        const stdDev = Math.sqrt(variance);

        output.innerHTML = `
            <div class="row">
                <div class="col-6"><strong>N:</strong> ${allValues.length}</div>
                <div class="col-6"><strong>Mean:</strong> ${mean.toFixed(2)}</div>
                <div class="col-6"><strong>Median:</strong> ${median.toFixed(2)}</div>
                <div class="col-6"><strong>Std Dev:</strong> ${stdDev.toFixed(2)}</div>
                <div class="col-6"><strong>Min:</strong> ${Math.min(...allValues).toFixed(2)}</div>
                <div class="col-6"><strong>Max:</strong> ${Math.max(...allValues).toFixed(2)}</div>
            </div>
        `;
    }

    exportConcatenated() {
         fetch(`/groups/export_concatenated/${this.config.groupId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('input[name="csrf_token"]').value },
            body: JSON.stringify({ concatenated_data: this.concatenatedData })
         })
         .then(response => response.blob())
         .then(blob => {
             const url = window.URL.createObjectURL(blob);
             const a = document.createElement('a');
             a.href = url;
             a.download = `concatenated_analytes_${this.config.groupId}.xlsx`;
             document.body.appendChild(a);
             a.click();
             window.URL.revokeObjectURL(url);
             document.body.removeChild(a);
         });
    }
}

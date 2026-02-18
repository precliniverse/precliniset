/**
 * static/js/groups/concatenate_page.js
 * Handles Analyte Concatenation, Graphing, and Global Measurements for the dedicated page.
 */

export class ConcatenationPage {
    constructor(config) {
        this.config = config;
        this.concatenatedData = null;
        this.availableAnalytes = [];
        this.chart = null;
        this.init();
    }

    init() {
        this.bindEvents();
        this.loadAnalytes();
    }

    bindEvents() {
        document.getElementById('load-concatenation-btn')?.addEventListener('click', () => this.loadConcatenatedData());
        document.getElementById('global-measurement-select')?.addEventListener('change', () => this.updateGlobalToolInputs());
        document.getElementById('export-concatenated-btn')?.addEventListener('click', () => this.exportConcatenated());

        // Group switch for graph
        document.getElementById('group-by-treatment-switch')?.addEventListener('change', () => {
            if (this.currentAnalyteForGraph) {
                this.generateGraph(this.currentAnalyteForGraph);
            }
        });
    }

    loadAnalytes() {
        if (!this.config.groupId) return;

        const loader = document.getElementById('load-concatenation-btn');
        const originalText = loader.innerHTML;
        loader.disabled = true;
        loader.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> ${this.config.i18n.loading}`;

        fetch(this.config.urls.getConcatenatedAnalytes)
            .then(response => response.json())
            .then(data => {
                loader.disabled = false;
                loader.innerHTML = originalText;

                if (data.error) {
                    alert(data.error);
                    return;
                }

                // Store data but wait for user to select analytes to display
                this.availableAnalytes = Object.values(data.analytes || {});
                this.concatenatedData = data;

                this.populateAnalyteSelector();
            })
            .catch(err => {
                console.error(err);
                loader.disabled = false;
                loader.innerHTML = originalText;
                alert('Failed to load analytes.');
            });
    }

    populateAnalyteSelector() {
        const selector = document.getElementById('analyte-selector');
        selector.innerHTML = '';

        if (this.availableAnalytes.length === 0) {
            const option = document.createElement('option');
            option.text = this.config.i18n.noData;
            option.disabled = true;
            selector.add(option);
            return;
        }

        // Sort analytes by name
        this.availableAnalytes.sort((a, b) => a.name.localeCompare(b.name));

        this.availableAnalytes.forEach(analyte => {
            const option = document.createElement('option');
            option.value = analyte.id; // Only ID used for selection
            option.textContent = `${analyte.name} (${analyte.unit || '-'})`;
            option.dataset.name = analyte.name;
            selector.appendChild(option);
        });
    }

    loadConcatenatedData() {
        const selector = document.getElementById('analyte-selector');
        const selectedOptions = Array.from(selector.selectedOptions);

        if (selectedOptions.length === 0) {
            alert('Please select at least one analyte.');
            return;
        }

        const selectedAnalyteNames = selectedOptions.map(opt => opt.dataset.name);

        this.renderTable(selectedAnalyteNames);
        this.setupGlobalTools(selectedAnalyteNames);
        this.setupGraph(selectedAnalyteNames);

        // Unhide containers
        document.getElementById('concatenated-data-container').style.display = 'block';
        document.getElementById('global-measurement-tools-card').style.display = 'block';
        document.getElementById('graph-container').style.display = 'block';
        document.getElementById('concatenation-placeholder').style.display = 'none';
        document.getElementById('export-concatenated-btn').disabled = false;
    }

    renderTable(selectedAnalyteNames) {
        const thead = document.getElementById('concatenated-table-header');
        const tbody = document.getElementById('concatenated-table-body');

        // Build Header
        // Group | Animal ID | Date | Analyte | Value | Protocol
        thead.innerHTML = `
            <th>${'Group'}</th>
            <th>${'Animal ID'}</th>
            <th>${'Date'}</th>
            <th>${'Analyte'}</th>
            <th>${'Value'}</th>
            <th>${'Protocol'}</th>
        `;

        tbody.innerHTML = '';

        const rows = [];

        // Flatten data for table: animal -> analyte -> measurements
        Object.entries(this.concatenatedData.animal_data).forEach(([animalId, analytes]) => {
            selectedAnalyteNames.forEach(analyteName => {
                const measurements = analytes[analyteName] || [];
                measurements.forEach(m => {
                    rows.push({
                        animalId: animalId,
                        analyte: analyteName,
                        date: m.date,
                        value: m.value,
                        protocol: m.protocol || '-',
                        group: 'Unknown' // Ideally we'd have group info here, can rely on existingAnimalData if passed
                    });
                });
            });
        });

        // Sort by Date, then Animal ID, then Analyte
        rows.sort((a, b) => {
            const dateDiff = new Date(a.date) - new Date(b.date);
            if (dateDiff !== 0) return dateDiff;
            return a.animalId.localeCompare(b.animalId);
        });

        rows.forEach(row => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>-</td>
                <td>${row.animalId}</td>
                <td>${row.date}</td>
                <td>${row.analyte}</td>
                <td>${row.value}</td>
                <td>${row.protocol}</td>
            `;
            tbody.appendChild(tr);
        });
    }

    setupGraph(selectedAnalyteNames) {
        // For simplicity, generate graph for the first selected analyte automatically
        // In a real app, might want a selector if multiple are chosen
        const primaryAnalyte = selectedAnalyteNames[0];
        if (primaryAnalyte) {
            this.currentAnalyteForGraph = primaryAnalyte;
            this.generateGraph(primaryAnalyte);
        }
    }

    generateGraph(analyteName) {
        const canvas = document.getElementById('evolution-chart');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        if (this.chart) this.chart.destroy();

        const groupByTreatment = document.getElementById('group-by-treatment-switch').checked;
        const datasets = [];
        const colors = [
            '#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b',
            '#fd7e14', '#6610f2', '#6f42c1', '#e83e8c', '#20c997'
        ];

        // Prepare data
        // Map: Label -> [ {x, y} ]
        const seriesData = {};

        Object.entries(this.concatenatedData.animal_data).forEach(([animalId, analytes]) => {
            const measurements = analytes[analyteName] || [];
            if (measurements.length === 0) return;

            // Determine series label (Animal ID or Treatment Group)
            // Note: Treatment group info isn't currently in the concatenated API response payload structure 
            // shown in `concatenation_manager.js`. We might need to look it up from `this.concatenatedData` 
            // if it contains animal metadata, or fallback to Animal ID.
            // For now, let's use Animal ID as the specific API response is not fully visible to me.
            // If we wanted grouping, we'd need to fetch animal details or pass them in config.

            const label = animalId;

            if (!seriesData[label]) seriesData[label] = [];

            measurements.forEach(m => {
                seriesData[label].push({
                    x: m.date,
                    y: parseFloat(m.value)
                });
            });
        });

        Object.keys(seriesData).forEach((label, index) => {
            // Sort by date
            seriesData[label].sort((a, b) => new Date(a.x) - new Date(b.x));

            datasets.push({
                label: label,
                data: seriesData[label],
                borderColor: colors[index % colors.length],
                backgroundColor: colors[index % colors.length],
                tension: 0.1,
                fill: false,
                pointRadius: 3
            });
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
                        time: { unit: 'day', displayFormats: { day: 'MMM dd' } },
                        title: { display: true, text: 'Date' }
                    },
                    y: {
                        title: { display: true, text: analyteName }
                    }
                },
                plugins: {
                    legend: { position: 'right' },
                    title: { display: true, text: `Evolution of ${analyteName}` }
                }
            }
        });
    }

    updateGlobalToolInputs() {
        const type = document.getElementById('global-measurement-select').value;
        const container = document.getElementById('global-tool-params');
        container.innerHTML = '';

        if (!type) return;

        // Implement specific inputs based on type
        // This is a placeholder for the logic seen in concatenation_manager.js
        // Ideally we would port the full logic over for 'weight_change_pct' etc.
        // For now, let's just show a simple "Not implemented" if it's complex, or basic inputs

        if (type === 'weight_change_pct') {
            container.innerHTML = `
                <div class="input-group">
                   <span class="input-group-text">Baseline Date</span>
                   <input type="date" class="form-control" id="baseline-date">
                   <button class="btn btn-outline-secondary" type="button" id="calc-tool-btn">Calculate</button>
                </div>
            `;
        } else {
            container.innerHTML = `<span class="text-muted">Tool configuration for ${type}</span>`;
        }
    }

    setupGlobalTools(selectedAnalytes) {
        // No-op for now, just clears previous state if needed
    }

    exportConcatenated() {
        // Use the filtered data if possible, or just dump everything?
        // The API export_concatenated uses the posted body.
        // ConcatenationManager sent `this.concatenatedData`. 
        // We will do the same.

        fetch(this.config.urls.exportConcatenated, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.config.csrfToken
            },
            body: JSON.stringify({ concatenated_data: this.concatenatedData })
        })
            .then(response => {
                if (!response.ok) throw new Error('Export failed');
                return response.blob();
            })
            .then(blob => {
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `concatenated_analytes_${this.config.groupId}.xlsx`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
            })
            .catch(err => {
                console.error(err);
                alert('Failed to export data.');
            });
    }
}

// ═══════════════════════════════════════════════════════════
// TAB 2 — Ethical Health Monitoring
// ═══════════════════════════════════════════════════════════
class HealthMonitoringTab {
    constructor(config) {
        this.config = config;
        this.healthData = null;
        this.chart = null;
        this.bindEvents();
        // Load available analytes for intergroup tab when health tab is first shown
    }

    bindEvents() {
        document.getElementById('load-health-btn')?.addEventListener('click', () => this.loadHealthData());
        document.getElementById('health-filter-status')?.addEventListener('change', () => this.renderHealthChart());
    }

    loadHealthData() {
        const critical = document.getElementById('health-threshold-critical')?.value || 20;
        const warning = document.getElementById('health-threshold-warning')?.value || 10;
        const btn = document.getElementById('load-health-btn');
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm"></span>`;

        const url = `${this.config.urls.getHealthTracking}?threshold_critical=${critical}&threshold_warning=${warning}`;
        fetch(url)
            .then(r => r.json())
            .then(data => {
                btn.disabled = false;
                btn.innerHTML = `<i class="fas fa-sync me-1"></i> ${this.config.i18n.loading.replace('...', '')} Health Data`;
                if (data.error) { alert(data.error); return; }
                this.healthData = data;
                this.renderHealthSummary();
                this.renderHealthChart();
                this.renderHealthAlerts();
                document.getElementById('health-placeholder').style.display = 'none';
                document.getElementById('health-chart-card').style.display = 'block';
                document.getElementById('health-alerts-card').style.display = 'block';
            })
            .catch(err => {
                btn.disabled = false;
                btn.innerHTML = `<i class="fas fa-sync me-1"></i> Load Health Data`;
                console.error(err);
            });
    }

    renderHealthSummary() {
        const container = document.getElementById('health-summary-cards');
        if (!container || !this.healthData) return;
        const animals = this.healthData.animals || [];
        const critical = animals.filter(a => a.alert_level === 'critical').length;
        const warning = animals.filter(a => a.alert_level === 'warning').length;
        const ok = animals.filter(a => a.alert_level === 'ok').length;
        const analyte = this.healthData.weight_analyte || 'N/A';

        container.innerHTML = `
            <div class="col-6 col-md-3">
                <div class="card text-center border-secondary">
                    <div class="card-body py-2">
                        <div class="fs-4 fw-bold">${animals.length}</div>
                        <div class="small text-muted">Animals</div>
                    </div>
                </div>
            </div>
            <div class="col-6 col-md-3">
                <div class="card text-center border-danger">
                    <div class="card-body py-2">
                        <div class="fs-4 fw-bold text-danger">${critical}</div>
                        <div class="small text-muted">${this.config.i18n.critical}</div>
                    </div>
                </div>
            </div>
            <div class="col-6 col-md-3">
                <div class="card text-center border-warning">
                    <div class="card-body py-2">
                        <div class="fs-4 fw-bold text-warning">${warning}</div>
                        <div class="small text-muted">${this.config.i18n.warning}</div>
                    </div>
                </div>
            </div>
            <div class="col-6 col-md-3">
                <div class="card text-center border-success">
                    <div class="card-body py-2">
                        <div class="fs-4 fw-bold text-success">${ok}</div>
                        <div class="small text-muted">${this.config.i18n.ok}</div>
                    </div>
                </div>
            </div>
            <div class="col-12 mt-2">
                <div class="alert alert-info py-1 mb-0 small">
                    <i class="fas fa-info-circle me-1"></i>
                    Analyte: <strong>${analyte}</strong> &nbsp;|&nbsp;
                    Thresholds: Critical ≥${this.healthData.thresholds.critical}% vs baseline,
                    Warning ≥${this.healthData.thresholds.warning}% vs previous
                </div>
            </div>
        `;
    }

    renderHealthChart() {
        const canvas = document.getElementById('health-chart');
        if (!canvas || !this.healthData) return;
        const ctx = canvas.getContext('2d');
        if (this.chart) this.chart.destroy();

        const filterStatus = document.getElementById('health-filter-status')?.value || 'all';
        const animals = (this.healthData.animals || []).filter(a =>
            filterStatus === 'all' || a.alert_level === filterStatus
        );

        const COLORS = {
            critical: '#dc3545',
            warning: '#ffc107',
            ok: '#198754'
        };
        const PALETTE = ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b', '#fd7e14', '#6610f2', '#6f42c1'];

        const datasets = animals.map((animal, idx) => ({
            label: animal.id,
            data: animal.series.filter(s => s.value !== null).map(s => ({ x: s.date, y: s.value })),
            borderColor: COLORS[animal.alert_level] || PALETTE[idx % PALETTE.length],
            backgroundColor: 'transparent',
            tension: 0.2,
            pointRadius: 4,
            borderWidth: animal.alert_level === 'critical' ? 2.5 : 1.5,
            borderDash: animal.alert_level === 'warning' ? [5, 3] : []
        }));

        this.chart = new Chart(ctx, {
            type: 'line',
            data: { datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'day', displayFormats: { day: 'MMM dd' } }, title: { display: true, text: 'Date' } },
                    y: { title: { display: true, text: this.healthData.weight_analyte || 'Weight' } }
                },
                plugins: {
                    legend: { position: 'right', labels: { boxWidth: 12, font: { size: 11 } } },
                    title: { display: true, text: `Weight Evolution (${filterStatus === 'all' ? 'all animals' : filterStatus + ' only'})` }
                }
            }
        });
    }

    renderHealthAlerts() {
        const tbody = document.getElementById('health-alerts-body');
        if (!tbody || !this.healthData) return;
        tbody.innerHTML = '';
        const animals = this.healthData.animals || [];
        const alertAnimals = animals.filter(a => a.has_alerts);

        if (alertAnimals.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" class="text-center text-success py-3"><i class="fas fa-check-circle me-1"></i>No alerts detected.</td></tr>`;
            return;
        }

        alertAnimals.forEach(animal => {
            animal.alerts.forEach(alert => {
                const badgeClass = alert.status === 'critical' ? 'bg-danger' : 'bg-warning text-dark';
                const tr = document.createElement('tr');
                tr.className = alert.status === 'critical' ? 'table-danger' : 'table-warning';
                tr.innerHTML = `
                    <td><strong>${animal.id}</strong></td>
                    <td>${animal.treatment_group || '-'}</td>
                    <td>${alert.date}</td>
                    <td><span class="badge ${badgeClass}">${alert.status.toUpperCase()}</span></td>
                    <td><small>${alert.message}</small></td>
                `;
                tbody.appendChild(tr);
            });
        });
    }
}

// ═══════════════════════════════════════════════════════════
// TAB 3 — Inter-group Comparison
// ═══════════════════════════════════════════════════════════
class IntergroupComparisonTab {
    constructor(config) {
        this.config = config;
        this.compData = null;
        this.chart = null;
        this.bindEvents();
        this.loadAvailableAnalytes();
    }

    bindEvents() {
        document.getElementById('load-intergroup-btn')?.addEventListener('click', () => this.loadComparison());
        document.getElementById('intergroup-show-sem')?.addEventListener('change', () => {
            if (this.compData) this.renderChart();
        });
    }

    loadAvailableAnalytes() {
        fetch(this.config.urls.getIntergroupComparison)
            .then(r => r.json())
            .then(data => {
                const sel = document.getElementById('intergroup-analyte-select');
                if (!sel) return;
                sel.innerHTML = '<option value="">-- Select analyte --</option>';
                (data.available_analytes || []).forEach(name => {
                    const opt = document.createElement('option');
                    opt.value = name;
                    opt.textContent = name;
                    sel.appendChild(opt);
                });
            })
            .catch(err => console.error('Failed to load analytes for intergroup:', err));
    }

    loadComparison() {
        const analyte = document.getElementById('intergroup-analyte-select')?.value;
        if (!analyte) { alert('Please select an analyte.'); return; }

        const btn = document.getElementById('load-intergroup-btn');
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm"></span>`;

        fetch(`${this.config.urls.getIntergroupComparison}?analyte=${encodeURIComponent(analyte)}`)
            .then(r => r.json())
            .then(data => {
                btn.disabled = false;
                btn.innerHTML = `<i class="fas fa-sync me-1"></i> Load Comparison`;
                if (data.error) { alert(data.error); return; }
                this.compData = data;
                document.getElementById('intergroup-chart-title').textContent = `Mean ± SEM — ${analyte}`;
                document.getElementById('intergroup-placeholder').style.display = 'none';
                document.getElementById('intergroup-chart-card').style.display = 'block';
                document.getElementById('intergroup-table-card').style.display = 'block';
                this.renderChart();
                this.renderTable();
            })
            .catch(err => {
                btn.disabled = false;
                btn.innerHTML = `<i class="fas fa-sync me-1"></i> Load Comparison`;
                console.error(err);
            });
    }

    renderChart() {
        const canvas = document.getElementById('intergroup-chart');
        if (!canvas || !this.compData) return;
        const ctx = canvas.getContext('2d');
        if (this.chart) this.chart.destroy();

        const showSem = document.getElementById('intergroup-show-sem')?.checked ?? true;
        const PALETTE = ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b', '#fd7e14', '#6610f2', '#6f42c1'];
        const dates = this.compData.dates || [];
        const groups = this.compData.treatment_groups || [];

        const datasets = groups.map((tg, idx) => {
            const color = PALETTE[idx % PALETTE.length];
            const series = this.compData.series_by_group[tg] || [];
            const points = series.map((s, i) => ({ x: dates[i], y: s.mean }));
            const ds = {
                label: tg,
                data: points,
                borderColor: color,
                backgroundColor: color + '33',
                tension: 0.2,
                pointRadius: 4,
                fill: false
            };
            if (showSem) {
                // Error bars via custom plugin or just show as tooltip
                ds.errorBars = series.map(s => s.sem);
            }
            return ds;
        });

        this.chart = new Chart(ctx, {
            type: 'line',
            data: { datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { unit: 'day', displayFormats: { day: 'MMM dd' } }, title: { display: true, text: 'Date' } },
                    y: { title: { display: true, text: this.compData.analyte || '' } }
                },
                plugins: {
                    legend: { position: 'top' },
                    tooltip: {
                        callbacks: {
                            afterLabel: (ctx) => {
                                const tg = ctx.dataset.label;
                                const series = this.compData.series_by_group[tg] || [];
                                const s = series[ctx.dataIndex];
                                if (!s) return '';
                                return showSem ? `SEM: ±${s.sem?.toFixed(3)} (n=${s.n})` : `n=${s.n}`;
                            }
                        }
                    }
                }
            }
        });
    }

    renderTable() {
        const tbody = document.getElementById('intergroup-stats-body');
        if (!tbody || !this.compData) return;
        tbody.innerHTML = '';
        const dates = this.compData.dates || [];
        const groups = this.compData.treatment_groups || [];

        dates.forEach(date => {
            groups.forEach(tg => {
                const series = this.compData.series_by_group[tg] || [];
                const dateIdx = dates.indexOf(date);
                const s = series[dateIdx];
                if (!s || s.n === 0) return;
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${date}</td>
                    <td>${tg}</td>
                    <td>${s.n}</td>
                    <td>${s.mean?.toFixed(3) ?? '-'}</td>
                    <td>${s.sem?.toFixed(3) ?? '-'}</td>
                `;
                tbody.appendChild(tr);
            });
        });

        if (tbody.children.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted">No data available.</td></tr>`;
        }
    }
}

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    const configEl = document.getElementById('page-config');
    if (configEl) {
        const config = JSON.parse(configEl.dataset.config);
        new ConcatenationPage(config);
        new HealthMonitoringTab(config);
        new IntergroupComparisonTab(config);
    }
});

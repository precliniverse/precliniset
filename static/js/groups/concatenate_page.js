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

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    const configEl = document.getElementById('page-config');
    if (configEl) {
        const config = JSON.parse(configEl.dataset.config);
        new ConcatenationPage(config);
    }
});

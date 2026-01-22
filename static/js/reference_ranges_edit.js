// reference_ranges_edit.js
/* global $, Plotly */

// This file handles the create/edit reference range functionality
// It expects the following global variables to be set by the template:
// - window.ReferenceRangeConfig.isEditing
// - window.ReferenceRangeConfig.existingData
// - window.ReferenceRangeConfig.rangeId
// - window.ReferenceRangeConfig.urls (analyte search, protocols, filters, etc.)

(function() {
    'use strict';

    $(document).ready(function () {
        const config = window.ReferenceRangeConfig || {};
        
        // Initialize Select2
        $('#team_id, #protocol_id, #animal_model_id, #shared_with_team_ids').select2({ theme: "bootstrap-5" });

        // Analyte search with Select2
        $('#analyte_id').select2({
            theme: "bootstrap-5",
            ajax: {
                url: config.urls.searchAnalytes,
                dataType: 'json',
                delay: 250,
                data: function (params) {
                    return { q: params.term };
                },
                processResults: function (data) {
                    return { results: data.items };
                },
                cache: true
            },
            placeholder: config.translations.searchAnalyte,
            minimumInputLength: 1
        });

        const $form = $('#referenceRangeForm');
        const $searchFiltersContainer = $('#search-filters');
        const $searchBtn = $('#searchBtn');
        const $selectAllBtn = $('#selectAllBtn');
        const $searchResultsTable = $('#searchResultsTable');
        const $includedAnimalsBody = $('#includedAnimalsTable tbody');
        const $isGloballySharedCheckbox = $('#is_globally_shared');
        const $sharedWithTeamsSelect = $('#shared_with_team_ids');
        const $filterIncludedAnimals = $('#filterIncludedAnimals');
        const $deleteSelectedBtn = $('#deleteSelectedBtn');

        const isEditing = config.isEditing || false;
        let existingData = config.existingData || {};
        let includedAnimals = {}; // Format: { group_id: Set(animal_index, ...), ... }

        // Filter included animals table
        $filterIncludedAnimals.on('keyup', function() {
            const value = $(this).val().toLowerCase();
            $includedAnimalsBody.find('tr').filter(function() {
                $(this).toggle($(this).text().toLowerCase().indexOf(value) > -1);
            });
        });

        // Select all checkboxes in included animals
        $(document).on('change', '#selectAllIncluded', function() {
            const isChecked = $(this).prop('checked');
            $('.animal-checkbox:visible').prop('checked', isChecked);
            updateDeleteButtonVisibility();
        });

        // Update delete button visibility when individual checkboxes change
        $(document).on('change', '.animal-checkbox', function() {
            updateDeleteButtonVisibility();
        });

        function updateDeleteButtonVisibility() {
            const checkedCount = $('.animal-checkbox:checked').length;
            if (checkedCount > 0) {
                $deleteSelectedBtn.show();
            } else {
                $deleteSelectedBtn.hide();
            }
        }

        // Delete selected animals
        $deleteSelectedBtn.on('click', function() {
            if (!confirm(config.translations.confirmDeleteSelected)) {
                return;
            }
            
            $('.animal-checkbox:checked').each(function() {
                const $row = $(this).closest('tr');
                const groupId = $row.data('group-id');
                const animalIndex = $row.data('animal-index');
                if (includedAnimals[groupId]) {
                    includedAnimals[groupId].delete(animalIndex);
                    if (includedAnimals[groupId].size === 0) {
                        delete includedAnimals[groupId];
                    }
                }
                $row.remove();
            });
            
            updateDeleteButtonVisibility();
            $('#selectAllIncluded').prop('checked', false);
        });

        function toggleSharedWithTeams() {
            if ($isGloballySharedCheckbox.is(':checked')) {
                $sharedWithTeamsSelect.val(null).trigger('change').prop('disabled', true);
            } else {
                $sharedWithTeamsSelect.prop('disabled', false);
            }
        }

        $isGloballySharedCheckbox.on('change', toggleSharedWithTeams);

        function renderParameterFilters(params = {}) {
            $searchFiltersContainer.empty();
            $.each(params, function (key, values) {
                let options = `<option value="">-- ${config.translations.any} --</option>`;
                values.forEach(v => options += `<option value="${v}">${v}</option>`);
                $searchFiltersContainer.append(`
                    <div class="row mb-2 align-items-center">
                        <div class="col-md-3"><label class="form-label">${key}</label></div>
                        <div class="col-md-9"><select class="form-select search-param-filter" data-param-key="${key}">${options}</select></div>
                    </div>`);
            });
            $searchFiltersContainer.find('.search-param-filter').select2({ theme: "bootstrap-5" });
        }

        function performSearch() {
            const protocolId = $('#protocol_id').val();
            const modelId = $('#animal_model_id').val();
            if (!protocolId || !modelId) {
                alert(config.translations.selectProtocolAndModel);
                return;
            }

            let filters = {};
            $('.search-param-filter').each(function () {
                const $select = $(this);
                if ($select.val()) {
                    filters[$select.data('param-key')] = $select.val();
                }
            });

            const apiUrl = `${config.urls.searchAnimals}?protocol_id=${protocolId}&model_id=${modelId}&filters=${encodeURIComponent(JSON.stringify(filters))}`;

            $searchResultsTable.find('thead, tbody').empty();
            $searchResultsTable.find('tbody').html(`<tr><td colspan="100%">${config.translations.searching}</td></tr>`);

            $.getJSON(apiUrl, function (response) {
                const { columns, data } = response;
                $searchResultsTable.find('tbody').empty();

                let headerRow = '<tr>';
                columns.forEach(col => headerRow += `<th>${col}</th>`);
                headerRow += `<th>${config.translations.action}</th></tr>`;
                $searchResultsTable.find('thead').html(headerRow);

                if (data.length === 0) {
                    $searchResultsTable.find('tbody').html(`<tr><td colspan="${columns.length + 1}">${config.translations.noAnimalsFound}</td></tr>`);
                    return;
                }

                data.forEach(function (animal) {
                    const uniqueId = `${animal.group_id}-${animal.animal_index}`;
                    const isIncluded = includedAnimals[animal.group_id] && includedAnimals[animal.group_id].has(animal.animal_index);
                    if (isIncluded) return;

                    let row = `<tr data-animal-unique-id="${uniqueId}" data-animal-info='${JSON.stringify(animal)}'>`;
                    columns.forEach(col => row += `<td>${animal[col] || ''}</td>`);
                    row += `<td><i class="fas fa-plus-circle add-btn"></i></td></tr>`;
                    $searchResultsTable.find('tbody').append(row);
                });
            }).fail(() => $searchResultsTable.find('tbody').html(`<tr><td colspan="100%">${config.translations.searchError}</td></tr>`));
        }

        function addAnimalToIncluded(animalData) {
            const uniqueId = `${animalData.group_id}-${animalData.animal_index}`;
            if ($(`#includedAnimalsTable tbody tr[data-animal-unique-id="${uniqueId}"]`).length > 0) return;

            if (!includedAnimals[animalData.group_id]) {
                includedAnimals[animalData.group_id] = new Set();
            }
            includedAnimals[animalData.group_id].add(animalData.animal_index);

            // Update headers if needed
            updateIncludedTableHeaders(animalData);
            
            // Build row with all parameters dynamically
            let rowHtml = `<tr data-animal-unique-id="${uniqueId}" data-group-id="${animalData.group_id}" data-animal-index="${animalData.animal_index}" data-animal-info='${JSON.stringify(animalData)}'>`;
            rowHtml += `<td><input type="checkbox" class="animal-checkbox"></td>`;
            rowHtml += `<td>${animalData['Animal ID']}</td>`;
            rowHtml += `<td>${animalData.group_name}</td>`;
            rowHtml += `<td>${animalData.project_name}</td>`;
            
            // Add all other parameters dynamically
            const fixedCols = ['Animal ID', 'group_name', 'project_name', 'group_id', 'animal_index'];
            for (const key in animalData) {
                if (!fixedCols.includes(key)) {
                    rowHtml += `<td>${animalData[key] || ''}</td>`;
                }
            }
            
            rowHtml += `<td><i class="fas fa-trash-alt remove-btn"></i></td></tr>`;
            $includedAnimalsBody.append(rowHtml);
        }

        function updateIncludedTableHeaders(sampleAnimalData) {
            const $header = $('#includedAnimalsTableHeader');
            
            // Count how many columns we need
            const fixedCols = ['Animal ID', 'group_name', 'project_name', 'group_id', 'animal_index'];
            const extraParams = Object.keys(sampleAnimalData).filter(key => !fixedCols.includes(key));
            
            // Check if we need to add extra parameter headers
            const currentExtraHeaders = $header.find('th').length - 5; // minus checkbox, ID, Group, Project, Action
            if (currentExtraHeaders < extraParams.length) {
                // Rebuild headers
                $header.empty();
                $header.append('<th><input type="checkbox" id="selectAllIncluded"></th>');
                $header.append(`<th>${config.translations.animalId}</th>`);
                $header.append(`<th>${config.translations.group}</th>`);
                $header.append(`<th>${config.translations.project}</th>`);
                extraParams.forEach(param => $header.append(`<th>${param}</th>`));
                $header.append(`<th>${config.translations.action}</th>`);
            }
        }

        $('#analyte_id').on('change', function () {
            const analyteId = $(this).val();
            const $protocolSelect = $('#protocol_id');
            const $modelSelect = $('#animal_model_id');

            $protocolSelect.html(`<option value="">-- ${config.translations.loading} --</option>`).prop('disabled', true);
            $modelSelect.html(`<option value="">-- ${config.translations.selectProtocolFirst} --</option>`).prop('disabled', true);
            renderParameterFilters();

            if (analyteId) {
                $.getJSON(`${config.urls.getProtocols}?analyte_id=${analyteId}`, function (data) {
                    $protocolSelect.html(`<option value="">-- ${config.translations.selectProtocol} --</option>`);
                    data.protocols.forEach(p => $protocolSelect.append(`<option value="${p.id}">${p.name}</option>`));
                    $protocolSelect.prop('disabled', false);

                    if (isEditing && existingData.protocol_id) {
                        $protocolSelect.val(existingData.protocol_id).trigger('change');
                    }
                });
            } else {
                $protocolSelect.html(`<option value="">-- ${config.translations.selectAnalyteFirst} --</option>`).prop('disabled', true);
            }
        });

        $('#protocol_id').on('change', function () {
            const protocolId = $(this).val();
            const $modelSelect = $('#animal_model_id');

            $modelSelect.html(`<option value="">-- ${config.translations.loading} --</option>`).prop('disabled', true);
            renderParameterFilters();

            if (protocolId) {
                $.getJSON(`${config.urls.getFilters}?protocol_id=${protocolId}`, function (data) {
                    $modelSelect.html(`<option value="">-- ${config.translations.selectModel} --</option>`);
                    data.animal_models.forEach(m => $modelSelect.append(`<option value="${m.id}">${m.name}</option>`));
                    $modelSelect.prop('disabled', false);

                    if (isEditing && existingData.animal_model_id) {
                        $modelSelect.val(existingData.animal_model_id).trigger('change');
                    }
                });
            } else {
                $modelSelect.html(`<option value="">-- ${config.translations.selectProtocolFirst} --</option>`).prop('disabled', true);
            }
        });

        $('#animal_model_id').on('change', function () {
            const protocolId = $('#protocol_id').val();
            const modelId = $(this).val();

            renderParameterFilters();

            if (protocolId && modelId) {
                $.getJSON(`${config.urls.getFilters}?protocol_id=${protocolId}&model_id=${modelId}`, function (data) {
                    renderParameterFilters(data.parameters);
                });
            }
        });

        $searchBtn.on('click', performSearch);

        $selectAllBtn.on('click', function () {
            $searchResultsTable.find('tbody .add-btn').each(function () {
                $(this).trigger('click');
            });
        });

        $searchResultsTable.on('click', '.add-btn', function () {
            const $row = $(this).closest('tr');
            const animalData = $row.data('animal-info');
            addAnimalToIncluded(animalData);
            $row.remove();
        });

        $includedAnimalsBody.on('click', '.remove-btn', function () {
            const $row = $(this).closest('tr');
            const groupId = $row.data('group-id');
            const animalIndex = $row.data('animal-index');
            if (includedAnimals[groupId]) {
                includedAnimals[groupId].delete(animalIndex);
                if (includedAnimals[groupId].size === 0) {
                    delete includedAnimals[groupId];
                }
            }
            $row.remove();
            updateDeleteButtonVisibility();
        });

        $form.on('submit', function (e) {
            e.preventDefault();
            let finalIncluded = {};
            for (const groupId in includedAnimals) {
                if (includedAnimals[groupId].size > 0) {
                    finalIncluded[groupId] = Array.from(includedAnimals[groupId]);
                }
            }

            const formData = {
                name: $('#name').val(),
                description: $('#description').val(),
                team_id: $('#team_id').val(),
                analyte_id: $('#analyte_id').val(),
                protocol_id: $('#protocol_id').val(),
                animal_model_id: $('#animal_model_id').val(),
                min_age: $('#min_age').val(),
                max_age: $('#max_age').val(),
                included_animals: finalIncluded,
                is_globally_shared: $isGloballySharedCheckbox.is(':checked'),
                shared_with_team_ids: $sharedWithTeamsSelect.val() || []
            };

            $.ajax({
                url: config.urls.submit,
                type: 'POST',
                contentType: 'application/json',
                data: JSON.stringify(formData),
                headers: { 'X-CSRFToken': $('input[name="csrf_token"]').val() },
                success: function (data) {
                    if (data.success) {
                        window.location.href = data.redirect_url;
                    } else {
                        alert(`${config.translations.error}: ${data.message}`);
                    }
                },
                error: function () {
                    alert(config.translations.unexpectedError);
                }
            });
        });

        function initializePage() {
            if (isEditing) {
                $('#name').val(existingData.name || '');
                $('#description').val(existingData.description || '');
                $('#team_id').val(existingData.team_id).trigger('change.select2');
                $('#min_age').val(existingData.min_age || '');
                $('#max_age').val(existingData.max_age || '');

                if (existingData.analyte_id && existingData.analyte_name) {
                    // Create a new option for the analyte
                    var analyteOption = new Option(existingData.analyte_name, existingData.analyte_id, true, true);
                    // Append it to the select
                    $('#analyte_id').append(analyteOption).trigger('change');
                }

                if (existingData.included_animals) {
                    includedAnimals = {};
                    for (const groupId in existingData.included_animals) {
                        includedAnimals[groupId] = new Set(existingData.included_animals[groupId]);
                    }
                }

                $isGloballySharedCheckbox.prop('checked', existingData.is_globally_shared);
                if (existingData.shared_with_team_ids) {
                    $sharedWithTeamsSelect.val(existingData.shared_with_team_ids).trigger('change.select2');
                }
                toggleSharedWithTeams();
            }
        }

        initializePage();

        // Fetch and render charts for this reference range if editing
        if (document.getElementById('range-scatter-plot') && config.rangeId) {
            fetch(`${config.urls.rangeData}/${config.rangeId}/data`)
                .then(response => response.json())
                .then(data => {
                    // Enhanced scatter plot with legends showing animal/group info
                    const scatterData = [];
                    const groupedByGroup = {};
                    
                    // Group data points by group name for legend
                    data.scatter_data.forEach((point, index) => {
                        const key = point.group || `Group ${index}`; // Use actual group name
                        if (!groupedByGroup[key]) {
                            groupedByGroup[key] = { x: [], y: [], name: key, text: [] };
                        }
                        groupedByGroup[key].x.push(point.x);
                        groupedByGroup[key].y.push(point.y);
                        groupedByGroup[key].text.push(point.animal_id || 'Unknown');
                    });
                    
                    // Convert to plotly traces
                    Object.values(groupedByGroup).forEach(group => {
                        scatterData.push({
                            x: group.x,
                            y: group.y,
                            text: group.text,
                            name: group.name,
                            mode: 'markers',
                            type: 'scatter',
                            hovertemplate: '<b>%{text}</b><br>Value: %{y}<extra></extra>'
                        });
                    });
                    
                    Plotly.newPlot('range-scatter-plot', scatterData, { 
                        title: 'Scatter Plot', 
                        xaxis: { title: 'Index' }, 
                        yaxis: { title: 'Value' },
                        showlegend: true
                    });

                    // Timeline
                    const timelineTrace = {
                        x: data.timeline_data.map(d => d.date),
                        y: data.timeline_data.map(d => d.value),
                        mode: 'lines+markers',
                        type: 'scatter'
                    };
                    Plotly.newPlot('range-timeline-plot', [timelineTrace], { title: 'Timeline Evolution', xaxis: { title: 'Date' }, yaxis: { title: 'Value' } });
                })
                .catch(error => console.error('Error fetching range data:', error));
        }
    });
})();

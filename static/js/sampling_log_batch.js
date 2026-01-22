/**
 * sampling_log_batch.js
 * Handles the multi-stage wizard for logging batch samples.
 */

document.addEventListener('DOMContentLoaded', function() {
    // 1. Load Configuration
    const configEl = document.getElementById('sampling-wizard-config');
    if (!configEl) return;
    const CONFIG = JSON.parse(configEl.textContent);

    // --- Data from Configuration ---
    const storageLocationsData = CONFIG.storageLocations;
    const organChoicesData = CONFIG.organChoices;
    const tissueConditionsChoicesData = CONFIG.tissueConditions;
    const sampleTypeEnumData = CONFIG.sampleTypes;
    const anticoagulantChoicesData = CONFIG.anticoagulants;
    const animalModelFields = CONFIG.animalModelFields;
    const csrfToken = CONFIG.csrfToken;
    const getAvailableAnimalsUrl = CONFIG.urls.getAvailableAnimals;
    const langJS = CONFIG.i18n;

    // --- State Management ---
    let appState = {
        currentStage: 'stage1_select_animals',
        commonDetails: {},
        selectedAnimalIndices: [],
        sampleSet: []
    };

    // --- DOM Elements ---
    const stages = {
        stage1: document.getElementById('stage1_select_animals'),
        stage2: document.getElementById('stage2_define_sample_set'),
        stage3: document.getElementById('stage3_assign_and_log')
    };
    const collectionDateInput = document.getElementById('common_collection_date');
    const animalListTableBodyS1 = document.getElementById('animalListTableBodyS1');
    const sampleSetContainer = document.getElementById('sampleSetDefinitionContainer');
    const animalAssignmentTableBodyS3 = document.getElementById('animalAssignmentTableBodyS3');
    const masterCheckboxS1 = document.getElementById('masterAnimalCheckboxS1');
    const masterCheckboxS3 = document.getElementById('masterAnimalCheckboxS3');

    // --- Helper Functions ---
    function showStage(stageId) {
        appState.currentStage = stageId;
        Object.values(stages).forEach(stageEl => stageEl.classList.remove('active'));
        stages[stageId].classList.add('active');
    }

    function populateSelect(selectEl, choices, placeholder, allowClear = false) {
        $(selectEl).empty();
        if (placeholder && !selectEl.multiple) {
            $(selectEl).append(new Option(placeholder, '', true, true));
        }
        // Handle both array of objects {id, text} and array of arrays [id, text]
        choices.forEach(choice => {
            const id = choice.id !== undefined ? choice.id : choice[0];
            const text = choice.text !== undefined ? choice.text : choice[1];
            $(selectEl).append(new Option(text, id));
        });
        $(selectEl).select2({ theme: "bootstrap-5", placeholder, allowClear, width: '100%' });
    }

    // --- Stage 1 Logic ---
    function fetchAndRenderAvailableAnimals() {
        const collectionDate = collectionDateInput.value;
        if (!collectionDate) return;
        
        // Use the URL from config
        fetch(`${getAvailableAnimalsUrl}?date=${collectionDate}`)
            .then(response => response.json())
            .then(data => {
                animalListTableBodyS1.innerHTML = '';
                if (data.success) {
                    data.animals.forEach(animal => {
                        const row = animalListTableBodyS1.insertRow();
                        let cell = row.insertCell();
                        cell.innerHTML = `<input type="checkbox" name="selected_animal_indices[]" value="${animal.index}" class="animal-select-checkbox-s1">`;
                        animalModelFields.forEach(fieldName => {
                            cell = row.insertCell();
                            cell.textContent = animal[fieldName] || 'N/A';
                        });
                    });
                }
            });
    }
    
    if (collectionDateInput) {
        collectionDateInput.addEventListener('change', fetchAndRenderAvailableAnimals);
        fetchAndRenderAvailableAnimals(); // Initial load
    }

    const goToStage2Btn = document.getElementById('goToStage2DefineSamplesBtn');
    if (goToStage2Btn) {
        goToStage2Btn.addEventListener('click', () => {
            const form = document.querySelector('#stage1_select_animals form') || document.getElementById('logBatchSamplesForm');
            if (!form.checkValidity()) {
                form.reportValidity();
                return;
            }
            appState.commonDetails = {
                collection_date: document.getElementById('common_collection_date').value,
                is_terminal_event: document.getElementById('common_is_terminal_event').checked,
                default_storage_id: document.getElementById('common_default_storage_id_s1').value,
                status: document.getElementById('common_status').value,
                event_notes: document.getElementById('common_event_notes').value
            };
            appState.selectedAnimalIndices = Array.from(document.querySelectorAll('.animal-select-checkbox-s1:checked')).map(cb => parseInt(cb.value));
            if (appState.selectedAnimalIndices.length === 0) {
                alert(langJS.selectAtLeastOne);
                return;
            }
            updateStage2Summary();
            showStage('stage2');
        });
    }

    if (masterCheckboxS1) {
        masterCheckboxS1.addEventListener('change', function() {
            const animalCheckboxesS1 = document.querySelectorAll('#animalListTableBodyS1 .animal-select-checkbox-s1');
            animalCheckboxesS1.forEach(cb => {
                cb.checked = this.checked;
            });
        });
    }

    // --- Stage 2 Logic ---
    function updateStage2Summary() {
        document.getElementById('s2_event_date_display').textContent = appState.commonDetails.collection_date;
        document.getElementById('s2_event_terminal_display').textContent = appState.commonDetails.is_terminal_event ? langJS.yesLabel : langJS.noLabel;
        const storage = storageLocationsData.find(s => s.id == appState.commonDetails.default_storage_id);
        document.getElementById('s2_event_storage_display').textContent = storage ? storage.text : langJS.noneLabel;
        document.getElementById('s2_event_notes_display').textContent = appState.commonDetails.event_notes || langJS.noneLabel;
    }

    const addSampleBtn = document.getElementById('addSampleToSetBtn');
    if (addSampleBtn) addSampleBtn.addEventListener('click', addSampleDefinitionEntryToSet);
    
    const backToStage1Btn = document.getElementById('backToStage1SelectAnimalsBtn');
    if (backToStage1Btn) backToStage1Btn.addEventListener('click', () => showStage('stage1'));
    
    const goToStage3Btn = document.getElementById('goToStage3AssignBtn');
    if (goToStage3Btn) goToStage3Btn.addEventListener('click', () => {
        if (collectDefinedSampleSet()) {
            updateStage3Summary();
            populateStage3AnimalAssignmentTable();
            showStage('stage3');
        }
    });

    function addSampleDefinitionEntryToSet() {
        const template = document.getElementById('sample-definition-template');
        const clone = template.content.cloneNode(true);
        const entryDiv = clone.querySelector('.sample-definition-entry');
        
        // Convert object to array for select2
        const sampleTypesArray = Object.entries(sampleTypeEnumData).map(([k,v]) => ({id: k, text: v}));
        
        populateSelect(entryDiv.querySelector('.dynamic-sample-type-select-def'), sampleTypesArray, langJS.selectType);
        populateSelect(entryDiv.querySelector('.dynamic-storage-override-select-def'), storageLocationsData, langJS.useEventDefault, true);
        populateSelect(entryDiv.querySelector('.dynamic-anticoagulant-select-def'), anticoagulantChoicesData, "--", true);

        entryDiv.querySelector('.remove-sample-def-btn').addEventListener('click', () => entryDiv.remove());
        entryDiv.querySelector('.add-organ-to-tissue-def-btn').addEventListener('click', (e) => addTissueOrganEntryToDef(e.target.previousElementSibling));
        $(entryDiv.querySelector('.dynamic-sample-type-select-def')).on('change', () => toggleSampleDefDetails(entryDiv));
        
        sampleSetContainer.appendChild(entryDiv);
        toggleSampleDefDetails(entryDiv);
    }

    function addTissueOrganEntryToDef(container) {
        const template = document.getElementById('tissue-organ-entry-template');
        const clone = template.content.cloneNode(true);
        const organRow = clone.querySelector('.tissue-organ-entry-row-def');
        
        populateSelect(organRow.querySelector('.dynamic-organ-select-def'), organChoicesData, langJS.selectOrgan);
        populateSelect(organRow.querySelector('.dynamic-tissue-conditions-def-select'), tissueConditionsChoicesData, langJS.selectConditions, false);
        populateSelect(organRow.querySelector('.dynamic-organ-storage-def-select'), storageLocationsData, langJS.useEventDefault, true);

        organRow.querySelector('.remove-organ-row-btn-def').addEventListener('click', () => organRow.remove());
        container.appendChild(organRow);
        $(organRow.querySelectorAll('select')).select2({ theme: "bootstrap-5", width: '100%', allowClear: true });
    }

    function toggleSampleDefDetails(entryDiv) {
        const selectedType = entryDiv.querySelector('.dynamic-sample-type-select-def').value;
        entryDiv.querySelectorAll('.sample-type-details-entry-def').forEach(el => {
            const typeDef = el.dataset.sampleTypeDetailDef;
            if (typeDef === selectedType || (typeDef === 'NOT_BIOLOGICAL_TISSUE' && selectedType !== 'BIOLOGICAL_TISSUE')) {
                el.style.display = 'block';
            } else {
                el.style.display = 'none';
            }
        });
    }

    function collectDefinedSampleSet() {
        appState.sampleSet = [];
        let isValid = true;
        const entries = document.querySelectorAll('#sampleSetDefinitionContainer .sample-definition-entry');
        
        if (entries.length === 0) {
            alert(langJS.noSampleSetDefined);
            return false;
        }

        entries.forEach(entry => {
            if (!isValid) return;
            const sampleData = {};
            sampleData.sample_type = entry.querySelector('[name="sample_type_def"]').value;
            if (!sampleData.sample_type) {
                alert(langJS.selectType);
                isValid = false;
                return;
            }
            sampleData.storage_id_override = entry.querySelector('[name="storage_id_override_def"]')?.value || null;
            sampleData.specific_notes = entry.querySelector('[name="specific_notes_def"]')?.value || null;

            if (sampleData.sample_type === "BIOLOGICAL_TISSUE") {
                sampleData.tissue_details_json = [];
                entry.querySelectorAll('.tissue-organ-entry-row-def').forEach(organRow => {
                    sampleData.tissue_details_json.push({
                        organ_id: organRow.querySelector('[name="organ_id_def"]').value,
                        piece_id: organRow.querySelector('[name="piece_id_def"]').value,
                        condition_ids: $(organRow.querySelector('[name="condition_ids_def"]')).val(),
                        storage_id: organRow.querySelector('[name="storage_id_def"]').value,
                        notes: organRow.querySelector('[name="notes_def"]').value
                    });
                });
            } else if (sampleData.sample_type === "BLOOD") {
                sampleData.anticoagulant_id = entry.querySelector('[name="anticoagulant_id_def"]').value;
                sampleData.blood_volume = entry.querySelector('[name="blood_volume_def"]').value;
                sampleData.blood_volume_unit = entry.querySelector('[name="blood_volume_unit_def"]').value;
            } else if (sampleData.sample_type === "URINE") {
                sampleData.urine_volume = entry.querySelector('[name="urine_volume_def"]').value;
                sampleData.urine_volume_unit = entry.querySelector('[name="urine_volume_unit_def"]').value;
            } else if (sampleData.sample_type === "OTHER") {
                sampleData.other_description = entry.querySelector('[name="other_description_def"]').value;
            }
            appState.sampleSet.push(sampleData);
        });
        return isValid;
    }

    // --- Stage 3 Logic ---
    function updateStage3Summary() {
        document.getElementById('s3_event_date_display').textContent = appState.commonDetails.collection_date;
        document.getElementById('s3_event_terminal_display').textContent = appState.commonDetails.is_terminal_event ? langJS.yesLabel : langJS.noLabel;
        const storage = storageLocationsData.find(s => s.id == appState.commonDetails.default_storage_id);
        document.getElementById('s3_event_storage_display').textContent = storage ? storage.text : langJS.noneLabel;
        document.getElementById('s3_event_notes_display').textContent = appState.commonDetails.event_notes || langJS.noneLabel;

        const summaryContainer = document.getElementById('definedSampleSetSummaryForStage3');
        summaryContainer.innerHTML = '';
        if (appState.sampleSet.length === 0) {
            summaryContainer.innerHTML = `<p class="text-muted">${langJS.noSampleSetDefined}</p>`;
            return;
        }

        const ul = document.createElement('ul');
        ul.className = 'list-unstyled';
        appState.sampleSet.forEach(sampleDef => {
            const li = document.createElement('li');
            li.className = 'mb-2';

            let details = '';
            const sampleTypeValue = sampleTypeEnumData[sampleDef.sample_type] || sampleDef.sample_type;

            if (sampleDef.sample_type === 'BLOOD') {
                const anticoagulantChoice = anticoagulantChoicesData.find(ac => ac[0] == sampleDef.anticoagulant_id);
                const anticoagulantName = anticoagulantChoice ? anticoagulantChoice[1] : 'N/A';
                details = `<small class="text-muted ms-2">(${langJS.anticoagulantLabel}: ${anticoagulantName}, ${langJS.volumeLabel}: ${sampleDef.blood_volume || 'N/A'} ${sampleDef.blood_volume_unit || 'µL'})</small>`;
            } else if (sampleDef.sample_type === 'URINE') {
                details = `<small class="text-muted ms-2">(${langJS.volumeLabel}: ${sampleDef.urine_volume || 'N/A'} ${sampleDef.urine_volume_unit || 'µL'})</small>`;
            } else if (sampleDef.sample_type === 'BIOLOGICAL_TISSUE' && sampleDef.tissue_details_json) {
                const organDetailsHtml = sampleDef.tissue_details_json.map(t => {
                    const organChoice = organChoicesData.find(oc => oc[0] == t.organ_id);
                    const organName = organChoice ? organChoice[1] : `ID ${t.organ_id}`;
                    const conditionNames = t.condition_ids.map(cid => {
                        const condChoice = tissueConditionsChoicesData.find(tc => tc[0] == cid);
                        return condChoice ? condChoice[1] : `ID ${cid}`;
                    }).join(', ');
                    return `<li class="small ps-3">• <strong>${organName}</strong> ${t.piece_id ? `(${t.piece_id})` : ''} - <span class="text-muted">${conditionNames}</span></li>`;
                }).join('');
                details = `<ul class="list-unstyled mb-0">${organDetailsHtml}</ul>`;
            } else if (sampleDef.sample_type === 'OTHER') {
                details = `<small class="text-muted ms-2">(${langJS.descriptionLabel}: ${sampleDef.other_description || 'N/A'})</small>`;
            }

            li.innerHTML = `<strong>${sampleTypeValue}</strong> ${details}`;
            ul.appendChild(li);
        });
        summaryContainer.appendChild(ul);
    }

    function populateStage3AnimalAssignmentTable() {
        animalAssignmentTableBodyS3.innerHTML = '';
        // We need the full animal data here. It was passed in the config.
        const allAnimalData = CONFIG.allAnimalData;
        
        appState.selectedAnimalIndices.forEach(index => {
            const animal = allAnimalData[index];
            const row = animalAssignmentTableBodyS3.insertRow();
            let cell = row.insertCell();
            cell.innerHTML = `<input type="checkbox" name="confirmed_animal_indices_for_set[]" value="${index}" class="animal-assign-checkbox-s3" checked>`;
            animalModelFields.forEach(fieldName => {
                cell = row.insertCell();
                cell.textContent = animal[fieldName] || 'N/A';
            });
        });
    }

    document.getElementById('backToStage2DefineSampleSetBtn').addEventListener('click', () => showStage('stage2'));
    
    document.getElementById('logFinalSamplesBtn').addEventListener('click', () => {
        const confirmedAnimalIndices = Array.from(document.querySelectorAll('.animal-assign-checkbox-s3:checked')).map(cb => parseInt(cb.value));
        if (confirmedAnimalIndices.length === 0) {
            alert(langJS.selectAtLeastOne);
            return;
        }
        
        const finalPayload = {
            common_details: appState.commonDetails,
            sample_set: appState.sampleSet,
            animal_indices: confirmedAnimalIndices
        };

        fetch(CONFIG.urls.logBatchSamples, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify(finalPayload)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                window.location.href = data.redirect_url;
            } else {
                alert("Error: " + (data.message || (data.errors ? data.errors.join('\n') : 'Unknown error')));
            }
        });
    });

    if (masterCheckboxS3) {
        masterCheckboxS3.addEventListener('change', function() {
            const animalCheckboxesS3 = document.querySelectorAll('#animalAssignmentTableBodyS3 .animal-assign-checkbox-s3');
            animalCheckboxesS3.forEach(cb => {
                cb.checked = this.checked;
            });
        });
    }

    // Initialize Select2 for the common storage dropdown
    $('#common_default_storage_id_s1').select2({ theme: "bootstrap-5", placeholder: langJS.selectDefaultStorage, allowClear: true, width: '100%' });
});
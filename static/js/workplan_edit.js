document.addEventListener('DOMContentLoaded', function () {

    // --- Configuration & Data ---
    const CONFIG = {
        // Assuming events_json is a string. If it's a list, remove JSON.parse
        events: JSON.parse(events_json),
        protocols: JSON.parse(protocols_json),
        teamMembers: JSON.parse(team_members_json),
        animalModels: JSON.parse(animal_models_json),
        currentLocale: current_locale,
        urls: {
            viewCalendar: view_calendar_url,
            finalize: finalize_url,
            getFinalizeInfo: get_finalize_info_url,
            restore: restore_url,
            bulkAssign: bulk_assign_url,
            history: history_url,
            reassignDatatable: reassign_datatable_url,
            moveDatatable: move_datatable_url
        },
        i18n: {
            selectProtocol: select_protocol_text,
            unassigned: unassigned_text,
            beforeDob: before_dob_text,
            invalidDate: invalid_date_text,
            viewOnCal: view_on_cal_text,
            noChanges: no_changes_text,
            requiredFields: required_fields_text,
            saving: saving_text
        }
    };

    // --- DOM Elements ---
    const els = {
        tbody: document.getElementById('workplan-events-tbody'),
        template: document.getElementById('event-row-template'),
        startDate: document.getElementById('study_start_date'),
        dob: document.getElementById('expected_dob'),
        btns: {
            addEvent: document.getElementById('add-event-btn'),
            save: document.getElementById('save-workplan-btn'),
            bulkAdd: document.getElementById('bulk-add-btn'),
            bulkAssign: document.getElementById('bulk-assign-btn'),
            finalize: document.getElementById('finalize-plan-btn'),
            clearAll: document.getElementById('clear-all-events-btn'),
            confirmClearEvents: document.getElementById('confirm-clear-events-btn'),
            confirmSave: document.getElementById('confirm-save-btn'),
            confirmFinalize: document.getElementById('confirm-finalize-btn'),
            confirmBulkAdd: document.getElementById('confirm-bulk-add-btn')
        }
    };

    let initialDataState = {};

    // --- Helper Functions ---
    function getISOWeek(date) {
        if (!(date instanceof Date) || isNaN(date)) return '';
        const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
        d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
        const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
        return Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
    }

    function initializeSelect2(element, data, placeholder, allowClear = true) {
        $(element).select2({
            theme: "bootstrap-5",
            placeholder: placeholder,
            allowClear: allowClear,
            data: data.map(item => ({ id: item.id, text: item.name || item.email }))
        });
    }

    function updateRowCalculation(row) {
        const offsetInput = row.querySelector('input[name="offset_days"]');
        const dateCell = row.querySelector('.projected-date');
        const weekCell = row.querySelector('.week-number');
        const ageCell = row.querySelector('.animal-age');

        dateCell.innerHTML = '';
        weekCell.textContent = '';
        ageCell.textContent = '';
        row.classList.remove('weekend-row');

        const startDateStr = els.startDate.value;
        const offsetVal = offsetInput.value;

        if (startDateStr && offsetVal !== '') {
            const offset = parseInt(offsetVal, 10);
            if (isNaN(offset)) return;

            const parts = startDateStr.split('-').map(p => parseInt(p, 10));
            const startDate = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
            const projectedDate = new Date(startDate.getTime() + offset * 86400000);

            const formatter = new Intl.DateTimeFormat(CONFIG.currentLocale, {
                weekday: 'short', year: 'numeric', month: '2-digit', day: '2-digit'
            });

            const formattedDate = formatter.format(projectedDate);
            const isoDate = projectedDate.toISOString().split('T')[0];

            dateCell.innerHTML = `<a href="${CONFIG.urls.viewCalendar}?date=${isoDate}" title="${CONFIG.i18n.viewOnCal}">${formattedDate}</a>`;
            weekCell.textContent = getISOWeek(projectedDate);

            const dayOfWeek = projectedDate.getUTCDay();
            if (dayOfWeek === 0 || dayOfWeek === 6) row.classList.add('weekend-row');

            if (els.dob.value) {
                const dobParts = els.dob.value.split('-').map(p => parseInt(p, 10));
                const dobDate = new Date(Date.UTC(dobParts[0], dobParts[1] - 1, dobParts[2]));
                const ageDays = Math.floor((projectedDate - dobDate) / 86400000);

                if (ageDays >= 0) {
                    ageCell.innerHTML = `${Math.floor(ageDays / 7)}w <small class="text-muted">(${ageDays}d)</small>`;
                } else {
                    ageCell.innerHTML = `<small class="text-danger">${CONFIG.i18n.beforeDob}</small>`;
                }
            }
        }
    }

    function sortTable() {
        if (!els.tbody) return;
        const rows = Array.from(els.tbody.querySelectorAll('tr'));
        rows.sort((a, b) => {
            const valA = parseInt(a.querySelector('input[name="offset_days"]').value, 10) || 0;
            const valB = parseInt(b.querySelector('input[name="offset_days"]').value, 10) || 0;
            return valA - valB;
        });
        rows.forEach(row => els.tbody.appendChild(row));
    }

    function addEventRow(event = {}) {
        const clone = els.template.content.cloneNode(true);
        const tr = clone.querySelector('tr');
        const offsetInput = tr.querySelector('input[name="offset_days"]');
        const protocolSelect = tr.querySelector('.protocol-select');
        const assigneeSelect = tr.querySelector('.assignee-select');

        offsetInput.value = (event.offset_days !== undefined && event.offset_days !== null) ? event.offset_days : '';
        tr.querySelector('input[name="event_name"]').value = event.event_name || '';

        initializeSelect2(protocolSelect, CONFIG.protocols, CONFIG.i18n.selectProtocol, false);
        initializeSelect2(assigneeSelect, CONFIG.teamMembers, CONFIG.i18n.unassigned, true);

        if (event.protocol_id) $(protocolSelect).val(event.protocol_id).trigger('change');
        if (event.assigned_to_id) $(assigneeSelect).val(event.assigned_to_id).trigger('change');

        updateRowCalculation(tr);
        els.tbody.appendChild(tr);

        if (els.btns.clearAll) els.btns.clearAll.disabled = false;
        if (els.btns.bulkAssign) els.btns.bulkAssign.disabled = false;
    }

    function getUIData() {
        const events = [];
        if (els.tbody) {
            els.tbody.querySelectorAll('tr').forEach(row => {
                const offVal = row.querySelector('input[name="offset_days"]').value;
                const protVal = $(row.querySelector('.protocol-select')).val();
                const assignVal = $(row.querySelector('.assignee-select')).val();

                events.push({
                    offset_days: offVal === "" ? null : parseInt(offVal, 10),
                    protocol_id: protVal ? parseInt(protVal, 10) : null,
                    event_name: row.querySelector('input[name="event_name"]').value || "",
                    assigned_to_id: assignVal ? parseInt(assignVal, 10) : null
                });
            });
            events.sort((a, b) => (a.offset_days || 0) - (b.offset_days || 0));
        }

        const countInput = document.getElementById('planned_animal_count');
        const noteInput = document.getElementById('workplan_notes');

        return {
            study_start_date: els.startDate.value || null,
            expected_dob: els.dob.value || null,
            notes: noteInput ? noteInput.value : "",
            planned_animal_count: countInput ? (countInput.value === "" ? null : parseInt(countInput.value, 10)) : null,
            events: events
        };
    }

    if (els.tbody) {
        CONFIG.events.forEach(addEventRow);
        sortTable();
        initialDataState = getUIData();

        els.tbody.addEventListener('click', function (e) {
            if (e.target.closest('.remove-event-btn')) {
                e.target.closest('tr').remove();
                if (els.tbody.children.length === 0) {
                    if (els.btns.clearAll) els.btns.clearAll.disabled = true;
                    if (els.btns.bulkAssign) els.btns.bulkAssign.disabled = true;
                }
            }
        });

        els.tbody.addEventListener('input', function (e) {
            if (e.target.name === 'offset_days') {
                updateRowCalculation(e.target.closest('tr'));
            }
        });

        els.tbody.addEventListener('change', function (e) {
            if (e.target.name === 'offset_days') {
                sortTable();
            }
        });

        const handleGlobalDateChange = () => {
            els.tbody.querySelectorAll('tr').forEach(updateRowCalculation);
            if (els.btns.finalize) {
                if (els.startDate.value && els.dob.value) {
                    els.btns.finalize.removeAttribute('disabled');
                    els.btns.finalize.removeAttribute('title');
                } else {
                    els.btns.finalize.setAttribute('disabled', 'true');
                }
            }
            const calBtn = document.getElementById('view-on-calendar-btn');
            if (els.startDate.value) {
                calBtn.href = `${CONFIG.urls.viewCalendar}?date=${els.startDate.value}`;
                calBtn.removeAttribute('disabled');
            }
        };
        els.startDate.addEventListener('input', handleGlobalDateChange);
        els.dob.addEventListener('input', handleGlobalDateChange);

        els.btns.addEvent.addEventListener('click', () => addEventRow());

        els.btns.save.addEventListener('click', () => {
            const currentData = getUIData();
            if (JSON.stringify(initialDataState) === JSON.stringify(currentData)) {
                alert(CONFIG.i18n.noChanges);
            } else {
                new bootstrap.Modal(document.getElementById('saveChangesModal')).show();
            }
        });

        els.btns.confirmClearEvents.addEventListener('click', function () {
            const btn = this;
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Clearing...';

            els.tbody.querySelectorAll('tr').forEach(row => row.remove());

            const payload = {
                ...getUIData(),
                change_comment: document.getElementById('clear_events_comment').value || 'Cleared all events',
                notify_team: document.getElementById('clear_events_notify_team').checked
            };

            fetch(window.location.pathname, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf_token },
                body: JSON.stringify(payload)
            }).then(r => r.json()).then(data => {
                if (data.success) {
                    window.location.reload();
                } else {
                    alert('Error: ' + data.message);
                    btn.disabled = false;
                    btn.innerHTML = 'Clear All Events';
                }
            });
        });

        els.btns.confirmSave.addEventListener('click', function () {
            const btn = this;
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Saving...';

            const payload = {
                ...getUIData(),
                change_comment: document.getElementById('change_comment').value,
                notify_team: document.getElementById('notify_team_checkbox').checked
            };

            if (payload.events.some(e => e.offset_days === null || !e.protocol_id)) {
                alert(CONFIG.i18n.requiredFields);
                btn.disabled = false;
                btn.textContent = 'Save';
                return;
            }

            fetch(window.location.pathname, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf_token },
                body: JSON.stringify(payload)
            }).then(r => r.json()).then(data => {
                if (data.success) window.location.reload();
                else { alert('Error: ' + data.message); btn.disabled = false; btn.textContent = 'Save'; }
            });
        });

        let bulkGeneratedEvents = [];
        els.btns.bulkAdd.addEventListener('click', () => {
            initializeSelect2(document.getElementById('bulk_protocol_id'), CONFIG.protocols, CONFIG.i18n.selectProtocol, false);
            new bootstrap.Modal(document.getElementById('bulkAddModal')).show();
        });

        document.querySelectorAll('input[name="repeat_unit"]').forEach(r => r.addEventListener('change', function () {
            document.getElementById('weekly_day_selection').style.display = (this.value === 'week') ? 'block' : 'none';
        }));
        document.querySelectorAll('input[name="end_condition"]').forEach(r => r.addEventListener('change', function () {
            document.getElementById('end_on_date_options').style.display = (this.value === 'on_date') ? 'block' : 'none';
            document.getElementById('end_after_occurrences_options').style.display = (this.value === 'after_occurrences') ? 'block' : 'none';
        }));

        document.getElementById('preview-bulk-events-btn').addEventListener('click', () => {
            const startStr = document.getElementById('bulk_start_date').value;
            const studyStartStr = els.startDate.value;
            if (!startStr || !studyStartStr) { alert("Please set study start date and bulk start date."); return; }

            const startDate = new Date(startStr);
            const studyStart = new Date(studyStartStr);
            const interval = parseInt(document.getElementById('repeat_interval').value) || 1;
            const unit = document.querySelector('input[name="repeat_unit"]:checked').value;
            const endCond = document.querySelector('input[name="end_condition"]:checked').value;
            const endDate = document.getElementById('end_date').value ? new Date(document.getElementById('end_date').value) : null;
            const maxOccurrences = parseInt(document.getElementById('num_occurrences').value) || 999;
            const skipWeekends = document.getElementById('skip_weekends').checked;

            let events = [];
            let count = 0;
            let safety = 0;
            const addMonths = (date, months) => {
                const d = new Date(date);
                const targetMonth = d.getMonth() + months;
                d.setMonth(targetMonth);
                if (d.getMonth() !== targetMonth % 12) d.setDate(0);
                return d;
            }

            if (unit === 'week') {
                const selectedDays = Array.from(document.querySelectorAll('input[name="bulk_days_of_week"]:checked')).map(c => parseInt(c.value));
                if (selectedDays.length === 0) { alert("Please select at least one day of the week."); return; }
                let currentWeekStart = new Date(startDate);
                currentWeekStart.setDate(currentWeekStart.getDate() - currentWeekStart.getDay());
                while (safety++ < 1000) {
                    for (let i = 0; i < 7; i++) {
                        let checkDate = new Date(currentWeekStart);
                        checkDate.setDate(currentWeekStart.getDate() + i);
                        if (checkDate < startDate) continue;
                        if (endCond === 'on_date' && checkDate > endDate) { safety = 9999; break; }
                        if (endCond === 'after_occurrences' && count >= maxOccurrences) { safety = 9999; break; }
                        const d = checkDate.getDay();
                        if (selectedDays.includes(d)) {
                            if (skipWeekends && (d === 0 || d === 6)) continue;
                            const offset = Math.floor((checkDate - studyStart) / 86400000);
                            if (offset >= 0) {
                                events.push({ offset_days: offset, date: new Date(checkDate) });
                                count++;
                            }
                        }
                    }
                    if (safety >= 9999) break;
                    currentWeekStart.setDate(currentWeekStart.getDate() + (interval * 7));
                    if (endCond === 'never' && events.length >= 365 * 5) break;
                }
            } else {
                let cursor = new Date(startDate);
                while (safety++ < 2000) {
                    if (endCond === 'on_date' && cursor > endDate) break;
                    if (endCond === 'after_occurrences' && count >= maxOccurrences) break;
                    const d = cursor.getDay();
                    let isValid = true;
                    if (skipWeekends && (d === 0 || d === 6)) isValid = false;
                    if (isValid) {
                        const offset = Math.floor((cursor - studyStart) / 86400000);
                        if (offset >= 0) {
                            events.push({ offset_days: offset, date: new Date(cursor) });
                            count++;
                        }
                    }
                    if (unit === 'day') cursor.setDate(cursor.getDate() + interval);
                    else if (unit === 'month') cursor = addMonths(cursor, interval);
                    if (endCond === 'never' && count >= 365) break;
                }
            }

            bulkGeneratedEvents = events;
            const tbody = document.getElementById('bulk_preview_tbody');
            tbody.innerHTML = '';
            if (events.length === 0) {
                tbody.innerHTML = '<tr><td colspan="3" class="text-center">No events generated.</td></tr>';
            } else {
                events.slice(0, 100).forEach(ev => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `<td>${ev.offset_days}</td><td>${getISOWeek(ev.date)}</td><td>(Auto)</td>`;
                    tbody.appendChild(tr);
                });
                if (events.length > 100) {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `<td colspan="3" class="text-center text-muted">...and ${events.length - 100} more...</td>`;
                    tbody.appendChild(tr);
                }
            }
            document.getElementById('preview-count-badge').textContent = events.length;
            document.getElementById('preview_event_count').textContent = events.length;
            document.getElementById('confirm-count').textContent = events.length;
            document.getElementById('bulk_preview_container').style.display = 'block';
            els.btns.confirmBulkAdd.disabled = events.length === 0;
        });

        els.btns.confirmBulkAdd.addEventListener('click', () => {
            const protId = document.getElementById('bulk_protocol_id').value;
            const nameTemplate = document.getElementById('enable_auto_naming').checked ? document.getElementById('event_name_template').value : null;
            bulkGeneratedEvents.forEach((ev, idx) => {
                let name = '';
                if (nameTemplate) {
                    name = nameTemplate.replace('{n}', idx + 1).replace('{day}', ev.offset_days).replace('{week}', Math.floor(ev.offset_days / 7) + 1);
                }
                addEventRow({ offset_days: ev.offset_days, protocol_id: protId, event_name: name });
            });
            sortTable();
            bootstrap.Modal.getInstance(document.getElementById('bulkAddModal')).hide();
        });
    }

    document.querySelectorAll('.datatable-assignee-select').forEach(select => {
        select.addEventListener('change', function () {
            const id = this.dataset.datatableId;
            const val = this.value;
            fetch(CONFIG.urls.reassignDatatable.replace('0', id), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf_token },
                body: JSON.stringify({ assignee_id: val })
            }).then(r => r.json()).then(d => {
                if (!d.success) { alert(d.message); }
            });
        });
    });

    document.querySelectorAll('.datatable-date-change').forEach(input => {
        input.addEventListener('change', function () {
            const id = this.dataset.datatableId;
            const val = this.value;
            fetch(CONFIG.urls.moveDatatable.replace('0', id), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf_token },
                body: JSON.stringify({ new_date: val })
            }).then(r => r.json()).then(d => {
                if (!d.success) { alert(d.message); }
            });
        });
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && e.target.closest('.workplan-table') && e.target.tagName === 'INPUT') {
            e.preventDefault();
        }
    });

    if (els.btns.finalize) {
        els.btns.finalize.addEventListener('click', async () => {
            const currentData = getUIData();
            if (JSON.stringify(initialDataState) !== JSON.stringify(currentData)) {
                try {
                    els.btns.finalize.disabled = true;
                    const originalContent = els.btns.finalize.innerHTML;
                    els.btns.finalize.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> ${CONFIG.i18n.saving}`;
                    if (currentData.events.some(e => e.offset_days === null || !e.protocol_id)) {
                        alert(CONFIG.i18n.requiredFields);
                        els.btns.finalize.disabled = false;
                        els.btns.finalize.innerHTML = originalContent;
                        return;
                    }
                    const response = await fetch(window.location.pathname, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf_token },
                        body: JSON.stringify({
                            ...currentData,
                            change_comment: 'Auto-save before finalization',
                            notify_team: false
                        })
                    });
                    const result = await response.json();
                    if (!result.success) {
                        alert('Error auto-saving changes: ' + result.message);
                        els.btns.finalize.disabled = false;
                        els.btns.finalize.innerHTML = originalContent;
                        return;
                    }
                    initialDataState = currentData;
                    els.btns.finalize.innerHTML = originalContent;
                    els.btns.finalize.disabled = false;
                } catch (err) {
                    console.error('Auto-save failed:', err);
                    alert('An error occurred while saving changes.');
                    els.btns.finalize.disabled = false;
                    return;
                }
            }

            const modal = new bootstrap.Modal(document.getElementById('finalizePlanModal'));
            const summary = document.getElementById('finalize-summary');
            const errors = document.getElementById('finalize-errors');
            summary.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Loading...';
            errors.style.display = 'none';

            fetch(CONFIG.urls.getFinalizeInfo).then(r => r.json()).then(data => {
                if (data.error) {
                    errors.textContent = data.error;
                    errors.style.display = 'block';
                    summary.innerHTML = '';
                    return;
                }
                summary.innerHTML = `Generates <strong>${data.event_count}</strong> datatables.`;
                const eaSelect = document.getElementById('finalize_ethical_approval_id');
                eaSelect.innerHTML = '';
                data.valid_eas.forEach(ea => eaSelect.add(new Option(ea.text, ea.id)));
                const gSelect = document.getElementById('existing_group_id');
                gSelect.innerHTML = '';
                if (data.existing_groups.length) {
                    data.existing_groups.forEach(g => gSelect.add(new Option(g.name, g.id)));
                    document.getElementById('link_existing_group_radio').disabled = false;
                } else {
                    gSelect.add(new Option("No groups available", ""));
                    document.getElementById('link_existing_group_radio').disabled = true;
                }
                const mSelect = document.getElementById('new_group_animal_model_id');
                mSelect.innerHTML = '';
                CONFIG.animalModels.forEach(m => mSelect.add(new Option(m.name, m.id)));
                modal.show();
            });
        });

        els.btns.confirmFinalize.addEventListener('click', function () {
            const action = document.querySelector('input[name="group_action"]:checked').value;
            const payload = {
                ea_id: document.getElementById('finalize_ethical_approval_id').value,
                notify_team: document.getElementById('finalize_notify_team').checked,
                group_action: action
            };
            if (action === 'create') {
                payload.group_name = document.getElementById('new_group_name').value;
                payload.animal_model_id = document.getElementById('new_group_animal_model_id').value;
            } else {
                payload.group_id = document.getElementById('existing_group_id').value;
            }
            fetch(CONFIG.urls.finalize, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf_token },
                body: JSON.stringify(payload)
            }).then(r => r.json()).then(data => {
                if (data.success) window.location.reload();
                else alert(data.message);
            });
        });

        document.querySelectorAll('input[name="group_action"]').forEach(el => el.addEventListener('change', function () {
            const isCreate = this.value === 'create';
            document.getElementById('new_group_section').style.display = isCreate ? 'block' : 'none';
            document.getElementById('existing_group_section').style.display = isCreate ? 'none' : 'block';
        }));
    }

    if (els.btns.bulkAssign) {
        const assignModal = document.getElementById('bulkAssignModal');
        assignModal.addEventListener('show.bs.modal', () => {
            initializeSelect2(document.getElementById('bulk_assign_protocols'), CONFIG.protocols, 'Select Protocols...', true);
            const userSelect = document.getElementById('bulk_assign_user');
            $(userSelect).empty();
            const data = [{ id: '', text: '-- Unassigned --' }, ...CONFIG.teamMembers.map(m => ({ id: m.id, text: m.email }))];
            $(userSelect).select2({ theme: "bootstrap-5", data: data });
        });

        document.getElementById('confirm-bulk-assign-btn').addEventListener('click', () => {
            const protocols = $(document.getElementById('bulk_assign_protocols')).val();
            const user = $(document.getElementById('bulk_assign_user')).val();
            fetch(CONFIG.urls.bulkAssign, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf_token },
                body: JSON.stringify({
                    protocol_ids: protocols,
                    assigned_to_id: user,
                    change_comment: document.getElementById('bulk_assign_comment').value,
                    notify_team: document.getElementById('bulk_assign_notify_team').checked
                })
            }).then(r => r.json()).then(d => {
                if (d.success) window.location.reload();
                else alert(d.message);
            });
        });
    }

    // --- History Modal Handling ---
    const historyModal = document.getElementById('historyModal');
    if (historyModal) {
        historyModal.addEventListener('show.bs.modal', function () {
            const versionList = document.getElementById('version-list');
            const versionDetails = document.getElementById('version-details-view');
            const restoreBtn = document.getElementById('restore-version-btn');

            versionList.innerHTML = '<div class="text-center"><span class="spinner-border spinner-border-sm"></span> Loading...</div>';
            versionDetails.innerHTML = '<div class="alert alert-info">Select a version to view its details.</div>';
            restoreBtn.disabled = true;

            fetch(CONFIG.urls.history)
                .then(r => r.json())
                .then(data => {
                    if (data.error) {
                        versionList.innerHTML = '<div class="alert alert-danger">Error loading history.</div>';
                        return;
                    }
                    versionList.innerHTML = '';
                    data.forEach(version => {
                        const btn = document.createElement('button');
                        btn.className = 'list-group-item list-group-item-action d-flex justify-content-between align-items-center';
                        btn.innerHTML = `
                            <div>
                                <strong>Version ${version.version_number}</strong><br>
                                <small class="text-muted">${version.created_at} by ${version.created_by}</small><br>
                                <small>${version.change_comment}</small>
                            </div>
                        `;
                        btn.addEventListener('click', () => {
                            // Remove active class from all
                            versionList.querySelectorAll('.list-group-item').forEach(item => item.classList.remove('active'));
                            btn.classList.add('active');

                            // Show details
                            const snapshot = version.snapshot;
                            let detailsHtml = `
                                <h6>Version ${version.version_number} - ${version.created_at}</h6>
                                <p><strong>Comment:</strong> ${version.change_comment}</p>
                                <p><strong>Created by:</strong> ${version.created_by}</p>
                                <hr>
                                <h6>Workplan Details:</h6>
                                <ul>
                                    <li><strong>Study Start Date:</strong> ${snapshot.study_start_date || 'Not set'}</li>
                                    <li><strong>Expected DOB:</strong> ${snapshot.expected_dob || 'Not set'}</li>
                                    <li><strong>Notes:</strong> ${snapshot.notes || 'None'}</li>
                                    <li><strong>Planned Animal Count:</strong> ${snapshot.planned_animal_count || 'Not set'}</li>
                                </ul>
                                <h6>Events (${snapshot.events.length}):</h6>
                            `;
                            if (snapshot.events.length > 0) {
                                detailsHtml += '<div class="table-responsive"><table class="table table-sm"><thead><tr><th>Day Offset</th><th>Protocol</th><th>Event Name</th><th>Assigned To</th></tr></thead><tbody>';
                                snapshot.events.forEach(event => {
                                    const protocol = CONFIG.protocols.find(p => p.id == event.protocol_id);
                                    const assignee = CONFIG.teamMembers.find(t => t.id == event.assigned_to_id);
                                    detailsHtml += `<tr><td>${event.offset_days}</td><td>${protocol ? protocol.name : 'N/A'}</td><td>${event.event_name || ''}</td><td>${assignee ? assignee.email : 'Unassigned'}</td></tr>`;
                                });
                                detailsHtml += '</tbody></table></div>';
                            } else {
                                detailsHtml += '<p>No events.</p>';
                            }
                            versionDetails.innerHTML = detailsHtml;
                            restoreBtn.disabled = false;
                            restoreBtn.onclick = () => restoreVersion(version.id);
                        });
                        versionList.appendChild(btn);
                    });
                })
                .catch(err => {
                    versionList.innerHTML = '<div class="alert alert-danger">Error loading history.</div>';
                    console.error(err);
                });
        });

        function restoreVersion(versionId) {
            const comment = prompt('Enter a comment for the restore:');
            if (!comment) return;

            const notify = document.getElementById('notify_team_on_restore').checked;
            fetch(CONFIG.urls.restore, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf_token },
                body: JSON.stringify({
                    version_id: versionId,
                    change_comment: comment,
                    notify_team: notify
                })
            }).then(r => r.json()).then(data => {
                if (data.success) {
                    window.location.reload();
                } else {
                    alert('Error: ' + data.message);
                }
            }).catch(err => {
                alert('Error restoring version.');
                console.error(err);
            });
        }
    }
});

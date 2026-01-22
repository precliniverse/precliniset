/**
 * calendar_view.js
 * Handles FullCalendar initialization and event interactions.
 */

document.addEventListener('DOMContentLoaded', function () {
    // 1. Load Configuration
    const configEl = document.getElementById('calendar-config');
    if (!configEl) return;
    const CONFIG = JSON.parse(configEl.textContent);

    var calendarEl = document.getElementById('calendar');
    const teamMembersCheckboxesDiv = document.getElementById('team-members-checkboxes');
    const filterSelectAllCheckbox = document.getElementById('filter-select-all');
    const filterUnassignedOnlyCheckbox = document.getElementById('filter-unassigned-only');

    let teamMembers = [];

    // Function to get the events URL based on selected assignees
    function getEventsUrl() {
        const baseUrl = CONFIG.urls.eventsJson;
        const params = new URLSearchParams();

        const selectedAssigneeIds = Array.from(document.querySelectorAll('.assignee-checkbox:checked'))
            .map(cb => cb.value);

        if (filterUnassignedOnlyCheckbox.checked) {
            params.append('include_unassigned', 'true');
        }

        if (selectedAssigneeIds.length > 0) {
            params.append('assigned_to_ids', selectedAssigneeIds.join(','));
        }

        return `${baseUrl}?${params.toString()}`;
    }

    var calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth',
        initialDate: CONFIG.initialDate || new Date(),
        weekNumbers: true,
        weekNumberCalculation: 'ISO',
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,listWeek'
        },
        eventSources: [
            {
                url: getEventsUrl(),
                color: '#007bff', // Blue for Precliniset events
                textColor: '#ffffff'
            },
            {
                url: CONFIG.urls.tmEvents,
                color: '#8B4513', // Brown for Training Manager events
                textColor: '#ffffff'
            }
        ],
        editable: true,
        height: 'auto',
        contentHeight: 'auto',
        aspectRatio: 1.8,
        eventDrop: function (info) {
            const eventId = info.event.id;
            const newStartDate = info.event.start;
            const oldStartDate = info.oldEvent.start;
            const deltaDays = Math.round((newStartDate - oldStartDate) / (1000 * 60 * 60 * 24));

            const isStandaloneDataTable = String(eventId).startsWith('dt-');

            if (isStandaloneDataTable) {
                // --- Handle Standalone DataTable Move ---
                const datatableId = eventId.substring(3);

                const year = newStartDate.getFullYear();
                const month = String(newStartDate.getMonth() + 1).padStart(2, '0');
                const day = String(newStartDate.getDate()).padStart(2, '0');
                const newDateStr = `${year}-${month}-${day}`;

                if (!confirm(CONFIG.i18n.confirmMoveDt.replace('%s', newDateStr))) {
                    info.revert();
                    return;
                }

                fetch(`/datatables/${datatableId}/move`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': CONFIG.csrfToken
                    },
                    body: JSON.stringify({ 'new_date': newDateStr })
                })
                    .then(response => response.json())
                    .then(data => {
                        if (!data.success) {
                            alert(CONFIG.i18n.errorUpdateDt + ' ' + data.message);
                            info.revert();
                        }
                        calendar.refetchEvents();
                    })
                    .catch(error => {
                        console.error('Error:', error);
                        alert(CONFIG.i18n.unexpectedError);
                        info.revert();
                    });

            } else {
                // --- Handle Workplan Event Move ---
                const modalEl = document.getElementById('eventMoveModal');
                const modal = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);
                const modalInfo = document.getElementById('eventMoveInfo');
                const confirmBtn = document.getElementById('confirmMoveBtn');
                const cancelBtn = document.getElementById('cancelMoveBtn');
                const commentInput = document.getElementById('eventMoveComment');
                const notifyCheckbox = document.getElementById('notifyTeamCheckboxCalendar');

                let ageHtml = '';
                const expectedDobStr = info.event.extendedProps.expected_dob;
                if (expectedDobStr) {
                    try {
                        const dobDate = new Date(expectedDobStr + 'T00:00:00Z');
                        const newDate = new Date(newStartDate.getTime());
                        const ageInMillis = newDate.getTime() - dobDate.getTime();
                        const ageInDays = Math.floor(ageInMillis / (1000 * 60 * 60 * 24));
                        if (ageInDays >= 0) {
                            const ageInWeeks = Math.floor(ageInDays / 7);
                            ageHtml = `<br><strong class="text-info">${CONFIG.i18n.projectedAge}: ${ageInWeeks}w (${ageInDays}d)</strong>`;
                        }
                    } catch (e) { console.error("Error parsing DOB for age calculation:", e); }
                }

                // Safe HTML injection for modal info
                modalInfo.innerHTML = CONFIG.i18n.moveEventMsg
                    .replace('{title}', info.event.title)
                    .replace('{days}', deltaDays) + ageHtml;

                commentInput.value = `Event '${info.event.title}' moved by ${deltaDays} day(s) via calendar drag-and-drop.`;

                // Clone buttons to remove old listeners
                const newConfirmBtn = confirmBtn.cloneNode(true);
                confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);

                const newCancelBtn = cancelBtn.cloneNode(true);
                cancelBtn.parentNode.replaceChild(newCancelBtn, cancelBtn);

                newConfirmBtn.disabled = false;
                newConfirmBtn.innerHTML = CONFIG.i18n.confirm;

                newConfirmBtn.addEventListener('click', function () {
                    newConfirmBtn.disabled = true;
                    newConfirmBtn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>`;

                    fetch(`/workplans/events/${eventId}/move`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': CONFIG.csrfToken
                        },
                        body: JSON.stringify({
                            'delta_days': deltaDays,
                            'change_comment': commentInput.value,
                            'notify_team': notifyCheckbox.checked
                        })
                    })
                        .then(response => response.json())
                        .then(data => {
                            if (!data.success) {
                                alert('Error updating event: ' + data.message);
                                info.revert();
                            }
                            calendar.refetchEvents();
                        })
                        .catch(error => {
                            console.error('Error:', error);
                            alert(CONFIG.i18n.unexpectedError);
                            info.revert();
                        })
                        .finally(() => {
                            modal.hide();
                        });
                });

                newCancelBtn.addEventListener('click', function () {
                    info.revert();
                    modal.hide();
                });

                modal.show();
            }
        },
        eventClick: function (info) {
            info.jsEvent.preventDefault();
            if (info.event.url) {
                window.location.href = info.event.url;
            }
        },
        dayCellDidMount: function (arg) {
            if (arg.isWeekend) {
                arg.el.classList.add('fc-day-weekend');
            }
        },
        eventDidMount: function (info) {
            const props = info.event.extendedProps;
            const content = `
                <strong>${props.project_name}</strong><br>
                <em>${props.workplan_name}</em><br>
                Group: ${props.group_name}<br>
                Event: ${props.event_name || info.event.title}<br>
                Week: ${props.week_number}<br>
                Status: ${props.status}<br>
                Assignee: ${props.assignee}
            `;
            tippy(info.el, { content: content, allowHTML: true, placement: 'auto' });

            if (props.status === 'Draft') {
                info.el.classList.add('draft-event');
            }
            if (info.event.classNames.includes('unassigned-event')) {
                info.el.style.backgroundColor = '#dc3545';
                info.el.style.borderColor = '#dc3545';
            }
        }
    });

    calendar.render();

    // Fetch team members
    fetch(CONFIG.urls.teamMembersJson)
        .then(response => response.json())
        .then(data => {
            teamMembers = data;
            const currentUserId = CONFIG.currentUserId;

            teamMembers.forEach(member => {
                const div = document.createElement('div');
                div.className = 'form-check';
                div.innerHTML = `
                    <input class="form-check-input assignee-checkbox" type="checkbox" id="assignee-${member.id}" value="${member.id}">
                    <label class="form-check-label" for="assignee-${member.id}">
                        ${member.name}
                    </label>
                `;
                teamMembersCheckboxesDiv.appendChild(div);

                if (member.id === currentUserId) {
                    div.querySelector('.assignee-checkbox').checked = true;
                }
            });

            const updateFiltersAndRefetch = () => {
                if (filterSelectAllCheckbox.checked) {
                    filterUnassignedOnlyCheckbox.checked = false;
                }
                if (filterUnassignedOnlyCheckbox.checked) {
                    filterSelectAllCheckbox.checked = false;
                    document.querySelectorAll('.assignee-checkbox').forEach(cb => cb.checked = false);
                } else {
                    const anyAssigneeSelected = Array.from(document.querySelectorAll('.assignee-checkbox:checked')).length > 0;
                    if (!anyAssigneeSelected && !filterSelectAllCheckbox.checked) {
                        const currentUserCheckbox = document.getElementById(`assignee-${currentUserId}`);
                        if (currentUserCheckbox) currentUserCheckbox.checked = true;
                    }
                }
                calendar.setOption('events', getEventsUrl());
            };

            updateFiltersAndRefetch();

            document.querySelectorAll('.assignee-checkbox').forEach(checkbox => {
                checkbox.addEventListener('change', function () {
                    filterSelectAllCheckbox.checked = false;
                    filterUnassignedOnlyCheckbox.checked = false;
                    updateFiltersAndRefetch();
                });
            });

            filterSelectAllCheckbox.addEventListener('change', function () {
                const isChecked = this.checked;
                document.querySelectorAll('.assignee-checkbox').forEach(cb => cb.checked = isChecked);
                updateFiltersAndRefetch();
            });

            filterUnassignedOnlyCheckbox.addEventListener('change', updateFiltersAndRefetch);
        })
        .catch(error => {
            console.error('Error fetching team members:', error);
        });
});

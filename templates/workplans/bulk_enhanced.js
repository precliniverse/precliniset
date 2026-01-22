// Enhanced Bulk Add Events - JavaScript Implementation
// This code should replace the existing bulk add event handlers in edit_workplan.html

// --- Bulk Add Modal: Pattern Type Switching ---
bulkAddBtn.addEventListener('click', () => {
    const bulkProtocolSelect = document.getElementById('bulk_protocol_id');
    initializeSelect2(bulkProtocolSelect, protocolsData, '{{ _("Select Protocol...") }}', false);
    bulkAddModal.show();
});

// Pattern type switching
document.querySelectorAll('input[name="pattern_type"]').forEach(radio => {
    radio.addEventListener('change', function() {
        document.querySelectorAll('.pattern-options').forEach(opt => opt.style.display = 'none');
        const selectedPattern = this.value;
        document.getElementById(selectedPattern + '_options').style.display = 'block';
    });
});

// Month pattern type switching
const monthPatternTypeSelect = document.getElementById('month_pattern_type');
if (monthPatternTypeSelect) {
    monthPatternTypeSelect.addEventListener('change', function() {
        if (this.value === 'nth_weekday') {
            document.getElementById('nth_weekday_options').style.display = 'block';
            document.getElementById('specific_day_options').style.display = 'none';
        } else {
            document.getElementById('nth_weekday_options').style.display = 'none';
            document.getElementById('specific_day_options').style.display = 'block';
        }
    });
}

// Filter toggles
document.getElementById('enable_month_filter').addEventListener('change', function() {
    document.getElementById('month_filter_options').style.display = this.checked ? 'block' : 'none';
});

document.getElementById('enable_week_filter').addEventListener('change', function() {
    document.getElementById('week_filter_options').style.display = this.checked ? 'block' : 'none';
});

document.getElementById('enable_auto_naming').addEventListener('change', function() {
    document.getElementById('auto_naming_options').style.display = this.checked ? 'block' : 'none';
});

// --- Pattern Generation Functions ---
function generateEveryNDays(startDay, endDay, interval) {
    const events = [];
    for (let day = startDay; day <= endDay; day += interval) {
        events.push(day);
    }
    return events;
}

function generateEveryNWeeks(startDay, endDay, weekInterval, weekdays, startDate) {
    const events = [];
    const parts = startDate.split('-').map(p => parseInt(p, 10));
    const baseDate = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    
    for (let day = startDay; day <= endDay; day++) {
        const currentDate = new Date(baseDate.getTime() + day * 24 * 60 * 60 * 1000);
        const dayOfWeek = currentDate.getUTCDay();
        const weekNum = Math.floor(day / 7);
        
        if (weekNum % weekInterval === 0 && weekdays.includes(dayOfWeek)) {
            events.push(day);
        }
    }
    return events;
}

function generateEveryNMonths(startDay, endDay, monthInterval, config, startDate) {
    const events = [];
    const parts = startDate.split('-').map(p => parseInt(p, 10));
    const baseDate = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    
    for (let day = startDay; day <= endDay; day++) {
        const currentDate = new Date(baseDate.getTime() + day * 24 * 60 * 60 * 1000);
        
        if (config.type === 'nth_weekday') {
            if (isNthWeekdayOfMonth(currentDate, config.occurrence, config.weekday)) {
                const monthsSinceStart = getMonthDifference(baseDate, currentDate);
                if (monthsSinceStart % monthInterval === 0) {
                    events.push(day);
                }
            }
        } else if (config.type === 'specific_day') {
            if (currentDate.getUTCDate() === config.dayNumber) {
                const monthsSinceStart = getMonthDifference(baseDate, currentDate);
                if (monthsSinceStart % monthInterval === 0) {
                    events.push(day);
                }
            }
        }
    }
    return events;
}

function generateSpecificDays(startDay, endDay, selectedDays, startDate) {
    const events = [];
    const parts = startDate.split('-').map(p => parseInt(p, 10));
    const baseDate = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    
    for (let day = startDay; day <= endDay; day++) {
        const currentDate = new Date(baseDate.getTime() + day * 24 * 60 * 60 * 1000);
        const dayOfWeek = currentDate.getUTCDay();
        
        if (selectedDays.includes(dayOfWeek)) {
            events.push(day);
        }
    }
    return events;
}

// Helper functions
function isNthWeekdayOfMonth(date, occurrence, weekday) {
    if (date.getUTCDay() !== weekday) return false;
    
    if (occurrence === 'last') {
        const nextWeek = new Date(date.getTime() + 7 * 24 * 60 * 60 * 1000);
        return nextWeek.getUTCMonth() !== date.getUTCMonth();
    } else {
        const dayOfMonth = date.getUTCDate();
        const nthOccurrence = Math.ceil(dayOfMonth / 7);
        return nthOccurrence === parseInt(occurrence);
    }
}

function getMonthDifference(date1, date2) {
    return (date2.getUTCFullYear() - date1.getUTCFullYear()) * 12 + 
           (date2.getUTCMonth() - date1.getUTCMonth());
}

// Filter functions
function applyMonthFilter(eventDays, allowedMonths, startDate) {
    const parts = startDate.split('-').map(p => parseInt(p, 10));
    const baseDate = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    
    return eventDays.filter(day => {
        const date = new Date(baseDate.getTime() + day * 24 * 60 * 60 * 1000);
        return allowedMonths.includes(date.getUTCMonth() + 1);
    });
}

function applyWeekFilter(eventDays, allowedWeeks) {
    return eventDays.filter(day => {
        const weekNum = Math.floor(day / 7) + 1;
        return allowedWeeks.includes(weekNum);
    });
}

function applyWeekendFilter(eventDays, startDate) {
    const parts = startDate.split('-').map(p => parseInt(p, 10));
    const baseDate = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    
    return eventDays.filter(day => {
        const date = new Date(baseDate.getTime() + day * 24 * 60 * 60 * 1000);
        const dayOfWeek = date.getUTCDay();
        return dayOfWeek !== 0 && dayOfWeek !== 6; // Not Sunday or Saturday
    });
}

function generateEventNames(eventDays, template, startDate) {
    const parts = startDate.split('-').map(p => parseInt(p, 10));
    const baseDate = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    
    return eventDays.map((day, index) => {
        let name = template;
        name = name.replace('{n}', index + 1);
        name = name.replace('{day}', day);
        name = name.replace('{week}', Math.floor(day / 7) + 1);
        
        const date = new Date(baseDate.getTime() + day * 24 * 60 * 60 * 1000);
        name = name.replace('{month}', date.getUTCMonth() + 1);
        
        return name;
    });
}

// Preview button handler
document.getElementById('preview-bulk-events-btn').addEventListener('click', function() {
    const startDateStr = startDateInput.value;
    if (!startDateStr) {
        alert('Please set a Study Start Date before previewing events.');
        return;
    }

    const startDay = parseInt(document.getElementById('bulk_start_day').value, 10);
    const endDay = parseInt(document.getElementById('bulk_end_day').value, 10);
    
    if (isNaN(startDay) || isNaN(endDay) || startDay > endDay) {
        alert('Please enter valid start and end days.');
        return;
    }

    // Generate base pattern
    const patternType = document.querySelector('input[name="pattern_type"]:checked').value;
    let eventDays = [];

    if (patternType === 'every_n_days') {
        const interval = parseInt(document.getElementById('interval_days').value, 10);
        eventDays = generateEveryNDays(startDay, endDay, interval);
    } else if (patternType === 'every_n_weeks') {
        const weekInterval = parseInt(document.getElementById('week_interval').value, 10);
        const weekdays = Array.from(document.querySelectorAll('input[name="week_days"]:checked'))
            .map(cb => parseInt(cb.value, 10));
        if (weekdays.length === 0) {
            alert('Please select at least one day of the week.');
            return;
        }
        eventDays = generateEveryNWeeks(startDay, endDay, weekInterval, weekdays, startDateStr);
    } else if (patternType === 'every_n_months') {
        const monthInterval = parseInt(document.getElementById('month_interval').value, 10);
        const monthPatternType = document.getElementById('month_pattern_type').value;
        const config = { type: monthPatternType };
        
        if (monthPatternType === 'nth_weekday') {
            config.occurrence = document.getElementById('month_occurrence').value;
            config.weekday = parseInt(document.getElementById('month_weekday').value, 10);
        } else {
            config.dayNumber = parseInt(document.getElementById('month_day_number').value, 10);
        }
        
        eventDays = generateEveryNMonths(startDay, endDay, monthInterval, config, startDateStr);
    } else if (patternType === 'specific_days') {
        const selectedDays = Array.from(document.querySelectorAll('input[name="specific_days"]:checked'))
            .map(cb => parseInt(cb.value, 10));
        if (selectedDays.length === 0) {
            alert('Please select at least one day of the week.');
            return;
        }
        eventDays = generateSpecificDays(startDay, endDay, selectedDays, startDateStr);
    }

    // Apply filters
    if (document.getElementById('enable_month_filter').checked) {
        const allowedMonths = Array.from(document.querySelectorAll('input[name="filter_months"]:checked'))
            .map(cb => parseInt(cb.value, 10));
        if (allowedMonths.length > 0) {
            eventDays = applyMonthFilter(eventDays, allowedMonths, startDateStr);
        }
    }

    if (document.getElementById('enable_week_filter').checked) {
        const weeksInput = document.getElementById('filter_weeks_input').value;
        if (weeksInput.trim()) {
            const allowedWeeks = weeksInput.split(',').map(w => parseInt(w.trim(), 10)).filter(w => !isNaN(w));
            if (allowedWeeks.length > 0) {
                eventDays = applyWeekFilter(eventDays, allowedWeeks);
            }
        }
    }

    if (document.getElementById('skip_weekends').checked) {
        eventDays = applyWeekendFilter(eventDays, startDateStr);
    }

    // Generate event names if enabled
    let eventNames = [];
    if (document.getElementById('enable_auto_naming').checked) {
        const template = document.getElementById('event_name_template').value || 'Event {n}';
        eventNames = generateEventNames(eventDays, template, startDateStr);
    } else {
        eventNames = eventDays.map(() => '');
    }

    // Update preview
    const previewTbody = document.getElementById('bulk_preview_tbody');
    previewTbody.innerHTML = '';
    
    const parts = startDateStr.split('-').map(p => parseInt(p, 10));
    const baseDate = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    
    eventDays.forEach((day, index) => {
        const date = new Date(baseDate.getTime() + day * 24 * 60 * 60 * 1000);
        const weekNum = Math.floor(day / 7) + 1;
        const monthNum = date.getUTCMonth() + 1;
        const monthNames = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${day}</td>
            <td>${weekNum}</td>
            <td>${monthNames[monthNum]} (${monthNum})</td>
            <td>${eventNames[index]}</td>
        `;
        previewTbody.appendChild(row);
    });

    document.getElementById('preview_event_count').textContent = eventDays.length;
    document.getElementById('preview-count-badge').textContent = eventDays.length;
    document.getElementById('confirm-count').textContent = eventDays.length;
    document.getElementById('bulk_preview_container').style.display = 'block';
    document.getElementById('confirm-bulk-add-btn').disabled = eventDays.length === 0;
});

// Confirm bulk add button handler
confirmBulkAddBtn.addEventListener('click', function () {
    const protocolId = document.getElementById('bulk_protocol_id').value;
    if (!protocolId) {
        alert('Please select a protocol.');
        return;
    }

    const startDateStr = startDateInput.value;
    if (!startDateStr) {
        alert('Please set a Study Start Date before bulk-adding events.');
        return;
    }

    // Get the previewed events
    const previewRows = document.getElementById('bulk_preview_tbody').querySelectorAll('tr');
    if (previewRows.length === 0) {
        alert('Please preview events first.');
        return;
    }

    // Add each event
    previewRows.forEach(row => {
        const cells = row.querySelectorAll('td');
        const day = parseInt(cells[0].textContent, 10);
        const eventName = cells[3].textContent;
        
        addEventRow({
            offset_days: day,
            protocol_id: protocolId,
            event_name: eventName
        });
    });

    updateAndSortTable();
    bulkAddModal.hide();
    document.getElementById('bulkAddForm').reset();
    document.getElementById('bulk_preview_container').style.display = 'none';
    document.getElementById('confirm-bulk-add-btn').disabled = true;
    
    // Reset pattern type to default
    document.getElementById('pattern_every_n_weeks').checked = true;
    document.querySelectorAll('.pattern-options').forEach(opt => opt.style.display = 'none');
    document.getElementById('every_n_weeks_options').style.display = 'block';
});

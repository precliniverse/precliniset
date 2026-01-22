/**
 * project_view.js
 * Handles interactions for the Project View page (Sharing, Archiving, Deleting).
 */

document.addEventListener('DOMContentLoaded', function() {
    // 1. Load Configuration
    const configEl = document.getElementById('project-config');
    if (!configEl) return;
    const CONFIG = JSON.parse(configEl.textContent);

    // --- Helper: Apply Presets ---
    function applyPreset(preset, checkboxes) {
        console.log(`Applying preset '${preset}'`);
        if (preset === 'custom') return;

        // Reset all to false
        for (let key in checkboxes) { if(checkboxes[key]) checkboxes[key].checked = false; }

        // 'Viewer' preset
        if(checkboxes.view) checkboxes.view.checked = true;
        if(checkboxes.view_g) checkboxes.view_g.checked = true;
        if(checkboxes.view_dt) checkboxes.view_dt.checked = true;
        if(checkboxes.view_s) checkboxes.view_s.checked = true;

        if (preset === 'collaborator') {
            if(checkboxes.create_g) checkboxes.create_g.checked = true;
            if(checkboxes.edit_g) checkboxes.edit_g.checked = true;
            if(checkboxes.create_dt) checkboxes.create_dt.checked = true;
            if(checkboxes.edit_dt) checkboxes.edit_dt.checked = true;
        } else if (preset === 'manager') {
            for (let key in checkboxes) { 
                if(checkboxes[key] && key !== 'unblind') checkboxes[key].checked = true; 
            }
        }
    }

    // --- Share Logic ---
    const shareProjectCard = document.getElementById('shareProjectCard');
    if (shareProjectCard) {
        // 1. User Share Logic
        const userPresetSelect = document.getElementById('user-share-preset');
        if (userPresetSelect) {
            const userCheckboxes = {
                view: document.getElementById('user_can_view'),
                view_g: document.getElementById('user_view_groups'),
                view_dt: document.getElementById('user_view_dt'),
                view_s: document.getElementById('user_view_samples'),
                create_g: document.getElementById('user_create_groups'),
                edit_g: document.getElementById('user_edit_groups'),
                delete_g: document.getElementById('user_delete_groups'),
                create_dt: document.getElementById('user_create_dt'),
                edit_dt: document.getElementById('user_edit_dt'),
                delete_dt: document.getElementById('user_delete_dt'),
                unblind: document.getElementById('user_view_unblinded')
            };

            userPresetSelect.addEventListener('change', function() {
                applyPreset(this.value, userCheckboxes);
            });
        }

        // 2. Team Share Logic
        const teamPresetSelect = document.getElementById('team-share-preset');
        const teamSelect = document.getElementById('team_to_share');
        
        if (teamPresetSelect) {
            const teamCheckboxes = {
                view: document.getElementById('team_can_view'),
                view_g: document.getElementById('team_view_groups'),
                view_dt: document.getElementById('team_view_dt'),
                view_s: document.getElementById('team_view_samples'),
                create_g: document.getElementById('team_create_groups'),
                edit_g: document.getElementById('team_edit_groups'),
                delete_g: document.getElementById('team_delete_groups'),
                create_dt: document.getElementById('team_create_dt'),
                edit_dt: document.getElementById('team_edit_dt'),
                delete_dt: document.getElementById('team_delete_dt'),
                unblind: document.getElementById('team_view_unblinded')
            };

            teamPresetSelect.addEventListener('change', function() {
                applyPreset(this.value, teamCheckboxes);
            });

            if (teamSelect) {
                teamSelect.addEventListener('change', function() {
                    const teamId = this.value;
                    if (teamId && teamId !== '0') {
                        fetchPermissions('team', teamId, teamCheckboxes);
                    }
                });
            }
        }
    }

    // --- Fetch Permissions Helper ---
    function fetchPermissions(type, id, checkboxes) {
        console.log(`Fetching permissions for ${type} ID: ${id}`);
        if (!id) {
            console.error("Invalid ID for permission fetch:", id);
            return;
        }

        const url = type === 'user' 
            ? CONFIG.urls.getUserPermissions.replace('999999', id)
            : CONFIG.urls.getTeamPermissions.replace('999999', id);

        fetch(url)
            .then(r => r.json())
            .then(data => {

                if (data.error) { alert(data.error); return; }

                // Set checkboxes based on fetched data
                if(checkboxes.view) checkboxes.view.checked = data.can_view_project;
                if(checkboxes.view_g) checkboxes.view_g.checked = data.can_view_exp_groups;
                if(checkboxes.view_dt) checkboxes.view_dt.checked = data.can_view_datatables;
                if(checkboxes.view_s) checkboxes.view_s.checked = data.can_view_samples;
                if(checkboxes.create_g) checkboxes.create_g.checked = data.can_create_exp_groups;
                if(checkboxes.edit_g) checkboxes.edit_g.checked = data.can_edit_exp_groups;
                if(checkboxes.delete_g) checkboxes.delete_g.checked = data.can_delete_exp_groups;
                if(checkboxes.create_dt) checkboxes.create_dt.checked = data.can_create_datatables;
                if(checkboxes.edit_dt) checkboxes.edit_dt.checked = data.can_edit_datatables;
                if(checkboxes.delete_dt) checkboxes.delete_dt.checked = data.can_delete_datatables;
                if(checkboxes.unblind) checkboxes.unblind.checked = data.can_view_unblinded_data;

                // UI Feedback
                const submitBtnName = type === 'user' ? 'submit_share_user' : 'submit_share_team';
                const submitBtn = document.querySelector(`button[name="${submitBtnName}"]`);
                if(submitBtn) submitBtn.textContent = CONFIG.i18n.updatePermissions;
                
                const presetSelect = document.getElementById(`${type}-share-preset`);
                if(presetSelect) presetSelect.value = 'custom';

                const collapseEl = document.getElementById('shareProjectCollapse');
                if(collapseEl) {
                    new bootstrap.Collapse(collapseEl, {toggle: false}).show();
                    const tabId = type === 'user' ? 'user-tab' : 'team-tab';
                    const tab = document.getElementById(tabId);
                    if(tab) new bootstrap.Tab(tab).show();
                    collapseEl.scrollIntoView({ behavior: 'smooth' });
                }
            });
    }

    // --- Event Listeners for "Edit" Buttons (Delegation) ---
    document.addEventListener('click', function(e) {
        // Edit User Share
        if (e.target.closest('.edit-user-share-btn')) {
            const btn = e.target.closest('.edit-user-share-btn');
            const userId = btn.dataset.userId;
            
            if (!userId) {
                console.error("User ID missing on edit button");
                return;
            }

            const userSelect = document.getElementById('user_to_share');
            if (userSelect) userSelect.value = userId;
            
            const checkboxes = {
                view: document.getElementById('user_can_view'),
                view_g: document.getElementById('user_view_groups'),
                view_dt: document.getElementById('user_view_dt'),
                view_s: document.getElementById('user_view_samples'),
                create_g: document.getElementById('user_create_groups'),
                edit_g: document.getElementById('user_edit_groups'),
                delete_g: document.getElementById('user_delete_groups'),
                create_dt: document.getElementById('user_create_dt'),
                edit_dt: document.getElementById('user_edit_dt'),
                delete_dt: document.getElementById('user_delete_dt'),
                unblind: document.getElementById('user_view_unblinded')
            };
            fetchPermissions('user', userId, checkboxes);
        }

        // Edit Team Share
        if (e.target.closest('.edit-team-share-btn')) {
            const btn = e.target.closest('.edit-team-share-btn');
            const teamId = btn.dataset.teamId;

            if (!teamId) {
                console.error("Team ID missing on edit button");
                return;
            }

            const teamSelect = document.getElementById('team_to_share');
            if (teamSelect) teamSelect.value = teamId;

            const checkboxes = {
                view: document.getElementById('team_can_view'),
                view_g: document.getElementById('team_view_groups'),
                view_dt: document.getElementById('team_view_dt'),
                view_s: document.getElementById('team_view_samples'),
                create_g: document.getElementById('team_create_groups'),
                edit_g: document.getElementById('team_edit_groups'),
                delete_g: document.getElementById('team_delete_groups'),
                create_dt: document.getElementById('team_create_dt'),
                edit_dt: document.getElementById('team_edit_dt'),
                delete_dt: document.getElementById('team_delete_dt'),
                unblind: document.getElementById('team_view_unblinded')
            };
            fetchPermissions('team', teamId, checkboxes);
        }
    });

    // --- Archive Modal Logic ---
    const archiveModalEl = document.getElementById('archiveProjectModal');
    if (archiveModalEl) {
        archiveModalEl.addEventListener('show.bs.modal', function () {
            fetch(CONFIG.urls.archiveInfo)
                .then(r => r.json())
                .then(data => {
                    const impactInfoDiv = document.getElementById('archiveImpactInfo');
                    if (data.error) {
                        impactInfoDiv.innerHTML = `<p class="text-danger">${data.error}</p>`;
                    } else {
                        let infoHtml = `<p>${CONFIG.i18n.projectHas}</p><ul>`;
                        infoHtml += `<li>${data.active_groups_count} ${CONFIG.i18n.activeGroups}</li>`;
                        infoHtml += `<li>${data.active_datatables_count} ${CONFIG.i18n.activeDatatables}</li>`;
                        infoHtml += `<li>${CONFIG.i18n.lastEntry} ${data.last_datatable_date || 'N/A'}.</li></ul>`;
                        impactInfoDiv.innerHTML = infoHtml;
                        
                        const cascadeCheckbox = document.getElementById('cascadeArchiveGroupsCheckbox');
                        if (data.active_groups_count > 0) {
                            cascadeCheckbox.disabled = false;
                            cascadeCheckbox.parentElement.classList.remove('text-muted');
                        } else {
                            cascadeCheckbox.checked = false;
                            cascadeCheckbox.disabled = true;
                            cascadeCheckbox.parentElement.classList.add('text-muted');
                        }
                    }
                });
        });
        
        const archiveForm = document.getElementById('archiveProjectForm');
        if (archiveForm) {
            archiveForm.addEventListener('submit', function() {
                document.getElementById('hiddenCascadeArchiveGroups').value = 
                    document.getElementById('cascadeArchiveGroupsCheckbox').checked ? 'true' : 'false';
            });
        }
    }

    // --- Delete Project Modal Logic ---
    const deleteProjectModalEl = document.getElementById('deleteProjectModal');
    if (deleteProjectModalEl) {
        const confirmSlugInput = document.getElementById('deleteConfirmSlug');
        const confirmDeleteBtn = document.getElementById('confirmDeleteProjectBtn');
        
        if (confirmSlugInput && confirmDeleteBtn) {
            confirmSlugInput.addEventListener('input', function() {
                confirmDeleteBtn.disabled = (this.value !== CONFIG.projectSlug);
            });
        }
    }

    // --- Unlink Group Modal Logic ---
    const unlinkGroupModalEl = document.getElementById('unlinkGroupModal');
    if (unlinkGroupModalEl) {
        const modal = new bootstrap.Modal(unlinkGroupModalEl);
        const actionSelect = document.getElementById('unlink_action_modal');
        const confirmBtn = document.getElementById('confirmUnlinkActionBtnModal');
        const targetSelect = document.getElementById('target_project_id_modal');
        let currentGroupId = null;
        let currentProjectSlug = null;

        document.querySelectorAll('.unlink-group-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                currentGroupId = this.dataset.groupId;
                currentProjectSlug = this.dataset.projectSlug;
                
                document.getElementById('unlinkGroupNameModal').textContent = this.dataset.groupName;
                actionSelect.value = "";
                document.getElementById('reassignProjectSectionModal').style.display = 'none';
                document.getElementById('deleteGroupWarningModal').style.display = 'none';
                confirmBtn.disabled = true;
                
                // Populate target projects
                if (targetSelect) {
                    targetSelect.innerHTML = `<option value="">${CONFIG.i18n.selectTarget}</option>`;
                    fetch(CONFIG.urls.manageableProjects.replace('999999', this.dataset.groupTeamId))
                        .then(r => r.json())
                        .then(data => {
                            data.projects.forEach(p => {
                                targetSelect.add(new Option(p.name, p.id));
                            });
                        });
                }
                modal.show();
            });
        });

        actionSelect.addEventListener('change', function() {
            const isReassign = this.value === 'reassign';
            const isDelete = this.value === 'delete';
            
            document.getElementById('reassignProjectSectionModal').style.display = isReassign ? 'block' : 'none';
            document.getElementById('deleteGroupWarningModal').style.display = isDelete ? 'block' : 'none';
            
            if (isDelete) {
                confirmBtn.disabled = false;
                confirmBtn.className = 'btn btn-danger';
                confirmBtn.textContent = CONFIG.i18n.delete;
            } else if (isReassign) {
                confirmBtn.disabled = (targetSelect.value === "");
                confirmBtn.className = 'btn btn-info';
                confirmBtn.textContent = CONFIG.i18n.reassign;
            } else {
                confirmBtn.disabled = true;
            }
        });

        targetSelect.addEventListener('change', function() {
            if (actionSelect.value === 'reassign') {
                confirmBtn.disabled = (this.value === "");
            }
        });

        document.getElementById('unlinkGroupFormModal').addEventListener('submit', function(e) {
            if (currentProjectSlug && currentGroupId) {
                this.action = `/projects/${currentProjectSlug}/groups/${currentGroupId}/handle_unlink`;
            } else {
                e.preventDefault();
                alert("Error: Missing context.");
            }
        });
    }

    // --- Workplan Delete Logic ---
    const deleteWorkplanModalEl = document.getElementById('deleteWorkplanModal');
    if (deleteWorkplanModalEl) {
        const modal = new bootstrap.Modal(deleteWorkplanModalEl);
        const confirmBtn = document.getElementById('confirmDeleteWorkplanBtn');
        const infoDiv = document.getElementById('workplanDeleteImpactInfo');
        let currentWorkplanId = null;

        document.querySelectorAll('.delete-workplan-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                currentWorkplanId = this.dataset.workplanId;
                document.getElementById('workplanNameToDelete').textContent = this.dataset.workplanName;
                infoDiv.style.display = 'none';
                confirmBtn.disabled = true;

                fetch(CONFIG.urls.workplanDeleteInfo.replace('999999', currentWorkplanId))
                    .then(r => r.json())
                    .then(data => {
                        if (data.can_delete) {
                            confirmBtn.disabled = false;
                        } else {
                            infoDiv.style.display = 'block';
                            infoDiv.innerHTML = CONFIG.i18n.workplanHasGroup.replace('%s', data.group.name);
                        }
                        modal.show();
                    });
            });
        });

        confirmBtn.addEventListener('click', function(e) {
            e.preventDefault();
            if (currentWorkplanId) {
                document.getElementById(`delete-workplan-form-${currentWorkplanId}`).submit();
            }
        });
    }

    // --- Generic Confirm Action ---
    document.querySelectorAll('.confirm-action-form').forEach(form => {
        form.addEventListener('submit', function(e) {
            if (!confirm(this.dataset.confirmMessage || CONFIG.i18n.confirm)) {
                e.preventDefault();
            }
        });
    });
});
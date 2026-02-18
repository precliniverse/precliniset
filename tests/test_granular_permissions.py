"""
Tests de permissions granulaires (RBAC).
Vérifie que les rôles personnalisés respectent les limites de permissions.
"""
import pytest
from datetime import date

from app.models import User, Role, Permission, UserTeamRoleLink, Team, EthicalApproval, Storage
from tests.conftest import login


# --- Helper to create a custom role dynamically ---
def create_custom_role(db_session, name, permissions_list, team=None):
    """Creates a role with specific permissions."""
    role = Role(name=name, team=team)
    db_session.add(role)
    
    for res, act in permissions_list:
        perm = Permission.query.filter_by(resource=res, action=act).first()
        if perm:
            role.permissions.append(perm)
        else:
            raise ValueError(f"Permission {res}:{act} not found in DB seeding.")
    
    db_session.commit()
    return role

def assign_role(db_session, user, team, role):
    link = UserTeamRoleLink(user_id=user.id, team_id=team.id, role_id=role.id)
    db_session.add(link)
    db_session.commit()


# ==========================================
# TEST CASE 1: The "Submitter" (Dead Switch)
# ==========================================
def test_create_only_permission(test_client, db_session, init_database):
    """
    GIVEN a user with 'EthicalApproval:create' but NOT 'EthicalApproval:edit'
    WHEN they try to access the create route vs the edit route
    THEN they should be allowed to Create, but forbidden to Edit.
    """
    # 1. Setup User and Team
    team = init_database['team1']
    user = User(email='submitter@test.com', email_confirmed=True, is_active=True)
    user.set_password('password')
    db_session.add(user)
    
    # 2. Create "Submitter" Role (Create YES, Edit NO)
    submitter_role = create_custom_role(db_session, "Submitter", [
        ('EthicalApproval', 'create'),
        ('EthicalApproval', 'view') # Usually needed to see the list
    ], team=team)
    
    assign_role(db_session, user, team, submitter_role)
    
    login(test_client, 'submitter@test.com', 'password')

    # 3. TEST: Can they access the CREATE page?
    # This verifies we fixed the "if not has_edit: abort" bug at the top of the route
    resp_create_page = test_client.get('/ethical_approvals/create')
    assert resp_create_page.status_code == 200
    assert b"Create Ethical Approval" in resp_create_page.data

    # 4. TEST: Can they access the EDIT page for an existing approval?
    # Create an EA first
    ea = EthicalApproval(
        reference_number='EA-TEST', title='Test', start_date=date.today(), 
        end_date=date.today(), number_of_animals=10, team_id=team.id
    )
    db_session.add(ea)
    db_session.commit()

    # Attempt to edit
    resp_edit_page = test_client.get(f'/ethical_approvals/{ea.id}/edit', follow_redirects=True)
    
    # Should be redirected away with a flash message (soft failure) or 403
    # Your code redirects to list_ethical_approvals on failure
    assert b"You do not have permission" in resp_edit_page.data
    assert b"Edit Ethical Approval" not in resp_edit_page.data


# ==========================================
# TEST CASE 2: Global vs. Team Scope
# ==========================================
def test_team_admin_cannot_create_global_resources(test_client, db_session, init_database):
    """
    GIVEN a standard 'Team Admin' (who has local power)
    WHEN they try to create a Global Resource (Analyte)
    THEN they should be blocked.
    """
    # 1. Log in as the standard Team Admin from fixtures
    # IMPORTANT: We assume update_perms.py has been run or init logic excludes Global perms from Team Admin
    login(test_client, 'team1admin@test.com', 'password')
    
    # 2. Try to POST a new Analyte
    resp = test_client.post('/resources/manage_analytes', data={
        'name': 'Malicious Global Analyte',
        'data_type': 'TEXT'
    }, follow_redirects=True)

    # 3. Expect Failure
    # If your fix works, user_has_permission(..., team_id=None) returns False for Team Admin
    assert b"You do not have permission" in resp.data
    
    # Verify DB
    from app.models import Analyte
    assert Analyte.query.filter_by(name='Malicious Global Analyte').first() is None


# ==========================================
# TEST CASE 3: Specific Granularity (Storage)
# ==========================================
def test_storage_manager_role(test_client, db_session, init_database):
    """
    GIVEN a 'Lab Manager' with 'Storage:create' but NOT 'Project:delete'
    WHEN they act on storages vs projects
    THEN permissions are respected separately.
    """
    team = init_database['team1']
    user = User(email='labmanager@test.com', email_confirmed=True, is_active=True)
    user.set_password('password')
    db_session.add(user)
    
    # Create "Lab Manager" Role
    role = create_custom_role(db_session, "Lab Manager", [
        ('Storage', 'create'),
        ('Storage', 'view'),
        ('Storage', 'edit'),
        ('Team', 'view') # Needed to access team pages
    ], team=team)
    
    assign_role(db_session, user, team, role)
    login(test_client, 'labmanager@test.com', 'password')

    # 1. Can create Storage? (Should PASS)
    resp_storage = test_client.post('/storage/', data={
        'name': 'New Freezer',
        'team_for_storage': team.id 
    }, follow_redirects=True)
    
    # Check for success message (handling potential HTML escaping)
    assert b"Storage" in resp_storage.data and b"created successfully" in resp_storage.data

    # 2. Can Delete Project? (Should FAIL)
    # Even though they can create storage, they aren't a "Team Admin"
    project = init_database['proj1']
    resp_project = test_client.post(f'/projects/{project.slug}/delete_project_cascade', follow_redirects=True)
    
    # Should be forbidden (403 or redirect with error)
    assert resp_project.status_code == 403 or b"permission" in resp_project.data.lower()
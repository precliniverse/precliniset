# tests/test_projects.py
from app.forms import ProjectForm
from app.models import Project, Team
from tests.conftest import login, logout, test_client


def test_team_admin_can_create_project(test_client, db_session, init_database):
    team1 = init_database['team1']
    login(test_client, init_database['team1_admin'].email, 'password')
    response = test_client.post('/projects/create', data={'name': 'New Project by Admin', 'team': team1.id}, follow_redirects=True)
    assert response.status_code == 200
    # Check for success message (handling potential HTML escaping of quotes)
    assert b'Project' in response.data and b'New Project by Admin' in response.data and b'created successfully' in response.data
    assert db_session.query(Project).filter_by(name='New Project by Admin').one_or_none() is not None
    logout(test_client)

def test_team_member_cannot_create_project(test_client, db_session, init_database):
    team1 = init_database['team1']
    login(test_client, init_database['team1_member'].email, 'password')
    response = test_client.post('/projects/create', data={'name': 'Member Project Attempt', 'team': team1.id}, follow_redirects=True)
    assert response.status_code == 403
    assert db_session.query(Project).filter_by(name='Member Project Attempt').one_or_none() is None
    logout(test_client)

def test_project_visibility_and_access(test_client, init_database):
    proj1 = init_database['proj1']
    proj2 = init_database['proj2']
    
    # Test team1_admin access
    login(test_client, init_database['team1_admin'].email, 'password')
    assert test_client.get(f'/projects/{proj1.slug}').status_code == 200
    assert test_client.get(f'/projects/{proj2.slug}').status_code == 403
    logout(test_client)
    
    # Test team2_admin access
    login(test_client, init_database['team2_admin'].email, 'password')
    assert test_client.get(f'/projects/{proj2.slug}').status_code == 200
    assert test_client.get(f'/projects/{proj1.slug}').status_code == 403
    logout(test_client)

def test_team_admin_can_edit_own_project(test_client, db_session, init_database):
    proj1 = init_database['proj1']
    original_name = proj1.name
    login(test_client, init_database['team1_admin'].email, 'password')
    response = test_client.post(f'/projects/{proj1.slug}', data={
        'name': 'Updated Project Name', 
        'description': 'Updated desc.', 
        'team': proj1.team_id, # Changed to pass integer directly
        'submit': 'Save Project'
    }, follow_redirects=True)
    assert response.status_code == 200
    db_session.refresh(proj1)
    assert proj1.name == 'Updated Project Name'
    logout(test_client)

def test_team_member_cannot_edit_project(test_client, db_session, init_database):
    """
    Test that a team member (who has read access but not edit access) cannot update the project.
    Note: The route returns 200 OK because it renders the view page (without edit forms) for read-only users.
    We assert that the project name remains unchanged.
    """
    proj1 = init_database['proj1']
    original_name = proj1.name
    login(test_client, init_database['team1_member'].email, 'password')
    
    # Attempt to post data
    response = test_client.post(f'/projects/{proj1.slug}', data={
        'name': 'Attempted Change', 
        'team': proj1.team_id,
        'submit': 'Save Project'
    }, follow_redirects=True)
    
    # The response code is 200 because the user has read access, so the page renders.
    assert response.status_code == 200
    
    # However, the update should NOT have happened.
    db_session.refresh(proj1)
    assert proj1.name == original_name
    logout(test_client)

def test_archive_and_unarchive_project(test_client, db_session, init_database):
    proj1 = init_database['proj1']
    login(test_client, init_database['team1_admin'].email, 'password')
    assert not proj1.is_archived
    test_client.post(f'/projects/{proj1.slug}/archive', follow_redirects=True)
    db_session.refresh(proj1)
    assert proj1.is_archived is True
    test_client.post(f'/projects/{proj1.slug}/unarchive', follow_redirects=True)
    db_session.refresh(proj1)
    assert proj1.is_archived is False
    logout(test_client)

def test_super_admin_can_delete_project(test_client, db_session, init_database):
    proj1_id = init_database['proj1'].id
    login(test_client, init_database['super_admin'].email, 'password')
    response = test_client.post(f"/projects/{init_database['proj1'].slug}/delete_project_cascade", follow_redirects=True)
    assert response.status_code == 200
    assert db_session.get(Project, proj1_id) is None
    logout(test_client)

def test_team_admin_cannot_delete_project(test_client, db_session, init_database):
    proj1 = init_database['proj1']
    login(test_client, init_database['team1_admin'].email, 'password')
    response = test_client.post(f'/projects/{proj1.slug}/delete_project_cascade', follow_redirects=True)
    assert response.status_code == 403
    assert db_session.get(Project, proj1.id) is not None
    logout(test_client)
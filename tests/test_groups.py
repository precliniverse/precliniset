# tests/test_groups.py
import json

from app.models import ExperimentalGroup
from tests.conftest import login, logout


def test_team_admin_can_create_group(team1_admin_client, db_session, init_database):
    proj1 = init_database['proj1']
    animal_model = init_database['animal_model']
    response = team1_admin_client.post('/groups/edit', data={'project': proj1.id, 'model': animal_model.id, 'name': 'New Group by Admin'}, follow_redirects=True)
    assert response.status_code == 200
    assert b'New Group by Admin' in response.data
    group = db_session.query(ExperimentalGroup).filter_by(name='New Group by Admin').first()
    assert group is not None and group.project_id == proj1.id

def test_team_member_cannot_create_group(team1_member_client, db_session, init_database):
    proj1 = init_database['proj1']
    animal_model = init_database['animal_model']
    response = team1_member_client.post('/groups/edit', data={'project': proj1.id, 'model': animal_model.id, 'name': 'Member Group Attempt'}, follow_redirects=True)
    assert response.status_code == 200
    assert b"You do not have permission to create groups in this project" in response.data
    group = db_session.query(ExperimentalGroup).filter_by(name='Member Group Attempt').first()
    assert group is None

def test_user_can_view_own_group(team1_member_client, init_database):
    """
    GIVEN a team member
    WHEN they access a group from their own team
    THEN they should get a 200 OK (read-only view), not a 403.
    """
    group = init_database['group1']
    # A member should be able to VIEW their own team's group, but not edit.
    # The /edit/<id> route now handles read-only mode.
    response = team1_member_client.get(f'/groups/view/{group.id}') # Use the /view/ endpoint
    assert response.status_code == 200
    # Check for some content that indicates it's the correct page
    assert b'Test Group 1' in response.data
    # Check that the main save button is NOT present for read-only users
    assert b'id="save-group-btn"' not in response.data

def test_user_cannot_view_other_team_group(team1_member_client, init_database):
    group2 = init_database['group2']
    response = team1_member_client.get(f'/groups/edit/{group2.id}')
    assert response.status_code == 403

def test_edit_group_animal_data(team1_admin_client, db_session, init_database):
    group = init_database['group1']
    animal_model = init_database['animal_model']
    ea1 = init_database['ea1']  # Get the ethical approval from the fixture
    animal_data = [{'ID': 'Mouse-01', 'Genotype': 'WT'}, {'ID': 'Mouse-02', 'Genotype': 'KO'}]
    payload = {
        'name': group.name,
        'model': animal_model.id,
        'ethical_approval': ea1.id,  # Use the ethical approval ID
        'animal_data': json.dumps(animal_data),
        'update_data_tables': 'yes'
    }
    response = team1_admin_client.post(f'/groups/edit/{group.id}', data=payload, follow_redirects=True)
    assert response.status_code == 200
    assert b'Group details and animal data saved successfully' in response.data
    db_session.refresh(group)
    assert len(group.animal_data) == 2 and group.animal_data[0]['ID'] == 'Mouse-01'

def test_archive_and_unarchive_group(team1_admin_client, db_session, init_database):
    group = init_database['group1']
    assert not group.is_archived
    team1_admin_client.post(f'/groups/archive/{group.id}', follow_redirects=True)
    # Query the database directly to check the state
    archived_group = db_session.query(ExperimentalGroup).filter_by(id=group.id).first()
    assert archived_group.is_archived is True

    team1_admin_client.post(f'/groups/unarchive/{group.id}', follow_redirects=True)
    # Query the database directly to check the state
    unarchived_group = db_session.query(ExperimentalGroup).filter_by(id=group.id).first()
    assert unarchived_group.is_archived is False
    assert group.is_archived is False

def test_delete_group(team1_admin_client, db_session, init_database):
    group = init_database['group1']
    group_id = group.id
    response = team1_admin_client.post(f'/groups/delete/{group.id}', data={'cascade': 'false'}, follow_redirects=True)
    assert response.status_code == 200
    assert b'Group deleted successfully' in response.data
    assert db_session.get(ExperimentalGroup, group_id) is None
# tests/test_api_admin.py
from app.models import APIToken, Team, User


def test_api_cannot_escalate_privilege(test_client, db_session, init_database, super_admin_api_token):
    """
    GIVEN a super admin with a valid API token
    WHEN they attempt to update another user's 'is_super_admin' status via the API
    THEN check that the 'is_super_admin' status remains unchanged.
    """
    target_user = init_database['team1_member']
    assert not target_user.is_super_admin

    response = test_client.put(
        f'/api/v1/admin/users/{target_user.id}',
        headers={'Authorization': f'Bearer {super_admin_api_token}'},
        json={
            'email': target_user.email,
            'is_active': False,
            'is_super_admin': True  # The malicious attempt
        }
    )
    assert response.status_code == 200

    db_session.refresh(target_user)
    assert not target_user.is_super_admin, "Privilege escalation vulnerability detected!"
    assert not target_user.is_active

def test_team_admin_cannot_access_global_user_list(test_client, api_token):
    """
    GIVEN a team admin
    WHEN they attempt to list all users via the API
    THEN they should receive a 403 Forbidden error.
    """
    response = test_client.get('/api/v1/admin/users', headers={'Authorization': f'Bearer {api_token}'})
    assert response.status_code == 403

def test_team_admin_can_manage_own_team_members(test_client, db_session, init_database, api_token):
    """
    GIVEN a team admin
    WHEN they add or remove a member from their own team via the API
    THEN the action should succeed.
    """
    team1 = init_database['team1']
    no_team_user = init_database['no_team_user']

    # Add user to team
    response = test_client.post(
        f'/api/v1/admin/teams/{team1.id}/members',
        headers={'Authorization': f'Bearer {api_token}'},
        json={'user_id': no_team_user.id}
    )
    assert response.status_code == 201
    assert no_team_user in team1.members

    # Remove user from team
    response = test_client.delete(
        f'/api/v1/admin/teams/{team1.id}/members/{no_team_user.id}',
        headers={'Authorization': f'Bearer {api_token}'}
    )
    assert response.status_code == 204
    assert no_team_user not in team1.members

def test_team_admin_cannot_manage_other_team_members(test_client, init_database, api_token):
    """
    GIVEN a team admin from Team 1
    WHEN they attempt to add a member to Team 2
    THEN they should receive a 403 Forbidden error.
    """
    team2 = init_database['team2']
    no_team_user = init_database['no_team_user']
    
    response = test_client.post(
        f'/api/v1/admin/teams/{team2.id}/members',
        headers={'Authorization': f'Bearer {api_token}'},
        json={'user_id': no_team_user.id}
    )
    assert response.status_code == 403

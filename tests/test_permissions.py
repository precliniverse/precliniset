# tests/test_permissions.py
from app.models import ProjectTeamShare, user_has_permission


def test_super_admin_permissions(init_database):
    """
    GIVEN a super admin user
    WHEN their permissions are checked
    THEN they should have permission for any action on any resource.
    """
    super_admin = init_database['super_admin']
    assert super_admin.is_super_admin is True
    assert user_has_permission(super_admin, 'Project', 'delete') is True
    assert user_has_permission(super_admin, 'User', 'create') is True
    assert user_has_permission(super_admin, 'AnyResource', 'any_action') is True

def test_team_admin_permissions(init_database):
    """
    GIVEN a team admin user
    WHEN their permissions are checked
    THEN they should have admin permissions for their own team, but not others.
    """
    team1_admin = init_database['team1_admin']
    team1 = init_database['team1']
    team2 = init_database['team2']

    # Has 'manage_members' permission for their own team
    assert user_has_permission(team1_admin, 'Team', 'manage_members', team_id=team1.id) is True
    
    # Does NOT have 'manage_members' for another team
    assert user_has_permission(team1_admin, 'Team', 'manage_members', team_id=team2.id) is False
    
    # Has 'create' project permission for their team (from default roles)
    assert user_has_permission(team1_admin, 'Project', 'create', team_id=team1.id) is True

def test_team_member_permissions(init_database):
    """
    GIVEN a regular team member
    WHEN their permissions are checked
    THEN they should have read permissions but not edit/create permissions.
    """
    team1_member = init_database['team1_member']
    team1 = init_database['team1']

    # Has 'read' permission for projects in their team
    assert user_has_permission(team1_member, 'Project', 'read', team_id=team1.id) is True
    
    # Does NOT have 'create' or 'edit' permissions
    assert user_has_permission(team1_member, 'Project', 'create', team_id=team1.id) is False
    assert user_has_permission(team1_member, 'Project', 'edit', team_id=team1.id) is False
    assert user_has_permission(team1_member, 'Team', 'manage_members', team_id=team1.id) is False

def test_get_accessible_projects(db_session, init_database):
    """
    GIVEN a set of users, teams, projects, and a project share
    WHEN get_accessible_projects() is called for different users
    THEN the correct set of projects should be returned based on ownership and shares.
    """
    super_admin = init_database['super_admin']
    team1_admin = init_database['team1_admin']
    team1_member = init_database['team1_member']
    team2_admin = init_database['team2_admin']
    proj1 = init_database['proj1']
    proj2 = init_database['proj2']
    team1 = init_database['team1']
    
    # 1. Super admin sees all projects
    super_admin_projects = super_admin.get_accessible_projects()
    assert len(super_admin_projects) == 2
    assert proj1 in super_admin_projects
    assert proj2 in super_admin_projects

    # 2. Team 1 admin sees only their team's project
    team1_admin_projects = team1_admin.get_accessible_projects()
    assert len(team1_admin_projects) == 1
    assert proj1 in team1_admin_projects
    assert proj2 not in team1_admin_projects

    # 3. Team 1 member sees only their team's project
    team1_member_projects = team1_member.get_accessible_projects()
    assert len(team1_member_projects) == 1
    assert proj1 in team1_member_projects
    assert proj2 not in team1_member_projects

    # 4. Team 2 admin sees only their team's project
    team2_admin_projects = team2_admin.get_accessible_projects()
    assert len(team2_admin_projects) == 1
    assert proj2 in team2_admin_projects
    assert proj1 not in team2_admin_projects

    # 5. Now, share Team 2's project with Team 1
    share = ProjectTeamShare(
        project_id=proj2.id,
        team_id=team1.id,
        can_view_project=True
    )
    db_session.add(share)
    db_session.commit()

    # 6. Team 1 member should now see both projects
    team1_member_projects_after_share = team1_member.get_accessible_projects()
    assert len(team1_member_projects_after_share) == 2
    assert proj1 in team1_member_projects_after_share
    assert proj2 in team1_member_projects_after_share
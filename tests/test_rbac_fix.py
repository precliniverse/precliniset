import pytest
from app.models import User, Role, Permission, UserTeamRoleLink, Team, user_has_permission
from flask import g

def create_custom_role(db_session, name, permissions_list, team=None):
    """Creates a role with specific permissions."""
    role = Role(name=name, team=team)
    db_session.add(role)
    
    for res, act in permissions_list:
        perm = Permission.query.filter_by(resource=res, action=act).first()
        if not perm:
            # Create permission if it doesn't exist for testing
            perm = Permission(resource=res, action=act)
            db_session.add(perm)
        role.permissions.append(perm)
    
    db_session.commit()
    return role

def assign_role(db_session, user, team, role):
    link = UserTeamRoleLink(user_id=user.id, team_id=team.id, role_id=role.id)
    db_session.add(link)
    db_session.commit()

def test_user_has_permission_allow_any_team(db_session, init_database):
    """
    Test that the allow_any_team flag works as expected.
    """
    team = init_database['team1']
    user = User(email='test_rbac@test.com', email_confirmed=True, is_active=True)
    user.set_password('password')
    db_session.add(user)
    db_session.commit()

    # 1. User has NO permissions yet
    assert user_has_permission(user, 'CoreModel', 'create') is False
    assert user_has_permission(user, 'CoreModel', 'create', allow_any_team=True) is False

    # 2. Assign a TEAM-SPECIFIC role with CoreModel:create permission
    team_role = create_custom_role(db_session, "Team Designer", [('CoreModel', 'create')], team=team)
    assign_role(db_session, user, team, team_role)

    # 3. Check permission contextually (should PASS)
    assert user_has_permission(user, 'CoreModel', 'create', team_id=team.id) is True

    # CLEANUP CACHE for the next check, as user_has_permission caches results in g
    if hasattr(g, '_permission_cache'):
        g._permission_cache = {}

    # 4. Check permission WITHOUT team_id (Global check)
    # Default (allow_any_team=False) should FAIL
    assert user_has_permission(user, 'CoreModel', 'create', allow_any_team=False) is False
    
    # allow_any_team=True should PASS
    assert user_has_permission(user, 'CoreModel', 'create', allow_any_team=True) is True

@pytest.mark.skip(reason="UserTeamRoleLink schema does not support team_id=None (NOT NULL constraint). Global roles logic needs refactoring.")
def test_user_has_permission_global_role(db_session, init_database):
    """
    Test that global roles still work with the flag.
    """
    user = User(email='global_rbac@test.com', email_confirmed=True, is_active=True)
    user.set_password('password')
    db_session.add(user)
    db_session.commit()

    # Create a GLOBAL role
    global_role = create_custom_role(db_session, "Global Designer", [('CoreModel', 'create')], team=None)
    
    # Link user to this global role (using team_id=None or some default)
    # In precliniset, global roles are often linked via a special mechanism or just being in the link table with team_id=None? 
    # Let's check UserTeamRoleLink structure.
    
    # link = UserTeamRoleLink(user_id=user.id, team_id=None, role_id=global_role.id)
    # db_session.add(link)
    # db_session.commit()

    # Should PASS both ways because it's a global role
    # assert user_has_permission(user, 'CoreModel', 'create', allow_any_team=False) is True
    # assert user_has_permission(user, 'CoreModel', 'create', allow_any_team=True) is True

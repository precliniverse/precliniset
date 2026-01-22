import pytest
from app.models import AuditLog, Project, User, Role
from app.extensions import db

def test_audit_log_creation(test_client, db_session, init_database):
    """
    Test that AuditLogs are created for CRUD operations.
    """
    admin_user = init_database['super_admin']
    
    # login
    test_client.post('/auth/login', data={'email': admin_user.email, 'password': 'password'})

    from flask_login import login_user
    from flask import current_app

    # 1. INSERT Logic
    # Creating a new project should trigger an INSERT log
    # Note: We rely on the app context being active which init_database/test_client provides
    
    # We need to simulate the login in the current context for the listener to pick it up
    with test_client.application.test_request_context():
        login_user(admin_user)
        new_project = Project(
            name="Audit Test Project",
            slug="audit-test",
            team_id=init_database['team1'].id,
            owner_id=admin_user.id
        )
        db_session.add(new_project)
        db_session.commit()
    
    log_entry = AuditLog.query.filter_by(
        resource_type='Project', 
        resource_id=str(new_project.id),
        action='INSERT'
    ).first()
    
    assert log_entry is not None
    assert log_entry.user_id == admin_user.id
    
    # 2. UPDATE Logic
    # Changing the name
    new_project.name = "Audit Test Project Updated"
    db_session.commit()
    
    update_log = AuditLog.query.filter_by(
        resource_type='Project',
        resource_id=str(new_project.id),
        action='UPDATE'
    ).order_by(AuditLog.timestamp.desc()).first()
    
    assert update_log is not None
    assert update_log.changes is not None
    assert "Audit Test Project" == update_log.changes['name']['old']
    assert "Audit Test Project Updated" == update_log.changes['name']['new']
    
    # 3. DELETE Logic
    project_id_str = str(new_project.id)
    db_session.delete(new_project)
    db_session.commit()
    
    delete_log = AuditLog.query.filter_by(
        resource_type='Project',
        resource_id=project_id_str,
        action='DELETE'
    ).first()
    
    assert delete_log is not None

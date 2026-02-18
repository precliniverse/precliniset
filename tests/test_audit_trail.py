"""
Tests de la piste d'audit (AuditLog).
Vérifie que les opérations INSERT/UPDATE/DELETE génèrent des entrées de log.
"""
import pytest
from flask_login import login_user

from app.extensions import db
from app.models import AuditLog, Project, User, Role
from tests.conftest import login


def test_audit_log_creation(logged_in_client, db_session, init_database):
    """
    GIVEN un utilisateur super_admin connecté
    WHEN des opérations CRUD sont effectuées sur un Project
    THEN des entrées AuditLog INSERT/UPDATE/DELETE doivent être créées.
    """
    admin_user = init_database['super_admin']
    team1 = init_database['team1']

    # 1. INSERT — Créer un projet déclenche un log INSERT
    new_project = Project(
        name="Audit Test Project",
        slug="audit-test",
        team_id=team1.id,
        owner_id=admin_user.id,
    )
    db_session.add(new_project)
    db_session.flush()

    log_entry = AuditLog.query.filter_by(
        resource_type='Project',
        resource_id=str(new_project.id),
        action='INSERT',
    ).first()

    assert log_entry is not None, "Un log INSERT doit être créé lors de l'ajout d'un Project"

    # 2. UPDATE — Modifier le nom déclenche un log UPDATE
    new_project.name = "Audit Test Project Updated"
    db_session.flush()

    update_log = AuditLog.query.filter_by(
        resource_type='Project',
        resource_id=str(new_project.id),
        action='UPDATE',
    ).order_by(AuditLog.timestamp.desc()).first()

    assert update_log is not None, "Un log UPDATE doit être créé lors de la modification d'un Project"
    assert update_log.changes is not None
    assert update_log.changes['name']['old'] == "Audit Test Project"
    assert update_log.changes['name']['new'] == "Audit Test Project Updated"

    # 3. DELETE — Supprimer le projet déclenche un log DELETE
    project_id_str = str(new_project.id)
    db_session.delete(new_project)
    db_session.flush()

    delete_log = AuditLog.query.filter_by(
        resource_type='Project',
        resource_id=project_id_str,
        action='DELETE',
    ).first()

    assert delete_log is not None, "Un log DELETE doit être créé lors de la suppression d'un Project"

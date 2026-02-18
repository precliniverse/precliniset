# tests/test_workplan_service.py
"""
Tests unitaires du WorkplanService.
Vérifie la création, la mise à jour, la gestion des versions et des événements.
"""
from datetime import date, timedelta

import pytest

from app.models import (
    AnimalModel, Project, ProtocolModel, Workplan,
    WorkplanEvent, WorkplanEventStatus, WorkplanStatus, WorkplanVersion,
)
from app.services.workplan_service import WorkplanService


@pytest.fixture
def workplan_service():
    return WorkplanService()


@pytest.fixture
def workplan_setup(db_session, init_database):
    """Crée un workplan de base pour les tests."""
    project = init_database['proj1']
    animal_model = init_database['animal_model']
    admin_user = init_database['team1_admin']

    protocol = ProtocolModel(name='WP Test Protocol')
    db_session.add(protocol)
    db_session.flush()

    workplan = Workplan(
        project_id=project.id,
        name='Test Workplan',
        animal_model_id=animal_model.id,
        planned_animal_count=20,
        status=WorkplanStatus.DRAFT,
    )
    db_session.add(workplan)
    db_session.flush()

    return {
        'workplan': workplan,
        'project': project,
        'animal_model': animal_model,
        'admin_user': admin_user,
        'protocol': protocol,
    }


# ---------------------------------------------------------------------------
# Tests de création
# ---------------------------------------------------------------------------

def test_create_workplan(test_app, db_session, workplan_service, init_database):
    """
    GIVEN un projet et un modèle animal
    WHEN create_workplan est appelé
    THEN un Workplan en statut DRAFT doit être créé.
    """
    with test_app.app_context():
        project = init_database['proj1']
        animal_model = init_database['animal_model']

        workplan = workplan_service.create_workplan(
            project_id=project.id,
            name='New Workplan',
            planned_animal_count=30,
        )
        db_session.flush()

        assert workplan.id is not None
        assert workplan.name == 'New Workplan'
        assert workplan.planned_animal_count == 30
        assert workplan.status == WorkplanStatus.DRAFT


# ---------------------------------------------------------------------------
# Tests de mise à jour
# ---------------------------------------------------------------------------

def test_update_workplan_creates_version(test_app, db_session, workplan_service, workplan_setup):
    """
    GIVEN un workplan existant
    WHEN update_workplan est appelé
    THEN une nouvelle WorkplanVersion doit être créée avec le bon numéro.
    """
    with test_app.app_context():
        workplan = workplan_setup['workplan']
        admin_user = workplan_setup['admin_user']
        protocol = workplan_setup['protocol']

        new_state = {
            'study_start_date': (date.today() + timedelta(days=30)).isoformat(),
            'expected_dob': (date.today() - timedelta(days=60)).isoformat(),
            'notes': 'Updated notes',
            'planned_animal_count': 25,
            'events': [
                {
                    'offset_days': 0,
                    'protocol_id': protocol.id,
                    'event_name': 'Day 0 Measurement',
                    'assigned_to_id': None,
                }
            ],
        }

        workplan_service.update_workplan(
            workplan, new_state, admin_user,
            change_comment='Initial setup',
        )
        db_session.flush()

        versions = WorkplanVersion.query.filter_by(workplan_id=workplan.id).all()
        assert len(versions) == 1
        assert versions[0].version_number == 1
        assert versions[0].snapshot['notes'] == 'Updated notes'
        assert versions[0].snapshot['planned_animal_count'] == 25


def test_update_workplan_increments_version(test_app, db_session, workplan_service, workplan_setup):
    """
    GIVEN un workplan avec une version existante
    WHEN update_workplan est appelé une deuxième fois
    THEN la version doit être incrémentée à 2.
    """
    with test_app.app_context():
        workplan = workplan_setup['workplan']
        admin_user = workplan_setup['admin_user']

        base_state = {
            'study_start_date': None,
            'expected_dob': None,
            'notes': 'First update',
            'planned_animal_count': 20,
            'events': [],
        }

        workplan_service.update_workplan(workplan, base_state, admin_user, 'First')
        db_session.flush()

        base_state['notes'] = 'Second update'
        workplan_service.update_workplan(workplan, base_state, admin_user, 'Second')
        db_session.flush()

        versions = WorkplanVersion.query.filter_by(workplan_id=workplan.id).all()
        assert len(versions) == 2
        version_numbers = sorted([v.version_number for v in versions])
        assert version_numbers == [1, 2]


def test_update_workplan_updates_fields(test_app, db_session, workplan_service, workplan_setup):
    """
    GIVEN un workplan existant
    WHEN update_workplan est appelé avec de nouvelles valeurs
    THEN les champs du workplan doivent être mis à jour.
    """
    with test_app.app_context():
        workplan = workplan_setup['workplan']
        admin_user = workplan_setup['admin_user']

        start_date = date.today() + timedelta(days=14)
        new_state = {
            'study_start_date': start_date.isoformat(),
            'expected_dob': None,
            'notes': 'New notes content',
            'planned_animal_count': 50,
            'events': [],
        }

        workplan_service.update_workplan(workplan, new_state, admin_user)
        db_session.flush()

        assert workplan.notes == 'New notes content'
        assert workplan.planned_animal_count == 50
        assert workplan.study_start_date == start_date


def test_update_workplan_creates_events(test_app, db_session, workplan_service, workplan_setup):
    """
    GIVEN un workplan existant
    WHEN update_workplan est appelé avec des événements
    THEN les WorkplanEvents doivent être créés.
    """
    with test_app.app_context():
        workplan = workplan_setup['workplan']
        admin_user = workplan_setup['admin_user']
        protocol = workplan_setup['protocol']

        new_state = {
            'study_start_date': None,
            'expected_dob': None,
            'notes': '',
            'planned_animal_count': 20,
            'events': [
                {
                    'offset_days': 0,
                    'protocol_id': protocol.id,
                    'event_name': 'Baseline',
                    'assigned_to_id': None,
                },
                {
                    'offset_days': 7,
                    'protocol_id': protocol.id,
                    'event_name': 'Week 1',
                    'assigned_to_id': None,
                },
            ],
        }

        workplan_service.update_workplan(workplan, new_state, admin_user)
        db_session.flush()

        events = WorkplanEvent.query.filter_by(workplan_id=workplan.id).all()
        assert len(events) == 2
        offset_days = sorted([e.offset_days for e in events])
        assert offset_days == [0, 7]


# ---------------------------------------------------------------------------
# Tests de snapshot
# ---------------------------------------------------------------------------

def test_snapshot_events_sorted_by_offset(test_app, db_session, workplan_service, workplan_setup):
    """
    GIVEN des événements dans un ordre non trié
    WHEN update_workplan est appelé
    THEN le snapshot doit contenir les événements triés par offset_days.
    """
    with test_app.app_context():
        workplan = workplan_setup['workplan']
        admin_user = workplan_setup['admin_user']
        protocol = workplan_setup['protocol']

        new_state = {
            'study_start_date': None,
            'expected_dob': None,
            'notes': '',
            'planned_animal_count': 20,
            'events': [
                {'offset_days': 14, 'protocol_id': protocol.id, 'event_name': 'Week 2', 'assigned_to_id': None},
                {'offset_days': 0, 'protocol_id': protocol.id, 'event_name': 'Baseline', 'assigned_to_id': None},
                {'offset_days': 7, 'protocol_id': protocol.id, 'event_name': 'Week 1', 'assigned_to_id': None},
            ],
        }

        workplan_service.update_workplan(workplan, new_state, admin_user)
        db_session.flush()

        version = WorkplanVersion.query.filter_by(workplan_id=workplan.id).first()
        snapshot_offsets = [e['offset_days'] for e in version.snapshot['events']]
        assert snapshot_offsets == sorted(snapshot_offsets), "Les événements du snapshot doivent être triés"


# ---------------------------------------------------------------------------
# Tests de statut
# ---------------------------------------------------------------------------

def test_workplan_status_transitions(test_app, db_session, workplan_setup):
    """
    GIVEN un workplan en DRAFT
    WHEN le statut est changé en ACTIVE puis COMPLETED
    THEN les transitions doivent être valides.
    """
    with test_app.app_context():
        workplan = workplan_setup['workplan']

        assert workplan.status == WorkplanStatus.DRAFT

        workplan.status = WorkplanStatus.ACTIVE
        db_session.flush()
        assert workplan.status == WorkplanStatus.ACTIVE

        workplan.status = WorkplanStatus.COMPLETED
        db_session.flush()
        assert workplan.status == WorkplanStatus.COMPLETED


def test_workplan_event_status_default(test_app, db_session, workplan_setup):
    """
    GIVEN un WorkplanEvent créé sans statut explicite
    WHEN il est sauvegardé
    THEN son statut doit être PLANNED par défaut.
    """
    with test_app.app_context():
        workplan = workplan_setup['workplan']
        protocol = workplan_setup['protocol']

        event = WorkplanEvent(
            workplan_id=workplan.id,
            protocol_id=protocol.id,
            offset_days=0,
        )
        db_session.add(event)
        db_session.flush()

        assert event.status == WorkplanEventStatus.PLANNED

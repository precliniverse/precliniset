import json
from datetime import date, datetime, timedelta

import pytest

from app import db
from app.models import AnimalModel, Project, Workplan, WorkplanStatus


def login(client, email, password):
    return client.post('/auth/login', data=dict(
        email=email,
        password=password
    ), follow_redirects=True)

def logout(client):
    return client.get('/auth/logout', follow_redirects=True)

@pytest.fixture
def logged_in_admin_client(test_client, init_database):
    login(test_client, 'team1admin@test.com', 'password')
    yield test_client
    logout(test_client)

def test_save_workplan_planned_animal_count_in_draft_mode(db_session, logged_in_admin_client, init_database):
    """
    Test that the planned_animal_count is saved correctly when a workplan in DRAFT mode is updated.
    """
    admin_user = init_database['team1_admin']
    project = init_database['proj1']
    animal_model = init_database['animal_model']

    # Create a workplan in DRAFT mode
    initial_animal_count = 5
    workplan = Workplan(
        project_id=project.id,
        name='Draft Workplan for Animals',
        animal_model_id=animal_model.id,
        planned_animal_count=initial_animal_count,
        status=WorkplanStatus.DRAFT,
        notes='Initial draft notes.'
    )
    db_session.add(workplan)
    db_session.commit()
    db_session.refresh(workplan)

    assert workplan.planned_animal_count == initial_animal_count

    # Simulate an update with a new planned_animal_count
    updated_animal_count = 10
    update_data = {
        'study_start_date': (date.today() + timedelta(days=30)).isoformat(),
        'expected_dob': (date.today() - timedelta(days=60)).isoformat(),
        'notes': 'Updated draft notes.',
        'planned_animal_count': updated_animal_count,
        'events': [] # No events for simplicity in this test
    }

    response = logged_in_admin_client.post(
        f'/workplans/{workplan.id}',
        data=json.dumps(update_data),
        content_type='application/json'
    )
    
    assert response.status_code == 200
    response_data = json.loads(response.data)
    assert response_data['success'] == True
    assert 'Workplan saved successfully.' in response_data['message']

    # Fetch the workplan again from the database to verify the update
    updated_workplan = db_session.get(Workplan, workplan.id)
    assert updated_workplan.planned_animal_count == updated_animal_count
    assert updated_workplan.notes == 'Updated draft notes.'
    assert updated_workplan.status == WorkplanStatus.DRAFT # Ensure status remains DRAFT


# tests/test_groups_api_simple.py
import pytest
import json
from datetime import datetime, timezone
from app.models import ExperimentalGroup, Animal, Project, Team

def test_server_side_groups_tooltip_refactor(test_client, db_session, init_database, api_token):
    """
    Test that the server-side groups API correctly retrieves euthanasia reason
    from the flattened animal dictionary, ensuring the refactor didn't break functionality.
    """
    # 1. Setup Data
    project = init_database['proj1']
    admin = init_database['team1_admin']
    
    # Login handled by token
    # client is standard test_client
    
    # Create a group with a dead animal using the Service to ensure integrity
    from app.services.group_service import GroupService
    service = GroupService()
    
    animal_data = [{
        "uid": "A-Dead",
        "date_of_birth": "2023-01-01",
        "status": "dead",
        "euthanasia_reason": "Limit reached",
        "severity": "Moderate"
    }]
    
    group = service.create_group(
        name="Tooltip Test Group", 
        project_id=project.id, 
        team_id=project.team_id, 
        owner_id=admin.id,
        model_id=init_database['animal_model'].id,
        animal_data=animal_data
    )
    
    # 2. Call the API
    # Endpoint: /api/server_side_groups/server_side
    # Params matching the datatable request
    response = test_client.get(
        '/api/v1/server_side_groups/server_side',
        headers={'Authorization': f'Bearer {api_token}'},
        query_string={
            'project_id': project.id,
            'draw': 1,
            'start': 0,
            'length': 10
        }
    )
    
    assert response.status_code == 200
    data = response.get_json()
    
    # 3. Verify Response
    assert data['recordsTotal'] >= 1
    
    # Find our specific group in the results
    target_group = next((item for item in data['data'] if item['id'] == group.id), None)
    assert target_group is not None
    
    # Check animal count HTML for the tooltip
    animal_count_html = target_group['animal_count']
    
    # Should contain the tooltip attribute
    assert 'data-bs-toggle="tooltip"' in animal_count_html
    
    # Should contain the euthanasia reason (this proves flattened access works)
    # The reason "Limit reached" was in measurements dict, now flattened in to_dict()
    # and accessed directly by the API.
    assert "Limit reached" in animal_count_html
    
    # Verify the tooltip formatting
    assert "Dead animals (1):" in animal_count_html
    assert "A-Dead: Limit reached" in animal_count_html

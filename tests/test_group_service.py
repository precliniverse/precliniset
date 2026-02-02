import pytest
from app import db
from app.services.group_service import GroupService
from app.models import ExperimentalGroup, Animal, Analyte, AnalyteDataType, AnimalModelAnalyteAssociation

def test_create_group_refactored(db_session, init_database):
    """Test that create_group populates the Animal table correctly."""
    service = GroupService()
    
    # Setup Data from fixture
    project = init_database['proj1']
    model = init_database['animal_model']
    owner = init_database['team1_admin']
    
    # Standardize analytes to ensure 'weight' is a known field to avoid filtering if stricly enforced
    # (Though current implementation might be permissive, good to be explicit)
    
    animals_input = [
        {'ID': 'A1', 'Date of Birth': '2023-01-01', 'sex': 'Male', 'Weight': 20.5, 'Comment': 'Healthy'},
        {'ID': 'A2', 'Date of Birth': '2023-01-02', 'sex': 'Female', 'Weight': 18.2, 'Comment': 'Small'}
    ]
    
    # Action: Create Group
    group = service.create_group(
        name="New Service Group", 
        project_id=project.id, 
        team_id=project.team_id, 
        owner_id=owner.id,
        model_id=model.id,
        animal_data=animals_input
    )
    
    # Assertions: Group Created
    assert group.id is not None
    assert group.name == "New Service Group"
    
    # Assertions: Animals Entities Created
    db_animals = Animal.query.filter_by(group_id=group.id).order_by(Animal.uid).all()
    assert len(db_animals) == 2
    
    a1 = db_animals[0]
    assert a1.uid == 'A1'
    assert str(a1.date_of_birth) == '2023-01-01'
    assert a1.sex == 'Male'
    
    # Assertions: Measurements JSON
    # Note: 'id', 'date of birth', 'sex' should NOT be in measurements if stripped, 
    # but other fields like 'Weight' and 'Comment' SHOULD be.
    assert a1.measurements.get('Weight') == 20.5
    assert a1.measurements.get('Comment') == 'Healthy'
    
    # Assertions: Backward Compatibility (animal_data property)
    # The property should merge static fields + measurements
    output_data = group.animal_data
    assert len(output_data) == 2
    assert output_data[0]['ID'] == 'A1'
    assert output_data[0]['Weight'] == 20.5
    assert output_data[0]['sex'] == 'Male'

def test_save_group_data_updates_animals(db_session, init_database):
    """Test that save_group_data updates existing Animal entities."""
    service = GroupService()
    project = init_database['proj1']
    model = init_database['animal_model']
    owner = init_database['team1_admin']
    
    # Initial Create
    animals_input = [{'ID': 'B1', 'Date of Birth': '2023-01-01', 'sex': 'Male', 'Val': 10}]
    group = service.create_group("Update Test Group", project.id, project.team_id, owner.id, model.id, animals_input)
    
    # Verify Initial State
    animal = Animal.query.filter_by(group_id=group.id, uid='B1').first()
    assert animal.measurements['Val'] == 10
    
    # Update Data
    updated_data = [{'ID': 'B1', 'Date of Birth': '2023-01-01', 'sex': 'Male', 'Val': 99, 'NewField': 'Added'}]
    
    # Action: Save Group Data
    service.save_group_data(group, updated_data)
    
    # Assertions: Verify Update in DB
    db.session.refresh(animal)
    assert animal.measurements['Val'] == 99
    assert animal.measurements['NewField'] == 'Added'

def test_sanitization(db_session, init_database):
    """Test XSS sanitization in AnimalSchema."""
    from app.schemas.animal import AnimalSchema
    
    # Test valid
    a = AnimalSchema(ID=' A1 ', **{'Date of Birth': '2023-01-01'}, sex='Male')
    assert a.animal_id == 'A1' # Stripped
    
    # Test Sanitization
    bad_input = "<script>alert(1)</script>"
    a = AnimalSchema(ID=bad_input, **{'Date of Birth': '2023-01-01'}, sex=bad_input)
    
    import html
    expected = html.escape(bad_input)
    assert a.animal_id == expected
    assert a.sex == expected

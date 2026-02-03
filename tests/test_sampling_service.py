# tests/test_sampling_service.py
from datetime import date

import pytest

from app.models import Sample, SampleStatus, SampleType
from app.services.sampling_service import SamplingService


def test_log_batch_samples(db_session, init_database):
    """
    GIVEN a group and a batch sampling request
    WHEN log_batch_samples is called
    THEN samples should be created in the database with correct attributes
    """
    # 1. Setup
    service = SamplingService()
    group = init_database['group1']
    
    # Ensure group has animal entities for the indices we will use
    from app.models import Animal
    db_session.add(Animal(uid='Mouse-1', group_id=group.id, status='alive'))
    db_session.add(Animal(uid='Mouse-2', group_id=group.id, status='alive'))
    db_session.commit()
    
    # Mock the form data structure coming from the frontend
    common_details = {
        'collection_date': date.today().isoformat(),
        'is_terminal_event': False,
        'status': 'STORED',
        'event_notes': 'Test Batch Log'
    }
    
    # Template for a blood sample
    sample_set = [{
        'sample_type': 'BLOOD',
        'blood_volume': 50.0,
        'blood_volume_unit': 'µL',
        # 'anticoagulant_id': None # Optional
    }]
    
    # Apply to both animals
    animal_indices = [0, 1]

    # 2. Action
    count, errors = service.log_batch_samples(group, common_details, sample_set, animal_indices)

    # 3. Assertions
    assert len(errors) == 0, f"Errors occurred: {errors}"
    assert count == 2
    
    # Verify DB records
    samples = Sample.query.filter_by(experimental_group_id=group.id).all()
    assert len(samples) == 2
    
    sample_1 = samples[0]
    assert sample_1.sample_type == SampleType.BLOOD
    assert sample_1.volume == 50.0
    assert sample_1.volume_unit == 'µL'
    assert sample_1.status == SampleStatus.STORED
    assert sample_1.notes == 'Test Batch Log'
    assert sample_1.animal_index_in_group in [0, 1]

def test_log_batch_samples_terminal(db_session, init_database):
    """
    GIVEN a terminal sampling event
    WHEN log_batch_samples is called
    THEN the animals in the group should be marked as dead
    """
    service = SamplingService()
    group = init_database['group1']
    from app.models import Animal
    db_session.add(Animal(uid='Mouse-1', group_id=group.id, status='alive'))
    db_session.add(Animal(uid='Mouse-2', group_id=group.id, status='alive'))
    db_session.commit()

    common_details = {
        'collection_date': date.today().isoformat(),
        'is_terminal_event': True, # <--- Terminal
        'status': 'STORED'
    }
    
    sample_set = [{'sample_type': 'BLOOD'}]
    animal_indices = [0] # Only Mouse-1

    service.log_batch_samples(group, common_details, sample_set, animal_indices)
    
    # Refresh group from DB to check JSON update - No longer JSON, need to check Entities
    db_session.expire_all()
    
    mouse1 = Animal.query.filter_by(group_id=group.id, uid='Mouse-1').first()
    mouse2 = Animal.query.filter_by(group_id=group.id, uid='Mouse-2').first()
    
    assert mouse1.status == 'dead'
    assert mouse1.measurements.get('death_date') == date.today().isoformat()
    assert mouse2.status == 'alive' # Mouse-2 should be untouched
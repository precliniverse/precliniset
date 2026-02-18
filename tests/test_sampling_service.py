# tests/test_sampling_service.py
"""
Tests unitaires du SamplingService.
Vérifie la création de lots d'échantillons et les validations associées.
"""
from datetime import date

import pytest

from app.models import Animal, Sample, SampleStatus, SampleType
from app.services.sampling_service import SamplingService


def test_log_batch_samples(db_session, init_database):
    """
    GIVEN un groupe avec 2 animaux et une requête de sampling en lot
    WHEN log_batch_samples est appelé
    THEN 2 échantillons doivent être créés avec les bons attributs.
    """
    service = SamplingService()
    group = init_database['group1']

    db_session.add(Animal(uid='Mouse-1', display_id='Mouse 1', group_id=group.id, status='alive'))
    db_session.add(Animal(uid='Mouse-2', display_id='Mouse 2', group_id=group.id, status='alive'))
    db_session.flush()
    
    common_details = {
        'collection_date': date.today().isoformat(),
        'is_terminal_event': False,
        'status': 'STORED',
        'event_notes': 'Test Batch Log',
    }

    sample_set = [{
        'sample_type': 'BLOOD',
        'blood_volume': 50.0,
        'blood_volume_unit': 'µL',
    }]

    animal_indices = [0, 1]

    count, errors = service.log_batch_samples(group, common_details, sample_set, animal_indices)

    assert len(errors) == 0, f"Des erreurs sont survenues : {errors}"
    assert count == 2

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
    GIVEN un événement de sampling terminal
    WHEN log_batch_samples est appelé avec is_terminal_event=True
    THEN l'animal concerné doit être marqué comme mort.
    """
    service = SamplingService()
    group = init_database['group1']

    db_session.add(Animal(uid='Mouse-T1', display_id='Mouse T1', group_id=group.id, status='alive'))
    db_session.add(Animal(uid='Mouse-T2', display_id='Mouse T2', group_id=group.id, status='alive'))
    db_session.flush()

    common_details = {
        'collection_date': date.today().isoformat(),
        'is_terminal_event': True,
        'status': 'STORED',
    }

    sample_set = [{'sample_type': 'BLOOD'}]
    animal_indices = [0]  # Seulement Mouse-T1

    service.log_batch_samples(group, common_details, sample_set, animal_indices)

    db_session.expire_all()

    mouse1 = Animal.query.filter_by(group_id=group.id, uid='Mouse-T1').first()
    mouse2 = Animal.query.filter_by(group_id=group.id, uid='Mouse-T2').first()

    assert mouse1.status == 'dead'
    assert mouse1.measurements.get('death_date') == date.today().isoformat()
    assert mouse2.status == 'alive'

# tests/test_analysis_service.py
"""
Tests unitaires de l'AnalysisService.
Vérifie la préparation des DataFrames et l'intégration avec StatisticsService.
"""
from datetime import date

import pytest

from app.models import (
    Analyte, AnalyteDataType, Animal, AnimalModel, DataTable,
    ExperimentalGroup, ExperimentDataRow, Project, ProtocolModel, Team,
)
from app.services.analysis_service import AnalysisService


@pytest.fixture
def analysis_service():
    return AnalysisService()


@pytest.fixture
def analysis_setup(db_session, init_database):
    """
    Crée un jeu de données complet pour tester l'AnalysisService :
    - 1 groupe avec 3 animaux
    - 1 protocole avec 2 analytes (Weight FLOAT, Genotype TEXT)
    - 1 datatable avec des données pour chaque animal
    """
    project = init_database['proj1']
    team = init_database['team1']
    admin_user = init_database['team1_admin']
    animal_model = init_database['animal_model']

    # Analytes
    analyte_weight = Analyte(name='Weight', data_type=AnalyteDataType.FLOAT, unit='g')
    analyte_genotype = Analyte(name='Genotype', data_type=AnalyteDataType.TEXT)
    db_session.add_all([analyte_weight, analyte_genotype])
    db_session.flush()

    # Protocole avec associations
    protocol = ProtocolModel(name='Analysis Protocol')
    db_session.add(protocol)
    db_session.flush()

    from app.models import ProtocolAnalyteAssociation
    db_session.add(ProtocolAnalyteAssociation(
        protocol_model_id=protocol.id, analyte_id=analyte_weight.id, order=1
    ))
    db_session.add(ProtocolAnalyteAssociation(
        protocol_model_id=protocol.id, analyte_id=analyte_genotype.id, order=2
    ))
    db_session.flush()

    # Groupe expérimental
    group = ExperimentalGroup(
        id='analysis_group_001',
        name='Analysis Group',
        project_id=project.id,
        model_id=animal_model.id,
        owner_id=admin_user.id,
        team_id=team.id,
    )
    db_session.add(group)
    db_session.flush()

    # Animaux
    animals = []
    for i in range(3):
        animal = Animal(
            uid=f'ANIM_{i:03d}',
            display_id=f'Animal {i+1}',
            group_id=group.id,
            status='alive',
            date_of_birth=date(2023, 1, 1),
            measurements={'Genotype': 'WT' if i < 2 else 'KO'},
        )
        db_session.add(animal)
        animals.append(animal)
    db_session.flush()

    # DataTable
    dt = DataTable(
        group_id=group.id,
        protocol_id=protocol.id,
        date='2024-01-15',
        creator_id=admin_user.id,
    )
    db_session.add(dt)
    db_session.flush()

    # Données expérimentales
    weights = [25.3, 27.1, 22.8]
    for animal, weight in zip(animals, weights):
        row = ExperimentDataRow(
            data_table_id=dt.id,
            animal_id=animal.id,
            row_data={'Weight': weight},
        )
        db_session.add(row)
    db_session.flush()

    return {
        'group': group,
        'protocol': protocol,
        'data_table': dt,
        'animals': animals,
        'analyte_weight': analyte_weight,
        'analyte_genotype': analyte_genotype,
        'weights': weights,
    }


# ---------------------------------------------------------------------------
# Tests de prepare_dataframe
# ---------------------------------------------------------------------------

def test_prepare_dataframe_returns_dataframe(test_app, db_session, analysis_service, analysis_setup):
    """
    GIVEN une DataTable avec des données
    WHEN prepare_dataframe est appelé
    THEN un DataFrame non vide doit être retourné.
    """
    with test_app.app_context():
        dt = analysis_setup['data_table']
        df = analysis_service.prepare_dataframe(dt)

    assert df is not None
    assert not df.empty


def test_prepare_dataframe_correct_row_count(test_app, db_session, analysis_service, analysis_setup):
    """
    GIVEN une DataTable avec 3 animaux
    WHEN prepare_dataframe est appelé
    THEN le DataFrame doit avoir 3 lignes.
    """
    with test_app.app_context():
        dt = analysis_setup['data_table']
        df = analysis_service.prepare_dataframe(dt)

    assert len(df) == 3


def test_prepare_dataframe_contains_protocol_analytes(test_app, db_session, analysis_service, analysis_setup):
    """
    GIVEN une DataTable avec un protocole contenant 'Weight' et 'Genotype'
    WHEN prepare_dataframe est appelé
    THEN le DataFrame doit contenir ces colonnes.
    """
    with test_app.app_context():
        dt = analysis_setup['data_table']
        df = analysis_service.prepare_dataframe(dt)

    assert 'Weight' in df.columns
    assert 'Genotype' in df.columns


def test_prepare_dataframe_correct_values(test_app, db_session, analysis_service, analysis_setup):
    """
    GIVEN des données expérimentales connues
    WHEN prepare_dataframe est appelé
    THEN les valeurs du DataFrame doivent correspondre aux données insérées.
    """
    with test_app.app_context():
        dt = analysis_setup['data_table']
        df = analysis_service.prepare_dataframe(dt)

    expected_weights = sorted(analysis_setup['weights'])
    actual_weights = sorted(df['Weight'].dropna().tolist())
    assert actual_weights == pytest.approx(expected_weights, abs=0.01)


def test_prepare_dataframe_contains_animal_metadata(test_app, db_session, analysis_service, analysis_setup):
    """
    GIVEN des animaux avec des métadonnées (uid, display_id, sex)
    WHEN prepare_dataframe est appelé
    THEN le DataFrame doit contenir les colonnes de métadonnées.
    """
    with test_app.app_context():
        dt = analysis_setup['data_table']
        df = analysis_service.prepare_dataframe(dt)

    assert 'uid' in df.columns or 'display_id' in df.columns


def test_prepare_dataframe_empty_datatable(test_app, db_session, analysis_service, init_database):
    """
    GIVEN une DataTable sans données expérimentales
    WHEN prepare_dataframe est appelé
    THEN le DataFrame doit être vide ou ne contenir que les métadonnées animales.
    """
    with test_app.app_context():
        project = init_database['proj1']
        team = init_database['team1']
        admin_user = init_database['team1_admin']
        animal_model = init_database['animal_model']

        protocol = ProtocolModel(name='Empty Protocol')
        db_session.add(protocol)
        db_session.flush()

        group = ExperimentalGroup(
            id='empty_group_001',
            name='Empty Group',
            project_id=project.id,
            model_id=animal_model.id,
            owner_id=admin_user.id,
            team_id=team.id,
        )
        db_session.add(group)
        db_session.flush()

        dt = DataTable(
            group_id=group.id,
            protocol_id=protocol.id,
            date='2024-01-15',
            creator_id=admin_user.id,
        )
        db_session.add(dt)
        db_session.flush()

        df = analysis_service.prepare_dataframe(dt)

    # Sans animaux, le DataFrame doit être vide
    assert df is not None
    assert len(df) == 0


# ---------------------------------------------------------------------------
# Tests d'intégration AnalysisService + StatisticsService
# ---------------------------------------------------------------------------

def test_analysis_service_has_stats_service(analysis_service):
    """
    GIVEN un AnalysisService instancié
    THEN il doit avoir un StatisticsService attaché.
    """
    from app.services.statistics_service import StatisticsService
    assert isinstance(analysis_service.stats_service, StatisticsService)


def test_full_analysis_pipeline(test_app, db_session, analysis_service, analysis_setup):
    """
    GIVEN une DataTable avec des données numériques
    WHEN prepare_dataframe + execute_test sont appelés
    THEN le résultat doit être un dict valide sans erreur.
    """
    with test_app.app_context():
        dt = analysis_setup['data_table']
        df = analysis_service.prepare_dataframe(dt)

        # Exécuter un test statistique simple (summary_only car 3 animaux = pas assez pour t-test)
        result = analysis_service.stats_service.execute_test(
            df, 'summary_only', 'Weight', ['Genotype'],
            is_repeated=False, subject_id_col='id',
        )

    assert result is not None
    assert isinstance(result, dict)
    assert result['error'] is None

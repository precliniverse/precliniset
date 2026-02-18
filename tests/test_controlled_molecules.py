# tests/test_controlled_molecules.py
"""
Tests unitaires du MoleculeService et du modèle ControlledMolecule.
Vérifie l'enregistrement des usages et les contraintes du modèle.
"""
import json
from datetime import date

import pytest

from app.models import (
    ControlledMolecule, DataTable, DataTableMoleculeUsage,
    ExperimentalGroup, ProtocolModel,
)
from app.services.molecule_service import MoleculeService


@pytest.fixture
def molecule_service():
    return MoleculeService()


@pytest.fixture
def molecule_setup(db_session, init_database):
    """
    Crée un jeu de données pour tester le MoleculeService :
    - 1 molécule contrôlée
    - 1 datatable
    """
    team = init_database['team1']
    admin_user = init_database['team1_admin']
    group = init_database['group1']

    # Molécule contrôlée
    molecule = ControlledMolecule(
        name='Ketamine',
        cas_number='6740-88-1',
        team_id=team.id,
        stock_quantity=500.0,
        unit='mL',
        is_active=True,
    )
    db_session.add(molecule)
    db_session.flush()

    # Protocole et DataTable
    protocol = ProtocolModel(name='Molecule Test Protocol')
    db_session.add(protocol)
    db_session.flush()

    dt = DataTable(
        group_id=group.id,
        protocol_id=protocol.id,
        date=date.today().isoformat(),
        creator_id=admin_user.id,
    )
    db_session.add(dt)
    db_session.flush()

    return {
        'molecule': molecule,
        'data_table': dt,
        'admin_user': admin_user,
        'team': team,
    }


# ---------------------------------------------------------------------------
# Tests du modèle ControlledMolecule
# ---------------------------------------------------------------------------

def test_controlled_molecule_creation(db_session, init_database):
    """
    GIVEN les données d'une molécule contrôlée
    WHEN la molécule est créée
    THEN elle doit être persistée avec les bons attributs.
    """
    team = init_database['team1']
    molecule = ControlledMolecule(
        name='Xylazine',
        cas_number='7361-61-7',
        team_id=team.id,
        stock_quantity=250.0,
        unit='mL',
        is_active=True,
    )
    db_session.add(molecule)
    db_session.flush()

    assert molecule.id is not None
    assert molecule.name == 'Xylazine'
    assert molecule.cas_number == '7361-61-7'
    assert molecule.stock_quantity == 250.0
    assert molecule.unit == 'mL'
    assert molecule.is_active is True
    assert molecule.team_id == team.id


def test_controlled_molecule_default_active(db_session, init_database):
    """
    GIVEN une molécule créée sans spécifier is_active
    WHEN elle est persistée
    THEN is_active doit être True par défaut.
    """
    team = init_database['team1']
    molecule = ControlledMolecule(
        name='Isoflurane',
        team_id=team.id,
        stock_quantity=100.0,
        unit='mL',
    )
    db_session.add(molecule)
    db_session.flush()

    assert molecule.is_active is True


def test_controlled_molecule_team_isolation(db_session, init_database):
    """
    GIVEN deux équipes avec des molécules différentes
    WHEN on filtre par team_id
    THEN chaque équipe ne voit que ses propres molécules.
    """
    team1 = init_database['team1']
    team2 = init_database['team2']

    mol1 = ControlledMolecule(name='Mol Team1', team_id=team1.id, stock_quantity=100.0, unit='mL')
    mol2 = ControlledMolecule(name='Mol Team2', team_id=team2.id, stock_quantity=50.0, unit='mL')
    db_session.add_all([mol1, mol2])
    db_session.flush()

    team1_molecules = ControlledMolecule.query.filter_by(team_id=team1.id).all()
    team2_molecules = ControlledMolecule.query.filter_by(team_id=team2.id).all()

    team1_names = [m.name for m in team1_molecules]
    team2_names = [m.name for m in team2_molecules]

    assert 'Mol Team1' in team1_names
    assert 'Mol Team2' not in team1_names
    assert 'Mol Team2' in team2_names
    assert 'Mol Team1' not in team2_names


# ---------------------------------------------------------------------------
# Tests du MoleculeService.record_usage
# ---------------------------------------------------------------------------

def test_record_usage_creates_entry(test_app, db_session, molecule_service, molecule_setup):
    """
    GIVEN une molécule et une datatable
    WHEN record_usage est appelé
    THEN une entrée DataTableMoleculeUsage doit être créée.
    """
    with test_app.app_context():
        molecule = molecule_setup['molecule']
        dt = molecule_setup['data_table']
        admin_user = molecule_setup['admin_user']

        animal_ids = [1, 2, 3]
        usage = molecule_service.record_usage(
            data_table_id=dt.id,
            molecule_id=molecule.id,
            volume_used=5.0,
            animal_ids_json=json.dumps(animal_ids),
            recorded_by_id=admin_user.id,
            notes='Test usage',
        )
        db_session.flush()

    assert usage.id is not None
    assert usage.data_table_id == dt.id
    assert usage.molecule_id == molecule.id
    assert usage.volume_used == 5.0
    assert usage.animal_ids == animal_ids
    assert usage.number_of_animals == 3
    assert usage.notes == 'Test usage'
    assert usage.recorded_by_id == admin_user.id


def test_record_usage_empty_animal_ids(test_app, db_session, molecule_service, molecule_setup):
    """
    GIVEN une liste d'animaux vide
    WHEN record_usage est appelé
    THEN number_of_animals doit être 0.
    """
    with test_app.app_context():
        molecule = molecule_setup['molecule']
        dt = molecule_setup['data_table']
        admin_user = molecule_setup['admin_user']

        usage = molecule_service.record_usage(
            data_table_id=dt.id,
            molecule_id=molecule.id,
            volume_used=2.5,
            animal_ids_json=json.dumps([]),
            recorded_by_id=admin_user.id,
        )
        db_session.flush()

    assert usage.number_of_animals == 0
    assert usage.animal_ids == []


def test_record_usage_null_animal_ids(test_app, db_session, molecule_service, molecule_setup):
    """
    GIVEN animal_ids_json=None
    WHEN record_usage est appelé
    THEN animal_ids doit être une liste vide et number_of_animals=0.
    """
    with test_app.app_context():
        molecule = molecule_setup['molecule']
        dt = molecule_setup['data_table']
        admin_user = molecule_setup['admin_user']

        usage = molecule_service.record_usage(
            data_table_id=dt.id,
            molecule_id=molecule.id,
            volume_used=1.0,
            animal_ids_json=None,
            recorded_by_id=admin_user.id,
        )
        db_session.flush()

    assert usage.animal_ids == []
    assert usage.number_of_animals == 0


def test_record_usage_without_notes(test_app, db_session, molecule_service, molecule_setup):
    """
    GIVEN un appel à record_usage sans notes
    WHEN l'usage est créé
    THEN notes doit être None.
    """
    with test_app.app_context():
        molecule = molecule_setup['molecule']
        dt = molecule_setup['data_table']
        admin_user = molecule_setup['admin_user']

        usage = molecule_service.record_usage(
            data_table_id=dt.id,
            molecule_id=molecule.id,
            volume_used=3.0,
            animal_ids_json=json.dumps([1]),
            recorded_by_id=admin_user.id,
        )
        db_session.flush()

    assert usage.notes is None


def test_multiple_usages_same_datatable(test_app, db_session, molecule_service, molecule_setup):
    """
    GIVEN une datatable avec plusieurs usages de molécules
    WHEN record_usage est appelé plusieurs fois
    THEN toutes les entrées doivent être créées.
    """
    with test_app.app_context():
        molecule = molecule_setup['molecule']
        dt = molecule_setup['data_table']
        admin_user = molecule_setup['admin_user']

        for i in range(3):
            molecule_service.record_usage(
                data_table_id=dt.id,
                molecule_id=molecule.id,
                volume_used=float(i + 1),
                animal_ids_json=json.dumps([i]),
                recorded_by_id=admin_user.id,
                notes=f'Usage {i}',
            )
        db_session.flush()

    usages = DataTableMoleculeUsage.query.filter_by(data_table_id=dt.id).all()
    assert len(usages) == 3
    volumes = sorted([u.volume_used for u in usages])
    assert volumes == [1.0, 2.0, 3.0]

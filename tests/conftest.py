# tests/conftest.py
"""
Configuration et fixtures partagées pour la suite de tests Precliniset.

Architecture des fixtures :
- test_app      : scope=module  — une seule app Flask par module de test
- test_client   : scope=module  — un seul client HTTP par module
- db_session    : scope=function — session transactionnelle isolée par test (rollback auto)
- init_database : scope=function — jeu de données standard (users, teams, projects, groups, EAs)
- logged_in_client / team1_admin_client / ... : clients HTTP pré-authentifiés
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import date, timedelta

from app import create_app, db
from app.config import TestingConfig
from app.models import (
    Analyte, AnalyteDataType, AnimalModel, APIToken,
    EthicalApproval, ExperimentalGroup, Permission,
    Project, ProjectTeamShare, Role, Team, TeamMembership,
    User, UserTeamRoleLink,
)
from app.services.admin_service import AdminService


# ---------------------------------------------------------------------------
# App & client
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def test_app():
    """Crée et configure une instance Flask pour chaque module de test."""
    app = create_app(TestingConfig)
    with app.app_context():
        db.create_all()
        yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture(scope='module')
def test_client(test_app):
    """Client HTTP Flask pour le module."""
    return test_app.test_client(use_cookies=True)


# ---------------------------------------------------------------------------
# Session transactionnelle isolée par test
# ---------------------------------------------------------------------------

@pytest.fixture(scope='function')
def db_session(test_app):
    """
    Fournit une session SQLAlchemy isolée par test via un SAVEPOINT (nested transaction).

    Stratégie :
    - On ouvre une transaction externe sur la connexion partagée.
    - On crée un SAVEPOINT (begin_nested) pour chaque test.
    - Après le test, on rollback jusqu'au SAVEPOINT → la DB est propre.
    - La transaction externe n'est jamais committée → aucune donnée ne persiste.

    Compatible SQLite in-memory + StaticPool (utilisé en TestingConfig).
    """
    with test_app.app_context():
        connection = db.engine.connect()
        trans = connection.begin()

        # Lier la session à cette connexion
        db.session.configure(bind=connection)

        nested = connection.begin_nested()

        yield db.session

        # Nettoyage : rollback du savepoint puis de la transaction externe
        db.session.remove()
        if nested.is_active:
            nested.rollback()
        trans.rollback()
        connection.close()


# ---------------------------------------------------------------------------
# Jeu de données standard
# ---------------------------------------------------------------------------

@pytest.fixture(scope='function')
def init_database(db_session):
    """
    Crée un jeu de données standard pour les tests :
    - 5 utilisateurs (super_admin, team1_admin, team1_member, team2_admin, no_team_user)
    - 2 équipes (Team One, Team Two)
    - 2 projets (un par équipe)
    - 1 modèle animal
    - 2 approbations éthiques (une par équipe)
    - 2 groupes expérimentaux (un par projet)
    """
    # Vider toutes les tables pour garantir un état propre
    for table in reversed(db.metadata.sorted_tables):
        db_session.execute(table.delete())

    # Peupler les permissions
    from app.permissions import AVAILABLE_PERMISSIONS
    for resource, actions in AVAILABLE_PERMISSIONS.items():
        for action in actions:
            db_session.add(Permission(resource=resource, action=action))
    db_session.flush()

    # --- Utilisateurs ---
    super_admin = User(email='superadmin@test.com', is_super_admin=True, email_confirmed=True)
    super_admin.set_password('password')

    team1_admin_user = User(email='team1admin@test.com', email_confirmed=True)
    team1_admin_user.set_password('password')

    team1_member_user = User(email='team1member@test.com', email_confirmed=True)
    team1_member_user.set_password('password')

    team2_admin_user = User(email='team2admin@test.com', email_confirmed=True)
    team2_admin_user.set_password('password')

    no_team_user = User(email='noteam@test.com', email_confirmed=True)
    no_team_user.set_password('password')

    db_session.add_all([
        super_admin, team1_admin_user, team1_member_user,
        team2_admin_user, no_team_user,
    ])

    # --- Équipes ---
    team1 = Team(name='Team One')
    team2 = Team(name='Team Two')
    db_session.add_all([team1, team2])
    db_session.flush()  # Obtenir les IDs

    # Rôles par défaut via AdminService
    admin_service = AdminService()
    team1_roles = admin_service._ensure_default_roles(team1)
    team2_roles = admin_service._ensure_default_roles(team2)

    # --- Memberships & rôles ---
    db_session.add(TeamMembership(user=team1_admin_user, team=team1))
    db_session.add(TeamMembership(user=team1_member_user, team=team1))
    db_session.add(TeamMembership(user=team2_admin_user, team=team2))

    db_session.add(UserTeamRoleLink(
        user_id=team1_admin_user.id, team_id=team1.id,
        role_id=team1_roles['team_admin'].id,
    ))
    db_session.add(UserTeamRoleLink(
        user_id=team1_member_user.id, team_id=team1.id,
        role_id=team1_roles['member'].id,
    ))
    db_session.add(UserTeamRoleLink(
        user_id=team2_admin_user.id, team_id=team2.id,
        role_id=team2_roles['team_admin'].id,
    ))

    # --- Projets ---
    proj1 = Project(
        name='Team 1 Project', team=team1,
        owner=team1_admin_user, slug='P0001',
    )
    proj2 = Project(
        name='Team 2 Project', team=team2,
        owner=team2_admin_user, slug='P0002',
    )
    db_session.add_all([proj1, proj2])

    # --- Modèle animal ---
    animal_model = AnimalModel(name='Test Mouse Model')
    db_session.add(animal_model)
    db_session.flush()

    # --- Approbations éthiques ---
    from app.models.enums import Severity
    ea1 = EthicalApproval(
        reference_number='EA-001',
        title='Test EA for Team 1',
        start_date=date.today() - timedelta(days=30),
        end_date=date.today() + timedelta(days=365),
        number_of_animals=100,
        overall_severity=Severity.MODERATE,
        team_id=team1.id,
    )
    ea2 = EthicalApproval(
        reference_number='EA-002',
        title='Test EA for Team 2',
        start_date=date.today(),
        end_date=date.today() + timedelta(days=100),
        number_of_animals=50,
        overall_severity=Severity.SEVERE,
        team_id=team2.id,
    )
    db_session.add_all([ea1, ea2])
    db_session.flush()

    # --- Groupes expérimentaux ---
    import random
    import string
    group1_id = ''.join(random.choices(string.ascii_letters + string.digits, k=40))
    group2_id = ''.join(random.choices(string.ascii_letters + string.digits, k=40))

    group1 = ExperimentalGroup(
        id=group1_id,
        name='Test Group 1',
        project_id=proj1.id,
        model_id=animal_model.id,
        owner_id=team1_admin_user.id,
        team_id=team1.id,
        ethical_approval_id=ea1.id,
    )
    group2 = ExperimentalGroup(
        id=group2_id,
        name='Test Group 2',
        project_id=proj2.id,
        model_id=animal_model.id,
        owner_id=team2_admin_user.id,
        team_id=team2.id,
    )
    db_session.add_all([group1, group2])
    db_session.flush()

    return {
        'super_admin': super_admin,
        'team1_admin': team1_admin_user,
        'team1_member': team1_member_user,
        'team2_admin': team2_admin_user,
        'no_team_user': no_team_user,
        'team1': team1,
        'team2': team2,
        'proj1': proj1,
        'proj2': proj2,
        'animal_model': animal_model,
        'group1': group1,
        'group2': group2,
        'ea1': ea1,
        'ea2': ea2,
    }


# ---------------------------------------------------------------------------
# Helpers d'authentification (importables depuis les modules de test)
# ---------------------------------------------------------------------------

def login(client, email, password):
    """Connecte un utilisateur via le formulaire de login."""
    client.get('/auth/logout', follow_redirects=True)
    return client.post(
        '/auth/login',
        data={'email': email, 'password': password},
        follow_redirects=True,
    )


def logout(client):
    """Déconnecte l'utilisateur courant."""
    return client.get('/auth/logout', follow_redirects=True)


# ---------------------------------------------------------------------------
# Clients HTTP pré-authentifiés
# ---------------------------------------------------------------------------

@pytest.fixture(scope='function')
def logged_in_client(test_client, init_database):
    """Client HTTP connecté en tant que super_admin."""
    login(test_client, 'superadmin@test.com', 'password')
    yield test_client
    logout(test_client)


@pytest.fixture(scope='function')
def team1_admin_client(test_client, init_database):
    """Client HTTP connecté en tant que team1_admin."""
    login(test_client, 'team1admin@test.com', 'password')
    yield test_client
    logout(test_client)


@pytest.fixture(scope='function')
def team1_member_client(test_client, init_database):
    """Client HTTP connecté en tant que team1_member."""
    login(test_client, 'team1member@test.com', 'password')
    yield test_client
    logout(test_client)


@pytest.fixture(scope='function')
def team2_admin_client(test_client, init_database):
    """Client HTTP connecté en tant que team2_admin."""
    login(test_client, 'team2admin@test.com', 'password')
    yield test_client
    logout(test_client)


# ---------------------------------------------------------------------------
# Tokens API
# ---------------------------------------------------------------------------

@pytest.fixture(scope='function')
def api_token(db_session, init_database):
    """Token API valide pour team1_admin."""
    user = init_database['team1_admin']
    token = APIToken(user_id=user.id, name='test_token')
    db_session.add(token)
    db_session.flush()
    return token.raw_token


@pytest.fixture(scope='function')
def super_admin_api_token(db_session, init_database):
    """Token API valide pour super_admin."""
    user = init_database['super_admin']
    token = APIToken(user_id=user.id, name='super_admin_test_token')
    db_session.add(token)
    db_session.flush()
    return token.raw_token

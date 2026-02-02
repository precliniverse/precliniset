from datetime import (date,  # Import date and timedelta for setting dates
                      timedelta)

import pytest

from app.extensions import db
from app.models import (Animal, AnimalModel, DataTable, EthicalApproval,
                        ExperimentalGroup, ExperimentDataRow, Project,
                        ProtocolModel, Severity, Team, User)
from app.models.teams import \
    ethical_approval_team_share  # Import the association table
from app.services.ethical_approval_service import (
    calculate_animals_used_for_ea, get_animals_available_for_ea,
    get_eligible_ethical_approvals, validate_ea_unshare_from_team,
    validate_group_ea_unlinking)

# Fixture setup (assuming conftest.py or similar is available for general setup)
# For specific tests, we'll create data within the test functions.

@pytest.fixture
def test_setup_data(test_app):
    with test_app.app_context():
        # Clean up database before starting tests to prevent IntegrityErrors
        db.session.query(ExperimentalGroup).delete()
        db.session.query(Animal).delete()
        db.session.query(DataTable).delete()
        db.session.query(ProtocolModel).delete()
        db.session.query(EthicalApproval).delete()
        db.session.query(Project).delete()
        db.session.query(User).delete()
        db.session.query(AnimalModel).delete()
        db.session.query(Team).delete()
        # Explicitly delete from the association table
        db.session.execute(ethical_approval_team_share.delete())
        db.session.commit()

        # Create Teams
        team1 = Team(name='Team Alpha')
        team2 = Team(name='Team Beta')
        db.session.add_all([team1, team2])
        db.session.commit()

        # Create Users
        user1 = User(email='user1@example.com')
        user1.set_password('password')
        user1.team_id = team1.id # Manually set for test fixture convenience
        user2 = User(email='user2@example.com')
        user2.set_password('password')
        user2.team_id = team2.id # Manually set for test fixture convenience
        db.session.add_all([user1, user2])
        db.session.commit()

        # Create AnimalModel
        am = AnimalModel(name='Mouse')
        db.session.add(am)
        db.session.commit()

        # Create EAs
        ea1 = EthicalApproval()
        ea1.reference_number = 'EA-001'
        ea1.title = 'Project Alpha EA'
        ea1.team_id = team1.id
        ea1.number_of_animals = 100
        ea1.overall_severity = Severity.MODERATE
        ea1.start_date = date.today()
        ea1.end_date = date.today() + timedelta(days=365)

        ea2 = EthicalApproval()
        ea2.reference_number = 'EA-002'
        ea2.title = 'Project Beta EA'
        ea2.team_id = team2.id
        ea2.number_of_animals = 50
        ea2.overall_severity = Severity.SEVERE
        ea2.start_date = date.today()
        ea2.end_date = date.today() + timedelta(days=365)

        ea3 = EthicalApproval()
        ea3.reference_number = 'EA-003'
        ea3.title = 'Shared EA'
        ea3.team_id = team1.id
        ea3.number_of_animals = 200
        ea3.overall_severity = Severity.LIGHT
        ea3.start_date = date.today()
        ea3.end_date = date.today() + timedelta(days=365)

        ea4 = EthicalApproval()
        ea4.reference_number = 'EA-004'
        ea4.title = 'Unlinked EA'
        ea4.team_id = team2.id
        ea4.number_of_animals = 10
        ea4.overall_severity = Severity.MODERATE
        ea4.start_date = date.today()
        ea4.end_date = date.today() + timedelta(days=365)
        db.session.add_all([ea1, ea2, ea3, ea4])
        db.session.commit()

        # Share ea3 with team2
        ea3.shared_with_teams.append(team2)
        db.session.commit()

        # Create Projects
        project1 = Project(name='Project Alpha', team_id=team1.id, owner_id=user1.id)
        project2 = Project(name='Project Beta', team_id=team2.id, owner_id=user2.id)
        db.session.add_all([project1, project2])
        db.session.commit()

        # Link EAs to projects
        project1.ethical_approvals.append(ea1)
        project1.ethical_approvals.append(ea3) # ea3 shared and linked to project1
        project2.ethical_approvals.append(ea2)
        db.session.commit()

        # Create Groups
        g1 = ExperimentalGroup(name='Group 1', project_id=project1.id, team_id=team1.id, owner_id=user1.id, model_id=am.id, ethical_approval_id=ea1.id, animal_data=[{'ID': 'A1', 'status': 'alive'}, {'ID': 'A2', 'status': 'alive'}]) # 2 animals
        g2 = ExperimentalGroup(name='Group 2', project_id=project1.id, team_id=team1.id, owner_id=user1.id, model_id=am.id, ethical_approval_id=ea3.id, animal_data=[{'ID': 'B1', 'status': 'alive'}, {'ID': 'B2', 'status': 'alive'}, {'ID': 'B3', 'status': 'alive'}]) # 3 animals
        g3 = ExperimentalGroup(name='Group 3', project_id=project2.id, team_id=team2.id, owner_id=user2.id, model_id=am.id, ethical_approval_id=ea2.id, animal_data=[{'ID': 'C1', 'status': 'alive'}]) # 1 animal
        g4 = ExperimentalGroup(name='Group 4', project_id=project2.id, team_id=team2.id, owner_id=user2.id, model_id=am.id, ethical_approval_id=ea3.id, animal_data=[{'ID': 'D1', 'status': 'alive'}, {'ID': 'D2', 'status': 'alive'}]) # 2 animals (team2 group linked to ea3)
        db.session.add_all([g1, g2, g3, g4])
        db.session.commit()

        # Create Protocols for severity tests
        proto_light = ProtocolModel()
        proto_light.name = 'Light Protocol'
        proto_light.severity = Severity.LIGHT
        proto_light.team_id = team1.id

        proto_mod = ProtocolModel()
        proto_mod.name = 'Moderate Protocol'
        proto_mod.severity = Severity.MODERATE
        proto_mod.team_id = team1.id

        proto_severe = ProtocolModel()
        proto_severe.name = 'Severe Protocol'
        proto_severe.severity = Severity.SEVERE
        proto_severe.team_id = team1.id
        db.session.add_all([proto_light, proto_mod, proto_severe])
        db.session.commit()

        # Create Datatables for group1 (linked to ea1, max_severity MODERATE)
        dt1 = DataTable(group_id=g1.id, protocol_id=proto_light.id, date='2023-01-01', creator_id=user1.id)
        dt2 = DataTable(group_id=g1.id, protocol_id=proto_mod.id, date='2023-01-02', creator_id=user1.id)
        db.session.add_all([dt1, dt2])
        db.session.commit()

        yield {
            'team1': team1, 'team2': team2,
            'user1': user1, 'user2': user2,
            'am': am,
            'ea1': ea1, 'ea2': ea2, 'ea3': ea3, 'ea4': ea4,
            'project1': project1, 'project2': project2,
            'g1': g1, 'g2': g2, 'g3': g3, 'g4': g4,
            'proto_light': proto_light, 'proto_mod': proto_mod, 'proto_severe': proto_severe,
            'dt1': dt1, 'dt2': dt2
        }

class TestEthicalApprovalService:
    def test_get_eligible_ethical_approvals_project_linked(self, test_setup_data, test_app):
        with test_app.app_context():
            project1 = test_setup_data['project1']
            team1 = test_setup_data['team1']
            eligible_eas = get_eligible_ethical_approvals(project1.id, team1.id)
            # No need for ea_refs, directly assert against the objects
            
            ea_titles_and_teams = [f"{ea.reference_number} - {ea.title} ({ea.owner_team.name})" for ea in eligible_eas]
            assert 'EA-001 - Project Alpha EA (Team Alpha)' in ea_titles_and_teams
            assert 'EA-003 - Shared EA (Team Alpha)' in ea_titles_and_teams
            assert len(eligible_eas) == 2

    def test_get_eligible_ethical_approvals_team_owned_only(self, test_setup_data, test_app):
        with test_app.app_context():
            # Create a project not linked to any EA, but get EAs for team1
            team1 = test_setup_data['team1']
            user1 = test_setup_data['user1']
            project_unlinked = Project(name='Unlinked Project', team_id=team1.id, owner_id=user1.id)
            db.session.add(project_unlinked)
            db.session.commit()

            eligible_eas = get_eligible_ethical_approvals(project_unlinked.id, team1.id)
            ea_titles_and_teams = [f"{ea.reference_number} - {ea.title} ({ea.owner_team.name})" for ea in eligible_eas]
            
            # Should get ea1, ea3 (owned by team1)
            assert 'EA-001 - Project Alpha EA (Team Alpha)' in ea_titles_and_teams
            assert 'EA-003 - Shared EA (Team Alpha)' in ea_titles_and_teams
            assert len(eligible_eas) == 2


    def test_get_eligible_ethical_approvals_team_shared_only(self, test_setup_data, test_app):
        with test_app.app_context():
            team2 = test_setup_data['team2']
            user2 = test_setup_data['user2']
            project_unlinked_team2 = Project(name='Unlinked Project Team2', team_id=team2.id, owner_id=user2.id)
            db.session.add(project_unlinked_team2)
            db.session.commit()

            eligible_eas = get_eligible_ethical_approvals(project_unlinked_team2.id, team2.id)
            ea_titles_and_teams = [f"{ea.reference_number} - {ea.title} ({ea.owner_team.name})" for ea in eligible_eas]

            # Should get ea2 (owned by team2), ea3 (shared with team2), and ea4 (owned by team2)
            assert 'EA-002 - Project Beta EA (Team Beta)' in ea_titles_and_teams
            assert 'EA-003 - Shared EA (Team Alpha)' in ea_titles_and_teams
            assert 'EA-004 - Unlinked EA (Team Beta)' in ea_titles_and_teams
            assert len(eligible_eas) == 3

    def test_calculate_animals_used_for_ea(self, test_setup_data, test_app):
        with test_app.app_context():
            ea1 = test_setup_data['ea1'] # g1 linked (2 animals)
            ea3 = test_setup_data['ea3'] # g2 (3 animals), g4 (2 animals) linked = 5 animals total

            assert calculate_animals_used_for_ea(ea1.id) == 2
            assert calculate_animals_used_for_ea(ea3.id) == 5
            assert calculate_animals_used_for_ea(test_setup_data['ea4'].id) == 0 # No groups linked

    def test_get_animals_available_for_ea(self, test_setup_data, test_app):
        with test_app.app_context():
            ea1 = test_setup_data['ea1'] # max 100, 2 used -> 98 available
            ea3 = test_setup_data['ea3'] # max 200, 5 used -> 195 available

            assert get_animals_available_for_ea(ea1) == 98
            assert get_animals_available_for_ea(ea3) == 195
            assert get_animals_available_for_ea(test_setup_data['ea4']) == 10 # 0 used

    def test_validate_group_ea_unlinking_no_ea_ids(self, test_setup_data, test_app):
        with test_app.app_context():
            g1 = test_setup_data['g1']
            result = validate_group_ea_unlinking(g1.id, [])
            assert not result['is_valid']
            assert "must be linked to at least one Ethical Approval" in result['errors'][0]

    def test_validate_group_ea_unlinking_valid_severity(self, test_setup_data, test_app):
        with test_app.app_context():
            g1 = test_setup_data['g1'] # Current EA is ea1 (MODERATE). Max protocol in its DTs is MODERATE.
            # Try to link to ea1 (MODERATE) -> should pass
            result = validate_group_ea_unlinking(g1.id, [test_setup_data['ea1'].id])
            assert result['is_valid']

    def test_validate_group_ea_unlinking_insufficient_severity(self, test_setup_data, test_app):
        with test_app.app_context():
            g1 = test_setup_data['g1'] # Max protocol in its DTs is MODERATE.
            # Try to link to ea3 (LIGHT) -> should fail
            result = validate_group_ea_unlinking(g1.id, [test_setup_data['ea3'].id])
            assert not result['is_valid']
            assert "exceeds the maximum severity allowed" in result['errors'][0]

    def test_validate_group_ea_unlinking_multiple_eas_sufficient_severity(self, test_setup_data, test_app):
        with test_app.app_context():
            g1 = test_setup_data['g1'] # Max protocol in its DTs is MODERATE.
            # Link to ea3 (LIGHT) and ea2 (SEVERE) -> ea2 should cover severity, so pass
            result = validate_group_ea_unlinking(g1.id, [test_setup_data['ea3'].id, test_setup_data['ea2'].id])
            assert result['is_valid']

    def test_validate_group_ea_unlinking_no_datatables(self, test_setup_data, test_app):
        with test_app.app_context():
            g4 = test_setup_data['g4'] # Has no datatables
            result = validate_group_ea_unlinking(g4.id, [test_setup_data['ea1'].id])
            assert result['is_valid']

    def test_validate_ea_unshare_from_team_orphans_groups(self, test_setup_data, test_app):
        with test_app.app_context():
            # ea3 is linked to g2 (team1) and g4 (team2)
            # If team2 unshares ea3, g4 would be orphaned (currently linked to ea3)
            ea3 = test_setup_data['ea3']
            team2 = test_setup_data['team2']
            g4 = test_setup_data['g4']

            result = validate_ea_unshare_from_team(ea3.id, team2.id)
            assert not result['is_valid']
            assert len(result['affected_groups']) == 1
            assert result['affected_groups'][0]['group_id'] == g4.id

    def test_validate_ea_unshare_from_team_no_orphaned_groups(self, test_setup_data, test_app):
        with test_app.app_context():
            # ea1 is owned by team1 and linked to g1 (team1). Not shared with other teams.
            # If team1 "unshares" ea1 (which it owns, so this scenario is slightly different,
            # but for the test of the function, we're checking if *any* group would be orphaned
            # if a team lost access to it and that group was using it)
            # A better test: ea3 linked to g2 (team1) and g4 (team2).
            # If team1 unshares ea3 (with team2), it doesn't affect g2 because g2 is team1's and ea3 is team1's.
            # But what if ea3 is shared with team2, and team2 has no groups linked to ea3.
            
            # Let's create a new team and share ea3 with them, but no groups linked
            team_unaffected = Team(name='Team Unaffected')
            db.session.add(team_unaffected)
            db.session.commit()

            # Re-fetch ea3 in the current session to avoid session conflicts
            ea3 = db.session.get(EthicalApproval, test_setup_data['ea3'].id)
            
            ea3.shared_with_teams.append(team_unaffected)
            db.session.commit()

            result = validate_ea_unshare_from_team(ea3.id, team_unaffected.id)
            assert result['is_valid']
            assert len(result['affected_groups']) == 0

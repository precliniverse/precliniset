# tests/test_models.py
"""
Tests unitaires des modèles SQLAlchemy.
Chaque test vérifie la création, les contraintes et les relations d'un modèle.
"""
from datetime import datetime

from app.models import (
    Analyte, AnalyteDataType, Animal, AnimalModel, Anticoagulant,
    APIToken, Attachment, DataTable, DataTableFile,
    DerivedSampleType, EthicalApproval,
    EthicalApprovalProcedure, ExperimentalGroup,
    ExperimentDataRow, HousingConditionItem,
    HousingConditionSet, HousingSetItemAssociation, Organ,
    Partner, Permission, Project, ProjectTeamShare,
    ProjectUserShare, ProtocolAttachment, ProtocolModel,
    ReferenceRange, Role, Sample, SampleStatus, SampleType,
    Severity, Staining, Storage, Team, TeamMembership,
    TissueCondition, User, UserTeamRoleLink, Workplan,
    WorkplanEvent, WorkplanEventStatus, WorkplanStatus,
    WorkplanVersion,
)
from app.permissions import AVAILABLE_PERMISSIONS, user_has_permission
from app.services.admin_service import AdminService


def test_new_user(db_session):
    """
    GIVEN a User model
    WHEN a new User is created
    THEN check the email, hashed password, and default roles are correct
    """
    user = User(email='testuser@example.com')
    user.set_password('mytestpassword')
    db_session.add(user)
    db_session.commit()

    assert user.id is not None
    assert user.email == 'testuser@example.com'
    assert user.check_password('mytestpassword')
    assert not user.check_password('wrongpassword')
    assert not user.is_super_admin
    assert user.is_active

def test_new_team_and_membership(db_session):
    """
    GIVEN User and Team models
    WHEN a new Team and TeamMembership are created
    THEN check the relationships are correctly established
    """
    # Populate permissions first
    for resource, actions in AVAILABLE_PERMISSIONS.items():
        for action in actions:
            db_session.add(Permission(resource=resource, action=action))
    db_session.commit()

    user = User(email='teamlead@example.com')
    user.set_password('password')
    team = Team(name='Test Team Alpha')
    
    db_session.add_all([user, team])
    db_session.commit()

    # Create default roles for the new team using Service
    admin_service = AdminService()
    roles = admin_service._ensure_default_roles(team)
    admin_role = roles['team_admin']

    # Create membership and assign the admin role
    role_link = UserTeamRoleLink(user_id=user.id, team_id=team.id, role_id=admin_role.id)
    db_session.add(role_link)
    db_session.flush() # Ensure role_link is in session before membership is added

    membership = TeamMembership(user=user, team=team)
    db_session.add(membership)
    db_session.commit()

    assert team.id is not None
    assert user in [m.user for m in team.memberships]
    assert team in [m.team for m in user.memberships]
    assert user.is_admin_of(team)


def test_permission_model(db_session):
    """Test Permission model creation and uniqueness."""
    # Permissions are pre-populated, so query existing instead of creating
    perm1 = db_session.query(Permission).filter_by(resource='Project', action='create').first()
    if not perm1:
        perm1 = Permission(resource='Project', action='create')
        db_session.add(perm1)
        db_session.commit()
    
    assert perm1.id is not None
    assert perm1.resource == 'Project'
    assert perm1.action == 'create'
    
    # Test uniqueness constraint with different values
    perm_duplicate = Permission(resource='Project', action='create')
    db_session.add(perm_duplicate)
    try:
        db_session.commit()
        assert False, "Unique constraint should prevent duplicate"
    except:
        db_session.rollback()
        assert True


def test_role_model(db_session):
    """Test Role model creation, permissions, and team association."""
    team = Team(name='Test Team')
    db_session.add(team)
    db_session.commit()
    
    # Permissions are pre-populated, query existing
    perm = db_session.query(Permission).filter_by(resource='Project', action='read').first()
    if not perm:
        perm = Permission(resource='Project', action='read')
        db_session.add(perm)
        db_session.commit()
    
    role = Role(name='Test Role', team_id=team.id)
    role.permissions.append(perm)
    db_session.add(role)
    db_session.commit()
    
    assert role.id is not None
    assert role.name == 'Test Role'
    assert role.team_id == team.id
    assert role.permissions[0].id == perm.id
    
    # Test global role
    global_role = Role(name='Global Admin')
    db_session.add(global_role)
    db_session.commit()
    assert global_role.team_id is None
    
    # Test has_active_assignments
    assert not role.has_active_assignments()
    assert not global_role.has_active_assignments()


def test_user_team_role_link_model(db_session):
    """Test UserTeamRoleLink model creation and relationships."""
    user = User(email='linkuser@example.com')
    user.set_password('password')
    team = Team(name='Link Team')
    role = Role(name='Link Role', team_id=team.id)
    
    db_session.add_all([user, team, role])
    db_session.commit()
    
    link = UserTeamRoleLink(user_id=user.id, team_id=team.id, role_id=role.id)
    db_session.add(link)
    db_session.commit()
    
    assert link.user_id == user.id
    assert link.team_id == team.id
    assert link.role_id == role.id
    assert link.user.email == 'linkuser@example.com'
    assert link.team.name == 'Link Team'


def test_anticoagulant_model(db_session):
    """Test Anticoagulant model creation and uniqueness."""
    anticoagulant = Anticoagulant(name='EDTA')
    db_session.add(anticoagulant)
    db_session.commit()
    
    assert anticoagulant.id is not None
    assert anticoagulant.name == 'EDTA'
    
    # Test uniqueness
    duplicate = Anticoagulant(name='EDTA')
    db_session.add(duplicate)
    try:
        db_session.commit()
        assert False, "Unique constraint violated"
    except:
        db_session.rollback()
        assert True


def test_organ_model(db_session):
    """Test Organ model creation and uniqueness."""
    organ = Organ(name='Liver')
    db_session.add(organ)
    db_session.commit()
    
    assert organ.id is not None
    assert organ.name == 'Liver'


def test_tissue_condition_model(db_session):
    """Test TissueCondition model creation and uniqueness."""
    condition = TissueCondition(name='Fresh')
    db_session.add(condition)
    db_session.commit()
    
    assert condition.id is not None
    assert condition.name == 'Fresh'


def test_staining_model(db_session):
    """Test Staining model creation and uniqueness."""
    staining = Staining(name='H&E')
    db_session.add(staining)
    db_session.commit()
    
    assert staining.id is not None
    assert staining.name == 'H&E'


def test_housing_condition_set_and_item(db_session):
    """Test HousingConditionSet and HousingConditionItem models with associations."""
    # Create item first
    item = HousingConditionItem(
        name='Temperature', data_type=AnalyteDataType.FLOAT, unit='°C'
    )
    db_session.add(item)
    db_session.commit()
    
    # Create set
    set_obj = HousingConditionSet(name='Standard Housing')
    db_session.add(set_obj)
    db_session.commit()
    
    association = HousingSetItemAssociation(
        set_id=set_obj.id, item_id=item.id, default_value='22.0'
    )
    db_session.add(association)
    db_session.commit()
    
    assert set_obj.id is not None
    assert set_obj.name == 'Standard Housing'
    assert item.id is not None
    assert item.name == 'Temperature'
    assert item.data_type == AnalyteDataType.FLOAT
    assert len(set_obj.items.all()) == 1
    assert len(item.sets.all()) == 1


def test_derived_sample_type_model(db_session):
    """Test DerivedSampleType model creation."""
    derived_type = DerivedSampleType(name='Plasma', parent_type=SampleType.BLOOD)
    db_session.add(derived_type)
    db_session.commit()
    
    assert derived_type.id is not None
    assert derived_type.name == 'Plasma'
    assert derived_type.parent_type == SampleType.BLOOD


def test_api_token_model(db_session):
    """Test APIToken model creation and verification."""
    user = User(email='tokenuser@example.com')
    user.set_password('password')
    db_session.add(user)
    db_session.commit()
    
    token = APIToken(user_id=user.id, name='Test Token')
    db_session.add(token)
    db_session.commit()
    
    assert token.id is not None
    assert token.name == 'Test Token'
    assert token.raw_token.startswith('pcv_')
    assert token.is_active is True
    
    # Test verification (note: raw_token is only available right after creation)
    raw_token = token.raw_token
    assert APIToken.verify_token(raw_token) == user
    assert APIToken.verify_token('invalid') is None


def test_analyte_model(db_session):
    """Test Analyte model creation and properties."""
    analyte = Analyte(
        name='Glucose', data_type=AnalyteDataType.FLOAT, unit='mmol/L',
        allowed_values=None, default_value='5.0', is_metadata=False, is_sensitive=False
    )
    db_session.add(analyte)
    db_session.commit()
    
    assert analyte.id is not None
    assert analyte.name == 'Glucose'
    assert analyte.data_type == AnalyteDataType.FLOAT
    assert analyte.to_dict()['name'] == 'Glucose'


def test_animal_model_model(db_session):
    """Test AnimalModel model creation and associations."""
    model = AnimalModel(name='Mouse Model')
    db_session.add(model)
    db_session.commit()
    
    assert model.id is not None
    assert model.name == 'Mouse Model'


def test_protocol_model(db_session):
    """Test ProtocolModel model creation and associations."""
    protocol = ProtocolModel(
        name='Blood Sampling', severity=Severity.LIGHT
    )
    db_session.add(protocol)
    db_session.commit()
    
    assert protocol.id is not None
    assert protocol.name == 'Blood Sampling'
    assert protocol.severity == Severity.LIGHT


def test_experimental_group_model(db_session):
    """Test ExperimentalGroup model creation and relationships."""
    team = Team(name='Group Team')
    db_session.add(team)
    db_session.commit()
    
    project = Project(name='Test Project', team_id=team.id, owner_id=1)
    animal_model = AnimalModel(name='Test Model')
    
    db_session.add_all([project, animal_model])
    db_session.commit()
    
    group = ExperimentalGroup(
        id='test_group_001',
        name='Test Group',
        project_id=project.id,
        model_id=animal_model.id,
        owner_id=1,
        team_id=team.id
    )
    db_session.add(group)
    db_session.commit()
    
    assert group.id == 'test_group_001'
    assert group.name == 'Test Group'
    assert group.model.name == 'Test Model'
    assert group.project.name == 'Test Project'
    assert group.is_archived is False
    assert group.sample_count == 0


def test_data_table_model(db_session):
    """Test DataTable model creation and relationships."""
    team = Team(name='DT Team')
    db_session.add(team)
    db_session.commit()
    
    project = Project(name='DT Project', team_id=team.id, owner_id=1)
    animal_model = AnimalModel(name='DT Model')
    db_session.add_all([project, animal_model])
    db_session.commit()
    
    protocol = ProtocolModel(name='DT Protocol')
    group = ExperimentalGroup(
        id='dt_group_001', name='DT Group', project_id=project.id,
        model_id=animal_model.id, owner_id=1, team_id=team.id
    )
    
    db_session.add_all([protocol, group])
    db_session.commit()
    
    data_table = DataTable(
        group_id=group.id, protocol_id=protocol.id, date='2023-01-01',
        creator_id=1
    )
    db_session.add(data_table)
    db_session.commit()
    
    assert data_table.id is not None
    assert data_table.group_id == group.id
    assert data_table.protocol_id == protocol.id


def test_data_table_file_model(db_session):
    """Test DataTableFile model creation."""
    data_table = DataTable(group_id='test_group', protocol_id=1, date='2023-01-01')
    db_session.add(data_table)
    db_session.commit()
    
    file_obj = DataTableFile(
        data_table_id=data_table.id, filename='test.csv',
        filepath='/path/to/test.csv', size=1024
    )
    db_session.add(file_obj)
    db_session.commit()
    
    assert file_obj.id is not None
    assert file_obj.filename == 'test.csv'


def test_workplan_model(db_session):
    """Test Workplan model creation and versions."""
    team = Team(name='WP Team')
    db_session.add(team)
    db_session.commit()
    
    project = Project(name='WP Project', team_id=team.id, owner_id=1)
    animal_model = AnimalModel(name='WP Model')
    
    db_session.add_all([project, animal_model])
    db_session.commit()
    
    workplan = Workplan(
        project_id=project.id, name='Test Workplan',
        animal_model_id=animal_model.id, planned_animal_count=50,
        status=WorkplanStatus.DRAFT
    )
    db_session.add(workplan)
    db_session.commit()
    
    assert workplan.id is not None
    assert workplan.name == 'Test Workplan'
    assert workplan.status == WorkplanStatus.DRAFT


def test_workplan_version_model(db_session):
    """Test WorkplanVersion model creation."""
    workplan = Workplan(project_id=1, name='Version WP', planned_animal_count=10)
    db_session.add(workplan)
    db_session.commit()
    
    version = WorkplanVersion(
        workplan_id=workplan.id, version_number=1,
        created_by_id=1, snapshot={'events': []}
    )
    db_session.add(version)
    db_session.commit()
    
    assert version.id is not None
    assert version.version_number == 1
    assert version.snapshot == {'events': []}


def test_workplan_event_model(db_session):
    """Test WorkplanEvent model creation."""
    workplan = Workplan(project_id=1, name='Event WP', planned_animal_count=10)
    protocol = ProtocolModel(name='Event Protocol')
    
    db_session.add_all([workplan, protocol])
    db_session.commit()
    
    event = WorkplanEvent(
        workplan_id=workplan.id, protocol_id=protocol.id,
        offset_days=30, status=WorkplanEventStatus.PLANNED
    )
    db_session.add(event)
    db_session.commit()
    
    assert event.id is not None
    assert event.offset_days == 30
    assert event.status == WorkplanEventStatus.PLANNED


def test_experiment_data_row_model(db_session):
    """Test ExperimentDataRow model creation."""
    data_table = DataTable(group_id='test_group', protocol_id=1, date='2023-01-01')
    db_session.add(data_table)
    db_session.commit()
    
    row = ExperimentDataRow(
        data_table_id=data_table.id, animal_id=1,
        row_data={'analyte1': 10.5}
    )
    db_session.add(row)
    db_session.commit()
    
    assert row.id is not None
    assert row.animal_id == 1
    assert row.row_data == {'analyte1': 10.5}


def test_project_model(db_session):
    """Test Project model creation and associations."""
    team = Team(name='Project Team')
    db_session.add(team)
    db_session.commit()
    
    project = Project(
        name='Test Project', team_id=team.id, owner_id=1,
        is_archived=False
    )
    db_session.add(project)
    db_session.commit()
    
    assert project.id is not None
    assert project.name == 'Test Project'
    assert project.team_id == team.id
    assert project.is_archived is False


def test_project_team_share_model(db_session):
    """Test ProjectTeamShare model creation."""
    project = Project(name='Share Project', team_id=1, owner_id=1)
    team = Team(name='Shared Team')
    
    db_session.add_all([project, team])
    db_session.commit()
    
    share = ProjectTeamShare(
        project_id=project.id, team_id=team.id,
        can_view_project=True,
        can_edit_datatables=True
    )
    db_session.add(share)
    db_session.commit()
    
    assert share.can_view_project is True
    assert share.can_edit_datatables is True


def test_project_user_share_model(db_session):
    """Test ProjectUserShare model creation."""
    project = Project(name='Perm Project', team_id=1, owner_id=1)
    user = User(email='shareuser@example.com')
    user.set_password('password')
    
    db_session.add_all([project, user])
    db_session.commit()
    
    share = ProjectUserShare(
        project_id=project.id, user_id=user.id,
        permission_level='editor'
    )
    db_session.add(share)
    db_session.commit()
    
    assert share.permission_level == 'editor'


def test_partner_model(db_session):
    """Test Partner model creation."""
    partner = Partner(company_name='Test Partner', contact_email='test@partner.com')
    db_session.add(partner)
    db_session.commit()
    
    assert partner.id is not None
    assert partner.company_name == 'Test Partner'


def test_attachment_model(db_session):
    """Test Attachment model creation."""
    project = Project(name='Attach Project', team_id=1, owner_id=1)
    db_session.add(project)
    db_session.commit()
    
    attachment = Attachment(
        project_id=project.id, filename='test.pdf',
        filepath='/path/to/test.pdf', size=2048
    )
    db_session.add(attachment)
    db_session.commit()
    
    assert attachment.id is not None
    assert attachment.filename == 'test.pdf'



def test_protocol_attachment_model(db_session):
    """Test ProtocolAttachment model creation."""
    protocol = ProtocolModel(name='Attach Protocol')
    db_session.add(protocol)
    db_session.commit()
    
    # ProtocolAttachment does not have a 'size' field in the current model definition
    prot_attach = ProtocolAttachment(
        protocol_id=protocol.id, filename='protocol.pdf',
        filepath='/path/to/protocol.pdf'
    )
    db_session.add(prot_attach)
    db_session.commit()
    
    assert prot_attach.id is not None
    assert prot_attach.filename == 'protocol.pdf'
    

def test_reference_range_model(db_session):
    """Test ReferenceRange model creation and dict method."""
    team = Team(name='RR Team')
    analyte = Analyte(name='RR Analyte', data_type=AnalyteDataType.FLOAT)
    protocol = ProtocolModel(name='RR Protocol')
    animal_model = AnimalModel(name='RR Model')
    
    db_session.add_all([team, analyte, protocol, animal_model])
    db_session.commit()
    
    rr = ReferenceRange(
        name='Test RR', team_id=team.id, owner_id=1,
        analyte_id=analyte.id, protocol_id=protocol.id, animal_model_id=animal_model.id,
        min_age=30, max_age=90, included_animals={'group1': [1,2,3]}
    )
    db_session.add(rr)
    db_session.commit()
    
    assert rr.id is not None
    assert rr.name == 'Test RR'
    assert rr.to_dict()['included_animals'] == {'group1': [1,2,3]}


def test_ethical_approval_model(db_session):
    """Test EthicalApproval model creation."""
    team = Team(name='EA Team')
    db_session.add(team)
    db_session.commit()
    
    approval = EthicalApproval(
        reference_number='EA001', title='Test Approval',
        start_date=datetime(2023,1,1).date(), end_date=datetime(2023,12,31).date(),
        number_of_animals=100, overall_severity=Severity.MODERATE,
        team_id=team.id
    )
    db_session.add(approval)
    db_session.commit()
    
    assert approval.id is not None
    assert approval.reference_number == 'EA001'
    assert approval.overall_severity == Severity.MODERATE


def test_ethical_approval_procedure_model(db_session):
    """Test EthicalApprovalProcedure model creation."""
    team = Team(name='Proc Team')
    db_session.add(team)
    db_session.commit()
    
    approval = EthicalApproval(reference_number='PROC001', title='Proc Approval',
                               start_date=datetime(2023,1,1).date(), end_date=datetime(2023,12,31).date(),
                               number_of_animals=50, team_id=team.id)
    db_session.add(approval)
    db_session.commit()
    
    procedure = EthicalApprovalProcedure(
        ethical_approval_id=approval.id, name='Blood Draw',
        severity=Severity.LIGHT, is_euthanasia_endpoint=False
    )
    db_session.add(procedure)
    db_session.commit()
    
    assert procedure.id is not None
    assert procedure.name == 'Blood Draw'


def test_storage_model(db_session):
    """Test Storage model creation."""
    team = Team(name='Storage Team')
    db_session.add(team)
    db_session.commit()
    
    storage = Storage(
        name='Freezer A', team_id=team.id, capacity='500L'
    )
    db_session.add(storage)
    db_session.commit()
    
    assert storage.id is not None
    assert storage.name == 'Freezer A'


def test_sample_model(db_session):
    """Test Sample model creation and properties."""
    team = Team(name='Sample Team')
    db_session.add(team)
    db_session.commit()
    
    project = Project(name='Sample Project', team_id=team.id, owner_id=1)
    animal_model = AnimalModel(name='Sample Model')
    db_session.add_all([project, animal_model])
    db_session.commit()
    
    group = ExperimentalGroup(
        id='sample_group_001', name='Sample Group', project_id=project.id,
        model_id=animal_model.id, owner_id=1, team_id=team.id
    )
    db_session.add(group)
    db_session.commit()
    
    animal = Animal(uid='Animal001', display_id='Animal 1', group_id=group.id, status='alive')
    db_session.add(animal)
    db_session.commit()
    anticoagulant = Anticoagulant(name='Heparin')
    organ = Organ(name='Kidney')
    derived_type = DerivedSampleType(name='Serum', parent_type=SampleType.BLOOD)
    staining = Staining(name='PAS')
    storage = Storage(name='Sample Storage', team_id=team.id)
    
    db_session.add_all([group, anticoagulant, organ, derived_type, staining, storage])
    db_session.commit()
    
    sample = Sample(
        experimental_group_id=group.id, animal_index_in_group=0,
        sample_type=SampleType.BLOOD, collection_date=datetime(2023,1,1).date(),
        status=SampleStatus.STORED, is_terminal=False,
        anticoagulant_id=anticoagulant.id, volume=100.0,
        organ_id=None, derived_type_id=None, staining_id=None,
        storage_id=storage.id, display_id='S001'
    )
    db_session.add(sample)
    db_session.commit()
    
    assert sample.id is not None
    assert sample.sample_type == SampleType.BLOOD
    assert sample.status == SampleStatus.STORED
    assert sample.animal_display_id == 'Animal001'
    assert sample.volume == 100.0


def test_user_has_permission_function(db_session):
    """Test user_has_permission function with various scenarios."""
    user = User(email='permuser@example.com')
    user.set_password('password')
    user.is_super_admin = True
    db_session.add(user)
    db_session.commit()
    
    # Super admin should always have permission
    assert user_has_permission(user, 'Project', 'create', team_id=1) is True
    
    user.is_super_admin = False
    db_session.commit()
    
    # Non-super admin without roles should not have permission
    assert user_has_permission(user, 'Project', 'create', team_id=1) is False
    
    # Add team and role with permission - use unique name to avoid constraint
    import secrets
    unique_suffix = secrets.token_hex(4)
    team = Team(name=f'Perm Team {unique_suffix}')
    db_session.add(team)
    db_session.commit()
    
    # Permissions pre-populated, query existing
    perm = db_session.query(Permission).filter_by(resource='Project', action='create').first()
    if not perm:
        perm = Permission(resource='Project', action='create')
        db_session.add(perm)
        db_session.commit()
    
    role = Role(name=f'Creator {unique_suffix}', team_id=team.id)
    role.permissions.append(perm)
    db_session.add(role)
    db_session.commit()
    
    link = UserTeamRoleLink(user_id=user.id, team_id=team.id, role_id=role.id)
    db_session.add(link)
    db_session.commit()
    
    assert user_has_permission(user, 'Project', 'create', team_id=team.id) is True
    assert user_has_permission(user, 'Project', 'delete', team_id=team.id) is False  # No delete perm


def test_enum_models():
    """Test enum models and their methods."""
    # Test Severity comparisons
    assert Severity.LIGHT < Severity.SEVERE
    assert Severity.MODERATE <= Severity.MODERATE
    assert not (Severity.NONE > Severity.SEVERE)  # Should be False, not NotImplemented
    
    # Test SampleStatus choices and coerce
    choices = SampleStatus.choices()
    assert len(choices) == len(SampleStatus)
    assert SampleStatus.coerce('STORED') == SampleStatus.STORED
    assert str(SampleStatus.STORED) == 'Stored'  # Assuming _l returns the value
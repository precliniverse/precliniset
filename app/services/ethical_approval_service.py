from sqlalchemy import or_

from app.extensions import db
from app.models.auth import User  # Import User
from app.models.ethical import Severity  # Import Severity
from app.models.ethical import EthicalApproval
from app.models.experiments import (  # Import ExperimentalGroup and DataTable
    DataTable, ExperimentalGroup)
from app.models.projects import Project
from app.models.resources import ProtocolModel  # Import ProtocolModel
from app.models.teams import Team


def validate_group_ea_unlinking(group_id: str, new_ea_ids: list) -> dict:
    """
    Validates the unlinking of a group from ethical approvals.
    Checks:
    1. If the group would be left without any ethical approval.
    2. If the maximal protocol severity of the group's datatables is within the range
       of the new/remaining ethical approvals' maximal severity.

    Args:
        group_id (str): The ID of the experimental group being modified.
        new_ea_ids (list): A list of IDs of ethical approvals that the group will be
                           linked to after the change.

    Returns:
        dict: A dictionary containing 'is_valid' (bool) and 'errors' (list of str).
    """
    errors = []
    is_valid = True

    group = db.session.get(ExperimentalGroup, group_id)
    if not group:
        errors.append("Experimental group not found.")
        return {'is_valid': False, 'errors': errors}

    # 1. Check if the group would be left without any ethical approval
    if not new_ea_ids:
        errors.append(f"Group '{group.name}' must be linked to at least one Ethical Approval.")
        is_valid = False
        # If there are no EAs, severity check is irrelevant, as it's already invalid
        return {'is_valid': is_valid, 'errors': errors}

    # 2. Check maximal protocol severity
    # Get all datatables for the group
    group_datatables = DataTable.query.filter_by(group_id=group_id).all()
    
    if group_datatables:
        max_protocol_severity_level = Severity.NONE.level
        for dt in group_datatables:
            if dt.protocol and dt.protocol.severity:
                if dt.protocol.severity.level > max_protocol_severity_level:
                    max_protocol_severity_level = dt.protocol.severity.level
        
        if max_protocol_severity_level > Severity.NONE.level: # Only if there are protocols with actual severity
            # Get the new/remaining EAs
            new_eas = EthicalApproval.query.filter(EthicalApproval.id.in_(new_ea_ids)).all()
            
            # Check if any of the new EAs can accommodate the max protocol severity
            can_accommodate_severity = False
            for ea in new_eas:
                if ea.overall_severity and ea.overall_severity.level >= max_protocol_severity_level:
                    can_accommodate_severity = True
                    break
            
            if not can_accommodate_severity:
                max_prot_sev_enum = next((s for s in Severity if s.level == max_protocol_severity_level), Severity.NONE)
                errors.append(
                    f"The maximum protocol severity ({max_prot_sev_enum.value}) "
                    f"in datatables for group '{group.name}' exceeds the maximum "
                    f"severity allowed by the selected Ethical Approval(s)."
                )
                is_valid = False

    return {'is_valid': is_valid, 'errors': errors}



def validate_ea_unshare_from_team(ethical_approval_id: int, team_to_unshare_id: int) -> dict:
    """
    Validates if unsharing an Ethical Approval from a specific team would leave
    any experimental groups from that team without an Ethical Approval.

    Args:
        ethical_approval_id (int): The ID of the Ethical Approval being unshared.
        team_to_unshare_id (int): The ID of the team from which the EA is being unshared.

    Returns:
        dict: A dictionary containing:
              - 'is_valid' (bool): True if no groups would be orphaned, False otherwise.
              - 'affected_groups' (list): A list of dictionaries, each with 'group_id',
                                         'group_name', and 'owner_name' for orphaned groups.
    """
    affected_groups_info = []

    # Find all groups belonging to 'team_to_unshare_id' that are currently linked to 'ethical_approval_id'
    groups_to_check = ExperimentalGroup.query.filter(
        ExperimentalGroup.team_id == team_to_unshare_id,
        ExperimentalGroup.ethical_approval_id == ethical_approval_id
    ).all()

    for group in groups_to_check:
        owner = db.session.get(User, group.owner_id)
        affected_groups_info.append({
            'group_id': group.id,
            'group_name': group.name,
            'owner_name': owner.email if owner else "Unknown User"
        })

    return {
        'is_valid': not bool(affected_groups_info),
        'affected_groups': affected_groups_info
    }


def calculate_animals_used_for_ea(ethical_approval_id: int) -> int:
    """
    Calculates the total number of animals used across all experimental groups
    linked to a specific ethical approval.
    Assumes animal_data in ExperimentalGroup is a JSON list, where each item represents an animal.
    """
    total_animals_used = 0
    # Use db.session.get for modern SQLAlchemy, and remove joinedload for dynamic relationship
    ea = db.session.get(EthicalApproval, ethical_approval_id)
    if ea:
        # The 'experimental_groups' relationship is dynamic, so it acts like a query
        for group in ea.experimental_groups:
            if group.animal_data and isinstance(group.animal_data, list):
                total_animals_used += len(group.animal_data)
    return total_animals_used


def get_animals_available_for_ea(ethical_approval: EthicalApproval) -> int:
    """
    Calculates the number of animals still available for a given ethical approval.
    """
    animals_used = calculate_animals_used_for_ea(ethical_approval.id)
    return ethical_approval.number_of_animals - animals_used

def get_eligible_ethical_approvals(project_id: int, team_id: int):
    """
    Retrieves a list of ethical approvals eligible for a given project and team.
    Eligibility is defined as:
    1. EAs directly linked to the project.
    2. EAs created by the specified team.
    3. EAs shared with the specified team.
    """
    
    # EAs directly linked to the project
    project_linked_eas = db.session.query(EthicalApproval).options(db.joinedload(EthicalApproval.owner_team)).join(Project.ethical_approvals).filter(Project.id == project_id)

    # EAs created by the specified team
    team_owned_eas = db.session.query(EthicalApproval).options(db.joinedload(EthicalApproval.owner_team)).filter(EthicalApproval.team_id == team_id)

    # EAs shared with the specified team
    team_shared_eas = db.session.query(EthicalApproval).options(db.joinedload(EthicalApproval.owner_team)).join(EthicalApproval.shared_with_teams).filter(Team.id == team_id)

    # Combine and get unique EAs
    eligible_eas = project_linked_eas.union(team_owned_eas, team_shared_eas).all()

    return eligible_eas

# app/models/__init__.py
"""
Database models for the Precliniset application.
This module re-exports all models from their respective domain modules
to maintain backward compatibility with existing imports.
"""

# Import auth and RBAC models
from .auth import (APIToken, Permission, Role, User, UserTeamRoleLink,
                   role_permissions, user_has_permission,
                   user_my_page_datatables, user_my_page_groups)
# Import audit model
from .audit import AuditLog
# Import CKAN models
from .import_template import ImportTemplate
from .ckan import CKANResourceTask, CKANUploadTask
# Import pipeline model
from .import_pipeline import ImportPipeline
# Import enums
from .enums import (AnalyteDataType, RegulationCategory, SampleStatus,
                    SampleType, Severity, WorkplanEventStatus, WorkplanStatus)
# Import ethical approval models
from .ethical import EthicalApproval, EthicalApprovalProcedure
# Import experiment models
from .experiments import (DataTable, DataTableFile, ExperimentalGroup,
                          ExperimentDataRow)
# Import animal model
from .animal import Animal
# Import project models
from .projects import (Attachment, Partner, Project,
                       ProjectEthicalApprovalAssociation,
                       ProjectPartnerAssociation, ProjectTeamShare,
                       ProjectUserShare, ReferenceRange)
# Import resource models
from .resources import (Analyte, AnimalModel, AnimalModelAnalyteAssociation,
                        Anticoagulant, DerivedSampleType, HousingConditionItem,
                        HousingConditionSet, HousingSetItemAssociation, Organ,
                        ProtocolAnalyteAssociation, ProtocolAttachment,
                        ProtocolModel, Staining, TissueCondition,
                        sample_conditions_association, protocol_pipeline_association)
# Import controlled molecule models
from .controlled_molecule import (ControlledMolecule, DataTableMoleculeUsage,
                                   ProtocolMoleculeAssociation)
# Import storage and sample models
from .storage import DerivedSample, Sample, Storage, StorageLocation
# Import team models
from .teams import (Team, TeamMembership, ethical_approval_team_share,
                    reference_range_team_share)
# Import workplan models
from .workplans import Workplan, WorkplanEvent, WorkplanVersion

# Backward compatibility alias
ProjectSharedTeamPermission = ProjectTeamShare

# Explicit __all__ for clarity
__all__ = [
    # Enums
    'WorkplanStatus',
    'WorkplanEventStatus',
    'AnalyteDataType',
    'Severity',
    'SampleType',
    'SampleStatus',
    'RegulationCategory',
    
    # Auth & RBAC
    'Permission',
    'Role',
    'UserTeamRoleLink',
    'User',
    'APIToken',
    'role_permissions',
    'user_my_page_groups',
    'user_my_page_datatables',
    'user_has_permission',
    'AuditLog',
    
    # Teams
    'Team',
    'TeamMembership',
    'ethical_approval_team_share',
    'reference_range_team_share',
    
    # Resources
    'Anticoagulant',
    'Organ',
    'TissueCondition',
    'sample_conditions_association',
    'Staining',
    'HousingSetItemAssociation',
    'HousingConditionSet',
    'HousingConditionItem',
    'DerivedSampleType',
    'Analyte',
    'AnimalModel',
    'ProtocolModel',
    'ProtocolAttachment',
    'AnimalModelAnalyteAssociation',
    'ProtocolAnalyteAssociation',
    
    # Controlled Molecules
    'ControlledMolecule',
    'ProtocolMoleculeAssociation',
    'DataTableMoleculeUsage',
    
    # Storage & Samples
    'Storage',
    'StorageLocation',
    'Sample',
    'DerivedSample',
    
    # Ethical Approvals
    'EthicalApproval',
    'EthicalApprovalProcedure',
    
    # Workplans
    'Workplan',
    'WorkplanVersion',
    'WorkplanEvent',
    
    # Projects
    'Project',
    'ProjectTeamShare',
    'ProjectUserShare',
    'Partner',
    'Attachment',
    'ProjectPartnerAssociation',
    'ProjectEthicalApprovalAssociation',
    'ReferenceRange',
    
    # Experiments
    'ExperimentalGroup',
    'DataTable',
    'DataTableFile',
    'ExperimentDataRow',
    'Animal',
    
    # CKAN
    'CKANUploadTask',
    'CKANResourceTask',
    'ImportTemplate',
    'ImportPipeline',
    'protocol_pipeline_association',
    
    # Backward compatibility
    'ProjectSharedTeamPermission',
]

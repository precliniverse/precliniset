# app/services/molecule_service.py
from typing import List, Optional
from datetime import datetime, timezone
import json
from flask_login import current_user
from app.extensions import db
from app.models import DataTableMoleculeUsage, ControlledMolecule
from app.services.base import BaseService
from app.decorators import transactional

class MoleculeService(BaseService):
    model = ControlledMolecule

    def __init__(self):
        super().__init__()

    @transactional
    def record_usage(self, 
                     data_table_id: int, 
                     molecule_id: int, 
                     volume_used: float, 
                     animal_ids_json: str, 
                     recorded_by_id: int, 
                     notes: Optional[str] = None) -> DataTableMoleculeUsage:
        """
        Record usage of a controlled molecule in a DataTable.
        """
        animal_ids_list = json.loads(animal_ids_json) if animal_ids_json else []
        
        usage = DataTableMoleculeUsage(
            data_table_id=data_table_id,
            molecule_id=molecule_id,
            volume_used=volume_used,
            animal_ids=animal_ids_list,
            number_of_animals=len(animal_ids_list),
            recorded_by_id=recorded_by_id,
            notes=notes
        )
        db.session.add(usage)
        return usage

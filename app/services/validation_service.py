# app/services/validation_service.py
from datetime import datetime
from flask_babel import lazy_gettext as _l
from app.models import AnalyteDataType

class ValidationService:
    """
    Service responsible for validating JSON data against Core Model definitions.
    Ensures data integrity before saving to JSON columns.
    """

    def validate_animal_data(self, animal_data_list, animal_model, strict=True):
        """
        Validates a list of animal data dictionaries against the model's analytes.
        Returns a dictionary: {'errors': [], 'new_categories': {analyte_id: [new_values]}}
        """
        errors = []
        new_categories = {} # map analyte_id -> set of new values
        
        if not animal_model:
            return {'errors': errors, 'new_categories': new_categories}
        
        if not animal_data_list:
            return {'errors': errors, 'new_categories': new_categories}

        # Create a map of field_name -> Analyte object for quick lookup (case-insensitive)
        analyte_map = {a.name.lower(): a for a in animal_model.analytes}
        analyte_map.update({a.name: a for a in animal_model.analytes}) # Keep original names too

        for index, row in enumerate(animal_data_list):
            row_idx = index + 1  # 1-based index for user-friendly error messages
            
            for field_name, value in row.items():
                # Skip internal fields or empty values
                if field_name not in analyte_map or value is None or value == "":
                    continue

                analyte = analyte_map[field_name]
                
                # 1. Validate Data Types
                if analyte.data_type == AnalyteDataType.INT:
                    try:
                        int(value)
                    except (ValueError, TypeError):
                        errors.append(_l("Row %(row)s: '%(field)s' must be an integer (got '%(val)s').", row=row_idx, field=field_name, val=value))
                
                elif analyte.data_type == AnalyteDataType.FLOAT:
                    try:
                        float(value)
                    except (ValueError, TypeError):
                        errors.append(_l("Row %(row)s: '%(field)s' must be a number (got '%(val)s').", row=row_idx, field=field_name, val=value))

                elif analyte.data_type == AnalyteDataType.DATE:
                    # Expect ISO format YYYY-MM-DD
                    try:
                        # Handle potential full datetime strings by slicing
                        val_str = str(value).split('T')[0]
                        datetime.strptime(val_str, '%Y-%m-%d')
                    except (ValueError, TypeError):
                        errors.append(_l("Row %(row)s: '%(field)s' must be a date in YYYY-MM-DD format (got '%(val)s').", row=row_idx, field=field_name, val=value))

                # 2. Validate Categorical Allowed Values
                elif analyte.data_type == AnalyteDataType.CATEGORY:
                    if analyte.allowed_values:
                        # Split by semicolon and strip whitespace
                        allowed = [v.strip() for v in analyte.allowed_values.split(';') if v.strip()]
                        val_str = str(value).strip()
                        if val_str not in allowed:
                            if not strict:
                                if analyte.id not in new_categories:
                                    new_categories[analyte.id] = set()
                                new_categories[analyte.id].add(val_str)
                            else:
                                errors.append(_l("Row %(row)s: '%(field)s' has invalid value '%(val)s'. Allowed: %(allowed)s", row=row_idx, field=field_name, val=value, allowed=", ".join(allowed)))

        # Convert sets to sorted lists for JSON serializability
        serializable_new_categories = {aid: sorted(list(vals)) for aid, vals in new_categories.items()}
        
        return {'errors': errors, 'new_categories': serializable_new_categories}
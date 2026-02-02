"""
Pydantic schemas for Animal data validation.

This module defines schemas for validating animal data with dynamic field support.
"""
from datetime import date
from typing import Any, Dict, Optional
import pydantic
from pydantic import BaseModel, Field, field_validator, model_validator


class AnimalSchema(BaseModel):
    """Schema for validating animal data.
    
    Validates core animal fields while allowing dynamic measurements.
    Sex validation is performed dynamically against database configuration.
    
    Attributes:
        animal_id: Unique identifier for the animal
        date_of_birth: Animal's date of birth
        sex: Animal's sex (validated against Analyte configuration)
        measurements: Dynamic scientific measurements (weight, tumor size, etc.)
    """
    
    animal_id: str = Field(..., alias="ID", description="Unique animal identifier")
    date_of_birth: date = Field(..., alias="Date of Birth", description="Date of birth")
    sex: Optional[str] = Field(None, description="Animal sex (e.g., Male, Female, M, F)")
    measurements: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Dynamic scientific measurements"
    )
    
    model_config = {
        "populate_by_name": True,  # Allow both alias and field name
        "str_strip_whitespace": True,  # Strip whitespace from strings
        "extra": "allow", # Allow extra fields to be captured by model_validator
    }

    @field_validator('animal_id', mode='before')
    @classmethod
    def pre_validate_id(cls, v: Any) -> Any:
        # Compatibility: if it's a number, convert to string
        if isinstance(v, (int, float)):
            return str(v)
        return v

    @pydantic.model_validator(mode='before')
    @classmethod
    def collect_extra_measurements(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        
        # Define fields that are NOT measurements
        # (Using actual field names AND aliases)
        known_fields = {'animal_id', 'ID', 'date_of_birth', 'Date of Birth', 'sex', 'Sex', 'measurements', 'status'}
        
        # Ensure measurements exists
        if 'measurements' not in data:
            data['measurements'] = {}
        
        # Move extra fields to measurements
        # We need to create a copy to avoid "dict changed size during iteration" if we were deleting, 
        # but here we are just selecting.
        extras = {k: v for k, v in data.items() if k not in known_fields}
        data['measurements'].update(extras)
        
        # Optional: remove extras from top level if we want a clean model
        # For Pydantic with extra='allow', they stay at top level too unless we remove them.
        # But we want them in .measurements for our Animal model sync.
        for k in extras:
            del data[k]
            
        return data
    
    @field_validator('animal_id')
    @classmethod
    def validate_animal_id(cls, v: str) -> str:
        """Validate animal ID is not empty and sanitizes it."""
        if not v or not v.strip():
            raise ValueError("Animal ID cannot be empty")
        import html
        return html.escape(v.strip())
    
    @field_validator('sex')
    @classmethod
    def validate_sex(cls, v: Optional[str]) -> Optional[str]:
        """Normalize and sanitize sex value."""
        if v:
            import html
            return html.escape(v.strip())
        return v

    @field_validator('measurements')
    @classmethod
    def sanitize_measurements(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Sanitize string values in measurements."""
        if not v:
            return v
        
        import html
        sanitized = {}
        for key, value in v.items():
            # Sanitize Key
            safe_key = html.escape(key.strip()) if isinstance(key, str) else key
            
            # Sanitize Value
            safe_val = value
            if isinstance(value, str):
                safe_val = html.escape(value)
            
            sanitized[safe_key] = safe_val
            
        return sanitized

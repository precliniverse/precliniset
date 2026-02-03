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
        id: Unique identifier for the animal
        date_of_birth: Animal's date of birth
        sex: Animal's sex (validated against Analyte configuration)
        measurements: Dynamic scientific measurements (weight, tumor size, etc.)
    """
    
    animal_id: str = Field(..., alias="id", description="Unique animal identifier")
    date_of_birth: date = Field(..., description="Date of birth")
    sex: Optional[str] = Field(None, description="Animal sex (e.g., Male, Female)")
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
        known_fields = {'animal_id', 'id', 'ID', 'date_of_birth', 'Date of Birth', 'date of birth', 'sex', 'Sex', 'measurements', 'status', 'Status'}
        
        # Map capitalized variants to known fields for Pydantic
        mapping = {
            'ID': 'id',
            'Date of Birth': 'date_of_birth',
            'date of birth': 'date_of_birth',
            'Sex': 'sex',
            'Status': 'status'
        }
        for k, v in mapping.items():
            if k in data and v not in data:
                data[v] = data[k]
                # We keep the original in data if it's a known field variant 
                # to satisfy known_fields check later if needed, but del is fine
                # because we already mapped it to a Pydantic field.

        # Ensure measurements exists
        if 'measurements' not in data:
            data['measurements'] = {}
        
        # Move extra fields to measurements
        extras = {k: v for k, v in data.items() if k not in known_fields}
        data['measurements'].update(extras)
        
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

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
    
    id: Optional[int] = Field(None, description="Internal DB ID (Ignored during creation)")
    uid: str = Field(..., description="Unique animal identifier")
    display_id: str = Field(..., description="User-facing animal identifier")
    date_of_birth: date = Field(..., description="Date of birth")
    sex: Optional[str] = Field(None, description="Animal sex (e.g., Male, Female)")
    measurements: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Dynamic scientific measurements"
    )
    
    model_config = {
        "str_strip_whitespace": True,  # Strip whitespace from strings
        "extra": "allow", # Allow extra fields to be captured by model_validator
    }

    @field_validator('uid', mode='before')
    @classmethod
    def pre_validate_id(cls, v: Any) -> Any:
        # Compatibility: if it's a number, convert to string
        if isinstance(v, (int, float)):
            return str(v)
        return v

    @model_validator(mode='before')
    @classmethod
    def collect_extra_measurements(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        
        # Canonical fields that are NOT measurements
        known_fields = {
            'id', 'uid', 'display_id', 'date_of_birth', 'sex', 'status', 
            'measurements', 'age_days', 'blinded_group', 'treatment_group'
        }
        
        # Ensure measurements exists
        if 'measurements' not in data:
            data['measurements'] = {}
        
        # Move extra fields to measurements
        extras = {k: v for k, v in data.items() if k not in known_fields}
        data['measurements'].update(extras)
        
        for k in extras:
            del data[k]
            
        return data
    
    @field_validator('uid')
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

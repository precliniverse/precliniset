"""
Pydantic schemas for ExperimentalGroup data validation.

This module defines schemas for validating group creation and updates.
"""
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
from .animal import AnimalSchema


class GroupCreateSchema(BaseModel):
    """Schema for creating a new experimental group.
    
    Validates group data including nested animal information.
    
    Attributes:
        name: Group name
        protocol_id: ID of the associated protocol
        animals: List of animals in the group
        description: Optional group description
    """
    
    name: str = Field(..., min_length=1, max_length=255, description="Group name")
    protocol_id: int = Field(..., gt=0, description="Protocol ID")
    animals: List[AnimalSchema] = Field(
        default_factory=list,
        description="List of animals in the group"
    )
    description: Optional[str] = Field(
        None,
        max_length=1000,
        description="Optional group description"
    )
    
    model_config = {
        "str_strip_whitespace": True,
    }
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate group name is not empty and sanitize it."""
        if not v.strip():
            raise ValueError("Group name cannot be empty")
        import html
        return html.escape(v.strip())

    @field_validator('description')
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Sanitize description."""
        if v:
            import html
            return html.escape(v.strip())
        return v
    
    @field_validator('animals')
    @classmethod
    def validate_animals_unique_ids(cls, v: List[AnimalSchema]) -> List[AnimalSchema]:
        """Validate that all animal IDs are unique within the group.
        
        Args:
            v: List of animals
            
        Returns:
            Validated list of animals
            
        Raises:
            ValueError: If duplicate animal IDs are found
        """
        if not v:
            return v
        
        animal_ids = [animal.animal_id for animal in v]
        duplicates = [aid for aid in animal_ids if animal_ids.count(aid) > 1]
        
        if duplicates:
            unique_duplicates = list(set(duplicates))
            raise ValueError(
                f"Duplicate animal IDs found: {', '.join(unique_duplicates)}"
            )
        
        return v


class GroupSearchSchema(BaseModel):
    """Schema for searching experimental groups.
    
    Attributes:
        q: Search query string
        project_id: Optional project ID filter
        page: Page number (default 1)
        per_page: Items per page (default 15)
    """
    q: Optional[str] = Field(None, description="Search term")
    project_id: Optional[str] = Field(None, description="Project ID to filter by")
    page: int = Field(1, ge=1, description="Page number")
    per_page: int = Field(15, ge=1, le=100, description="Items per page")

    model_config = {
        "str_strip_whitespace": True,
    }


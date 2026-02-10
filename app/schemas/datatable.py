"""
Pydantic schemas for DataTable operations.

This module defines schemas for validating DataTable actions like move and reassign.
"""
from typing import Optional
from pydantic import BaseModel, Field
from datetime import date


class DataTableMoveSchema(BaseModel):
    """Schema for validating DataTable move requests.
    
    Moves a DataTable to a new date.
    
    Attributes:
        new_date: The new date for the DataTable in YYYY-MM-DD format.
    """
    
    new_date: str = Field(
        ..., 
        description="New date in YYYY-MM-DD format",
        pattern=r"^\d{4}-\d{2}-\d{2}$"
    )
    
    model_config = {
        "str_strip_whitespace": True,
    }


class DataTableReassignSchema(BaseModel):
    """Schema for validating DataTable reassign requests.
    
    Reassigns a DataTable to a different user.
    
    Attributes:
        assignee_id: The ID of the user to assign the DataTable to.
    """
    
    assignee_id: Optional[int] = Field(
        None,
        description="ID of the user to assign the DataTable to (null to unassign)"
    )
    
    model_config = {
        "str_strip_whitespace": True,
    }

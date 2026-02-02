"""
Custom exception hierarchy for Precliniset application.

This module defines a structured exception hierarchy for better error handling
and reporting throughout the application.
"""
from typing import Optional


class PreclinisetError(Exception):
    """Base exception class for all Precliniset errors.
    
    Args:
        message: Human-readable error message
        code: Optional error code for programmatic handling
    """
    
    def __init__(self, message: str, code: Optional[str] = None):
        self.message = message
        self.code = code
        super().__init__(self.message)
    
    def to_dict(self) -> dict:
        """Convert exception to dictionary for JSON responses.
        
        Returns:
            Dictionary containing error message and code
        """
        result = {"error": self.message}
        if self.code:
            result["code"] = self.code
        return result


class ValidationError(PreclinisetError):
    """Raised when data validation fails.
    
    Used for input validation errors, schema validation failures,
    and data integrity issues.
    """
    pass


class BusinessError(PreclinisetError):
    """Raised when business rules are violated.
    
    Used for domain-specific constraints that are not met,
    such as attempting to randomize an already randomized group.
    """
    pass


class ResourceNotFoundError(PreclinisetError):
    """Raised when a requested resource does not exist.
    
    Used for 404-type errors when querying for entities by ID.
    """
    
    def __init__(self, resource_type: str, resource_id: any, code: Optional[str] = None):
        message = f"{resource_type} with ID '{resource_id}' not found"
        super().__init__(message, code or "RESOURCE_NOT_FOUND")
        self.resource_type = resource_type
        self.resource_id = resource_id


class SecurityError(PreclinisetError):
    """Raised when security or permission checks fail.
    
    Used for authentication failures, authorization errors,
    and access control violations.
    """
    pass

# app/models/enums.py
"""
Enumeration classes for the Precliniset application.
"""
import enum

from flask_babel import lazy_gettext as _l


class WorkplanStatus(enum.Enum):
    """Enumeration for Workplan statuses."""
    DRAFT = 'Draft'
    PLANNED = 'Planned'
    RUNNING = 'Running'
    COMPLETED = 'Completed'
    ARCHIVED = 'Archived'


class WorkplanEventStatus(enum.Enum):
    """Enumeration for Workplan Event statuses."""
    PLANNED = 'Planned'
    COMPLETED = 'Completed'
    SKIPPED = 'Skipped'


class AnalyteDataType(enum.Enum):
    """Enumeration for Analyte data types."""
    FLOAT = 'float'
    INT = 'int'
    TEXT = 'text'
    CATEGORY = 'category'
    DATE = 'date'


class Severity(enum.Enum):
    """Enumeration for Severity levels."""
    NONE = 'None'
    LIGHT = 'Light'
    MODERATE = 'Moderate'
    SEVERE = 'Severe'

    @property
    def level(self):
        """Return numeric level for comparison."""
        return {Severity.NONE: 0, Severity.LIGHT: 1, Severity.MODERATE: 2, Severity.SEVERE: 3}[self]

    def __lt__(self, other):
        return self.level < other.level if self.__class__ is other.__class__ else NotImplemented
    def __le__(self, other):
        return self.level <= other.level if self.__class__ is other.__class__ else NotImplemented
    def __gt__(self, other):
        return self.level > other.level if self.__class__ is other.__class__ else NotImplemented
    def __ge__(self, other):
        return self.level >= other.level if self.__class__ is other.__class__ else NotImplemented


class SampleType(enum.Enum):
    """Enumeration for Sample types."""
    BLOOD = 'Blood'
    URINE = 'Urine'
    BIOLOGICAL_TISSUE = 'Biological Tissue'
    OTHER = 'Other'


class SampleStatus(enum.Enum):
    """Enumeration for Sample statuses."""
    TO_BE_COLLECTED = "To be collected"
    STORED = "Stored"
    SHIPPED = "Shipped"
    DESTROYED = "Destroyed"
    USED_FOR_DERIVATION = "Used for Derivation"
    NOT_COLLECTED = "Not collected"

    @classmethod
    def choices(cls):
        """Return choices for forms."""
        return [(choice.name, _l(choice.value)) for choice in cls]

    @classmethod
    def coerce(cls, item):
        """Coerce string to Enum member."""
        return cls[item] if not isinstance(item, cls) else item

    def __str__(self):
        return str(_l(self.value))


class RegulationCategory(enum.Enum):
    """Enumeration for Controlled Molecule regulation categories."""
    STUPEFIANT = 'Stupéfiant'
    ASSIMILE_STUPEFIANT = 'Assimilé Stupéfiant'
    MOLECULE_CONTROLEE = 'Molécule Contrôlée'
    AUTRE = 'Autre'

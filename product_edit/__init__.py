"""Product-edit planning primitives.

This package deliberately has no dependency on ``app`` or any other workbench.
It defines field metadata and safe in-memory patching only; transport and UI
integration are intentionally deferred to the owning integration task.
"""

from .adapters import PatchError, apply_field_change, get_field_value, parse_selector
from .api import ProductDraftTransport, ProductEditApiClient
from .field_registry import FIELD_SPECS, field_spec
from .models import FieldChange, ProductFieldSpec
from .widget import ProductEditWidget
from .workflow import ProductEditExecution, ProductEditPolicy, ProductEditWorkflow

__all__ = [
    "FIELD_SPECS",
    "FieldChange",
    "PatchError",
    "ProductDraftTransport",
    "ProductEditApiClient",
    "ProductEditExecution",
    "ProductEditPolicy",
    "ProductEditWidget",
    "ProductEditWorkflow",
    "ProductFieldSpec",
    "apply_field_change",
    "field_spec",
    "get_field_value",
    "parse_selector",
]

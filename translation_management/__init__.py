"""Independent translation-management business boundary.

This package deliberately does not import the Qt main window or ``app``.
"""

from .api import TranslationApiClient
from .models import (
    TranslationDiffPlan,
    TranslationFieldSnapshot,
    TranslationOnlineContext,
    TranslationResultRow,
    TranslationSnapshot,
    TranslationTemplateRow,
)
from .widget import TranslationManagementWidget
from .workflow import TranslationWorkflowWorker

__all__ = [
    "TranslationApiClient",
    "TranslationDiffPlan",
    "TranslationFieldSnapshot",
    "TranslationManagementWidget",
    "TranslationOnlineContext",
    "TranslationResultRow",
    "TranslationSnapshot",
    "TranslationTemplateRow",
    "TranslationWorkflowWorker",
]

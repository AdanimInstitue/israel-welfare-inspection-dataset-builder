"""Source discovery components for Gov.il welfare inspection reports."""

from welfare_inspections.collect.models import (
    DiscoveryRunDiagnostics,
    HttpDiagnostic,
    SourceDocumentRecord,
)
from welfare_inspections.collect.portal_discovery import discover_source_documents

__all__ = [
    "DiscoveryRunDiagnostics",
    "HttpDiagnostic",
    "SourceDocumentRecord",
    "discover_source_documents",
]

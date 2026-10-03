"""Extractly: unstructured text in, structured JSON out."""

from .config import settings

__version__ = settings.version
__all__ = ["settings", "__version__"]

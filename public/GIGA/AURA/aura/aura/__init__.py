"""
AURA — Autonomous Universal Resonance Architecture
The new internet. A folder is a node. Files are everything.

Version: 1.0.0
Protocol: v0.4
License: MIT
"""

__version__  = "1.0.0"
__protocol__ = "v0.4"
__author__   = "Aethyr Global"
__email__    = "protocol@aethyr-global.com"
__url__      = "https://github.com/aethyr-global/aura"

from .crypto import Identity
from .folder import FolderAura
from .field  import AuraField
from .config import Config

__all__ = ["Identity", "FolderAura", "AuraField", "Config"]

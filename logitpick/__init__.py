"""logitpick — score declared options from local next-token logprobs."""

from .compact import compact
from .engine import pick
from .gate import gate
from .schema import PickError, PickRequest

__version__ = "0.1.1"
__all__ = ["pick", "gate", "compact", "PickError", "PickRequest", "__version__"]

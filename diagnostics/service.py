"""Compatibility import; implementation lives in PokerFill-AI-Diagnostics."""
import sys
from pokerfill_ai import service as implementation
sys.modules[__name__] = implementation

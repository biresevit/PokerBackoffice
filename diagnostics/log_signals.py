"""Compatibility import; implementation lives in PokerFill-AI-Diagnostics."""
import sys
from pokerfill_ai.integrations.pokerfill import log_signals as implementation
sys.modules[__name__] = implementation

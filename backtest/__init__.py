"""Local backtester for the modular framework (no QuantConnect needed)."""
import os
import sys

_QC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "quantconnect")
if _QC_DIR not in sys.path:
    sys.path.insert(0, _QC_DIR)

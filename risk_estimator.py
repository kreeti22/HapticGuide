"""
risk_estimator.py
------------------
Root wrapper module for RiskEstimator.
Imports RiskEstimator, RiskObject, and estimate_risk from backend/risk_estimator.py.
"""

import sys
from pathlib import Path

# Add backend directory to sys.path if not present
backend_dir = Path(__file__).parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.risk_estimator import RiskEstimator, RiskObject, risk_estimator, estimate_risk

__all__ = ["RiskEstimator", "RiskObject", "risk_estimator", "estimate_risk"]

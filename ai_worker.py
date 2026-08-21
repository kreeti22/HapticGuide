"""
ai_worker.py
------------
Root wrapper entry point for AIWorker.
"""

import sys
import time
from pathlib import Path

# Add backend directory to sys.path if not present
backend_dir = Path(__file__).parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.ai_worker import AIWorker, ai_worker, start_ai_worker, stop_ai_worker

__all__ = ["AIWorker", "ai_worker", "start_ai_worker", "stop_ai_worker"]

if __name__ == "__main__":
    start_ai_worker()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_ai_worker()

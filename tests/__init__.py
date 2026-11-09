import os
import sys

_WORKFLOW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workflow")
if _WORKFLOW not in sys.path:
    sys.path.insert(0, _WORKFLOW)

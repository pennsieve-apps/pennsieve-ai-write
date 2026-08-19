from __future__ import annotations

import sys
import types


try:
    import pennsieve_llm  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("pennsieve_llm")
    stub.Governor = object
    sys.modules["pennsieve_llm"] = stub

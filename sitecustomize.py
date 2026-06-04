"""Interpreter startup customizations for local runs.

This module is imported automatically by Python's site machinery when the
workspace root is on ``sys.path``. On Windows, it switches asyncio to the
selector event loop so psycopg async pools work under uvicorn.
"""

import asyncio
import sys


if sys.platform.startswith("win") and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


"""Test configuration: disable telemetry during the test run.

Set before ``npckks`` is imported so the import-time usage ping is suppressed
when running the test suite.
"""

import os

os.environ["NPCKKS_DISABLE_TELEMETRY"] = "1"

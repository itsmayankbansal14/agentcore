"""AgentCore — tests/integration/
Integration testing framework.

Every integration test exercises the REAL runtime across component
boundaries (Planner → Executor → Tool → Observer → Memory), with only the
external LLM pinned to a deterministic mock. Run:

    pytest -m integration -v
    pytest --cov=. --cov-config=.coveragerc --cov-report=term --cov-report=html:htmlcov

Add a test here for EVERY new feature (enforced by the build gate —
scripts/build.py runs `pytest -m integration` in the smoke stage).
"""

from pathlib import Path
from skills.integration import run_skill_by_name
from skills.types import SkillManifest

class DummyToolResult:
    def __init__(self, ok=True, data=None, error=None):
        self.ok = ok
        self.data = data
        self.error = error

class DummyRegistry:
    def execute(self, name, params, ctx):
        print(f"[registry] {name} {params}")
        if name == "web_search":
            return DummyToolResult(True, f"results for {params.get('query')}")
        if name == "think":
            return DummyToolResult(True, f"summary of {params.get('thought')}")
        return DummyToolResult(False, None, "unknown")

class DummyPermissions:
    def check(self, spec, name, params):
        class R:
            decision = "ALLOWED"
        return R()

result = run_skill_by_name(
    "web-summarize",
    [Path(r"C:\AI\AgentCore\skills\installed")],
    DummyRegistry(),
    DummyPermissions(),
    initial_context={"query": "AgentCore skills"}
)

print("Integration run success:", result.success)
print("Context:", result.context)

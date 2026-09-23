from skills.catalog import SkillCatalog
from skills.executor import SkillExecutor
from pathlib import Path

catalog = SkillCatalog([Path(r"C:\AI\AgentCore\skills\installed")])
manifest = catalog.get("web-summarize")
print("Running skill:", manifest.name)

def fake_tool_executor(tool_name, args):
    # Simulate tools
    print(f"Tool called: {tool_name} args={args}")
    if tool_name == "web_search":
        return {"ok": True, "data": f"Search results for {args.get('query')}"}
    if tool_name == "think":
        return {"ok": True, "data": f"Summary of {args.get('thought')}"}
    return {"ok": False, "data": None}

executor = SkillExecutor(fake_tool_executor)
result = executor.run(manifest, initial_context={"query": "OpenJarvis skills"})
print("Success:", result.success)
print("Context:", result.context)
print("Step results:", result.step_results)

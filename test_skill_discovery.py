from skills.catalog import SkillCatalog
from pathlib import Path

c = SkillCatalog([Path(r"C:\AI\AgentCore\skills\installed")])
print("Discovered:", c.list_names())
m = c.get("web-summarize")
if m:
    print("Manifest name:", m.name)
    print("Description:", m.description)
    print("Tags:", m.tags)
    print("Steps:", [(s.tool_name, s.arguments_template, s.output_key) for s in m.steps])
    print("Markdown:", m.markdown_content[:100])
else:
    print("Not found")

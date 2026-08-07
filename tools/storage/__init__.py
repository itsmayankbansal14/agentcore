"""AgentCore — tools/storage/
Storage backends behind capability interfaces. The Planner reasons about
capabilities (todo_add, todo_list, todo_done) — never about filesystem paths.
Storage implementations (SQLiteTodoStorage today, anything else later) are
interchangeable behind the ABCs and auto-initialize on first use.
"""

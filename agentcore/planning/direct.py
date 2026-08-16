"""AgentCore — planning/direct.py
Deterministic fast-path router.

Single-intent requests (time, weather, todo, clipboard, open-youtube) are
answered by their REAL tool directly — the LLM is never consulted to pick
tools or to phrase the answer for these. The Executor consults this router
BEFORE its LLM loop; a match means a real tool produced the result.

Design constraints:
  * additive seam — Planner/Executor/Registry are untouched structurally
  * conservative matching — ambiguous goals return None → LLM path
  * target_device matters: "open youtube" → browser (windows), but
    "open youtube on my phone" → android_open_youtube
"""
from __future__ import annotations

import re
from typing import Any

YOUTUBE_URL = "https://www.youtube.com"

# multi-intent markers → the direct path must NEVER swallow these; they need
# real planning/LLM (mirrors the Planner's complexity detection)
_COMPLEX = re.compile(
    r"\b(then|next|after that|finally|and then|and|plus|also|with)\b|[,;]", re.I)


class DirectToolRouter:
    """Maps an unambiguous single-intent goal → ordered tool calls.

    Returns None when the goal is chat-like, multi-intent, or ambiguous —
    in that case the normal LLM loop runs unchanged.

    Capability registration (preferred for future tools):
        router.register_capability(
            name="my_feature",
            matcher=lambda low: "my trigger" in low,
            builder=lambda goal, target: [("my_tool", {"arg": ...})]
        )

    Existing hardcoded routes are preserved for backward compatibility.
    New deterministic capabilities should use registration instead of
    adding another if/elif branch.
    """

    def __init__(self) -> None:
        self._capabilities: list[dict] = []   # registered capability handlers

    def register_capability(self, name: str, matcher, builder) -> None:
        """Register a new deterministic capability.
        matcher(low_goal) -> bool
        builder(goal, target_device) -> list[tuple[tool_name, params]] | None
        """
        self._capabilities.append({
            "name": name,
            "matcher": matcher,
            "builder": builder
        })

    def route(self, goal: str, target_device: str = "windows",
              ) -> list[tuple[str, dict[str, Any]]] | None:
        low = " ".join((goal or "").lower().split())
        if not low:
            return None

        # 1) Try registered capabilities first (future-proof path)
        for cap in self._capabilities:
            if cap["matcher"](low):
                result = cap["builder"](goal, target_device)
                if result is not None:
                    return result

        # personal-memory commands are checked FIRST: their payload is a
        # description, not a second intent — "save this website … and I could
        # use it for X" must not be blocked by the complexity guard.
        personal = self._route_personal(low, goal=goal)
        if personal is not None:
            return personal
        # single-intent only: multi-command goals go through the planner/LLM
        if _COMPLEX.search(low):
            return None

        # --- time → TimeTool -------------------------------------------
        if re.search(r"\b(time|clock|date|day)\b", low) and re.search(
                r"\b(what|current|now|tell|today)\b|is it", low):
            return [("time_now", {})]

        # --- weather → WeatherTool -------------------------------------
        if "weather" in low:
            city = self._city(low)
            return [("weather", {"city": city})]

        # --- todo → Todo capability ------------------------------------
        if low.startswith(("add ", "create ")) and re.search(
                r"\b(todo|task|reminder)\b", low):
            return [("todo_add", self._todo_params(low))]
        if re.search(r"\b(todos?|tasks?|reminders?)\b", low) and re.search(
                r"\b(list|show|what|get|pending|open)\b", low):
            return [("todo_list", {})]

        # --- clipboard → Clipboard capability --------------------------
        if "clipboard" in low or low.startswith("copy ") or low.startswith("paste"):
            return self._clipboard(low)

        # --- open youtube → browser (windows) / android device ----------
        if re.search(r"\byoutube\b", low) and re.search(
                r"\b(open|launch|start)\b", low):
            # explicit phone target in the goal wins even if the caller did
            # not run target resolution (e.g. direct run_step calls)
            wants_android = (target_device == "android" or
                             re.search(r"\b(phone|android|mobile)\b", low))
            if wants_android:
                return [("android_open_youtube", {"query": self._yt_query(low)})]
            url = YOUTUBE_URL
            q = self._yt_query(low)
            if q:
                from urllib.parse import quote
                url = "https://www.youtube.com/results?search_query=" + quote(q)
            return [("browser_open", {}),
                    ("browser_navigate", {"url": url})]

        return None

    def _route_personal(self, low: str, goal: str = "") -> list[tuple[str, dict[str, Any]]] | None:
        """Deterministic personal-memory commands. Returns None when the goal
        is not a personal command (caller continues normal routing).
        Matching runs on the lowercased goal; EXTRACTION uses the original
        text so proper nouns (UPI, OpenRouter) keep their case."""
        orig = goal or low
        if low.startswith(("save this website", "save the website")):
            calls = self._save_website(orig)
            return calls  # None → not parseable → LLM path (has the tool)
        if low.startswith(("save this idea", "save an idea", "save the idea",
                           "save idea")):
            return self._save_idea(orig)
        if low.startswith(("save this note", "save a note", "save note")):
            return self._save_note(orig)
        if re.search(r"\b(list|show|get)\b.*\bsaved\b|"
                     r"what (?:did|have|do) i (?:save|saved|have)\b", low):
            return [("saved_list", {})]
        if re.search(r"\b(briefing|brief me|what should i know|what's new|"
                     r"what do you remember)\b", low):
            return [("personal_briefing", {})]
        return None

    # -- param extraction ------------------------------------------------
    @staticmethod
    def _city(low: str) -> str:
        m = re.search(r"\bweather\s+(?:in|for|at|of)\s+([a-z][a-z .'\-]{1,40})$", low)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _todo_params(low: str) -> dict[str, Any]:
        priority = "medium"
        for p in ("high", "medium", "low"):
            if re.search(rf"\b{p}\s+priority\b|\b{p}\b", low) and \
                    re.search(rf"\b{p}\s+priority\b", low):
                priority = p
                break
        task = re.sub(r"^(add|create|make)\s+", "", low)
        task = re.sub(r"\b(a|an|the)\s+", " ", task)
        task = re.sub(r"\b(todos?|tasks?|reminders?)\b", " ", task)
        task = re.sub(r"\b(to|for|on|my|me)\b", " ", task)
        task = re.sub(r"\b(high|medium|low)\s+priority\b", " ", task)
        task = re.sub(r"\s+", " ", task).strip(" .")
        return {"task": task or low, "priority": priority}

    @staticmethod
    def _yt_query(low: str) -> str:
        q = re.sub(r"^(open|launch|start)\s+", "", low)
        q = re.sub(r"\byoutube\b", " ", q)
        q = re.sub(r"\b(on|in|via|using|through|from)\s+(?:my\s+)?"
                   r"(?:[\w'\-]+\s+)?"
                   r"(phone|android|mobile|browser|laptop|pc|windows|computer|device)\b",
                   " ", q)
        q = re.sub(r"\b(the|and|please|can you|just)\b", " ", q)
        q = re.sub(r"\s+", " ", q).strip(" .")
        return q

    # -- personal memory extraction ----------------------------------------
    @staticmethod
    def _save_website(text: str) -> list[tuple[str, dict[str, Any]]] | None:
        m = re.search(r"(https?://\S+|www\.\S+)", text)
        if not m:
            return None     # no URL → let the LLM path handle it
        url = m.group(1).rstrip(".,;")
        tail = text[m.end():].strip(" .,;")
        # name = the website's domain, prettified
        host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0].split("?")[0]
        name = host.replace(".", " ").title() if host else url
        purpose = usage = ""
        pm = re.search(
            r"\b(?:useful|great|good|used)\s+for\s+([^.,;]+?)"
            r"(?=\s+(?:and|so|which|that)\s+[a-z]|$)", tail, re.I)
        if pm:
            purpose = pm.group(1).strip()
        um = re.search(r"\b(?:i\s+)?(?:could|can|want|plan|need|use|using)\s+"
                       r"(?:it|this|them)?\s*(?:for|to)\s+([^.,;]+)", tail, re.I)
        if um:
            usage = um.group(1).strip()
        # description: everything after the URL (kept verbatim)
        description = tail or purpose
        return [("save_website", {"url": url, "name": name,
                                  "description": description,
                                  "purpose": purpose, "usage": usage})]

    @staticmethod
    def _save_idea(text: str) -> list[tuple[str, dict[str, Any]]]:
        rest = re.sub(r"^save (?:this |an |the )?idea\s*[:,\-]?\s*", "", text, flags=re.I)
        title, _, desc = rest.partition(":")
        title = title.strip().strip(".")
        desc = desc.strip()
        if not title:
            title = desc
            desc = ""
        return [("save_idea", {"title": title, "description": desc})]

    @staticmethod
    def _save_note(text: str) -> list[tuple[str, dict[str, Any]]]:
        rest = re.sub(r"^save (?:this |a )?note\s*[:,\-]?\s*", "", text, flags=re.I)
        return [("save_note", {"title": rest[:60].strip(".") or "note",
                               "body": rest})]

    @staticmethod
    def _clipboard(low: str) -> list[tuple[str, dict[str, Any]]]:
        # "copy <something> [to clipboard]" → set
        m = re.search(r"\bcopy\s+(.+?)(?:\s+to\s+clipboard)?$", low)
        if m and len(m.group(1).strip()) >= 2:
            return [("clipboard_set", {"text": m.group(1).strip()})]
        # "set clipboard to <x>" / "put <x> on clipboard" → set
        m = re.search(r"\b(?:set|put)\s+(?:the\s+)?clipboard\s+(?:to|with)\s+(.+)$", low)
        if m:
            return [("clipboard_set", {"text": m.group(1).strip()})]
        # "what's on the clipboard" / "paste" / "get clipboard" → get
        return [("clipboard_get", {})]


def describe(tool_name: str, result) -> str:
    """Natural-language rendering of a direct-path tool result.
    Kept here so the Executor's fast path needs no LLM for the answer text."""
    d = result.data or {}
    if tool_name == "time_now":
        return f"🕐 It is {d.get('now', 'now')}."
    if tool_name == "weather":
        return (f"🌤 Weather in {d.get('city', 'your city')}: {d.get('condition')}, "
                f"{d.get('temp_c')}°C, wind {d.get('wind_kmh')} km/h "
                f"(source: {d.get('source', 'open-meteo')}).")
    if tool_name == "todo_add":
        return (f"✅ Added todo #{d.get('id')}: “{d.get('task')}” "
                f"({d.get('priority')} priority).")
    if tool_name == "todo_list":
        todos = d.get("todos", [])
        if not todos:
            return "📋 No pending todos."
        lines = [f"{t.get('id')}. {t.get('task')} [{t.get('priority')}]"
                 for t in todos]
        return "📋 Todos:\n" + "\n".join("  " + ln for ln in lines)
    if tool_name == "clipboard_set":
        return "📋 Copied to clipboard."
    if tool_name == "clipboard_get":
        return f"📋 Clipboard: {d.get('text') or '(empty)'}"
    if tool_name == "browser_open":
        return "🌐 Browser opened (headless Chromium)."
    if tool_name == "browser_navigate":
        url = d.get("url", "")
        if "youtube.com" in str(url):
            return f"▶️ Opened YouTube in the browser: {url}"
        return f"🌐 Navigated to {url}."
    if tool_name == "browser_verify_url":
        return (f"✅ URL verified: {d.get('url')}." if result.ok
                else f"❌ URL check failed: {d}")
    if tool_name == "android_open_youtube":
        return "📱 Opened YouTube on your phone."
    if tool_name == "save_website":
        return f"💾 Saved website “{d.get('name')}” — {d.get('url')}"
    if tool_name == "save_idea":
        return f"💡 Saved idea: “{d.get('title')}”"
    if tool_name == "save_note":
        return f"📝 Saved note: “{d.get('title')}”"
    if tool_name == "saved_list":
        items = d.get("items", [])
        if not items:
            return "🗂 Nothing saved yet."
        lines = [f"  {i.get('id')}. [{i.get('kind')}] {i.get('title')}"
                 + (f" — {i.get('url')}" if i.get("url") else "")
                 for i in items]
        return "🗂 Saved items:\n" + "\n".join(lines)
    if tool_name == "personal_briefing":
        return d.get("briefing", "(no briefing)")
    return str(d)

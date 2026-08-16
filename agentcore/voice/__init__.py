"""AgentCore — voice

Voice is AgentCore's PRIMARY interface. This package is a dedicated voice
subsystem, completely separate from the agent runtime:

    Microphone → audio.input → STT → text
        → orchestrator.handle_user_message (SAME input as chat)
        → response → TTS → speaker

The Planner/Executor/Runtime never depend on microphone or speaker code.
Voice input is normalized into the exact same user-input representation chat
uses, and every response also lands in the chat transcript.
"""

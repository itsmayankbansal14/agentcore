"""AgentCore — voice.audio
Audio capture (microphone / WAV file), end-of-speech detection (VAD), and
playback. The microphone requires an audio device (Windows); the WAV source
is used for tests. No fake audio — devices are probed and errors are honest.
"""

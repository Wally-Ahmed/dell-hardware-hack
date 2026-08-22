"""RushCut agent: tool-calling loop against the local Ollama brain.

Public surface: `backend.agent.router.router` (mount into the FastAPI app)
and `backend.agent.loop.AgentLoop` (drive the loop directly, e.g. from the
NemoClaw sandbox fallback).
"""

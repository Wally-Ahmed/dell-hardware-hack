"""Model residency ledger. The GB10's 128 GB is unified, so "loaded" is a
budget line rather than a hard fact — we enforce the ComfyUI slice of the
registry's budgetGb by LRU-evicting unpinned residents before each load.
One ledger for everything (the brain nominally belongs to the llm slice) is
the demo simplification; the numbers still keep us honest.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from backend.core.config import settings
from backend.core.ws import hub

# The §4 wire shape is the registry minus paths — the frontend and the agent
# never learn where weights live on disk.
REGISTRY_FIELDS = (
    "id",
    "task",
    "tier",
    "precision",
    "approxGb",
    "loadSeconds",
    "license",
    "bestFor",
)


class ModelManager:
    def __init__(self, registry_path: Path | None = None, *, simulate: bool = True) -> None:
        data = json.loads(Path(registry_path or settings.registry_path).read_text())
        self._budget: dict[str, float] = data["budgetGb"]
        self._registry: dict[str, dict[str, Any]] = {m["id"]: m for m in data["models"]}
        self._state: dict[str, str] = {mid: "idle" for mid in self._registry}
        self._pinned: set[str] = set()
        self._lru: list[str] = []  # resident ids, least recently used first
        # True in the Codespace: loads are instant. On the box, loadSeconds is
        # real time handed to ollama/ComfyUI loaders.
        self._simulate = simulate

    def entry(self, model_id: str) -> dict[str, Any]:
        m = self._registry[model_id]
        return {
            **{k: m[k] for k in REGISTRY_FIELDS},
            "state": self._state[model_id],
            "pinned": model_id in self._pinned,
        }

    def list(self) -> list[dict[str, Any]]:
        return [self.entry(mid) for mid in self._registry]

    def budget(self) -> dict[str, Any]:
        return {"budgetGb": self._budget, "totalGb": 128, "usedGb": self._used_gb()}

    async def ensure(self, model_id: str) -> dict[str, Any]:
        """Make `model_id` resident, evicting LRU unpinned residents until it
        fits under the ComfyUI budget slice. Pinned models are never victims —
        if everything left is pinned, loading fails loudly instead."""
        incoming = self._registry[model_id]
        if self._state[model_id] == "resident":
            self._touch(model_id)
            return self.entry(model_id)

        cap = self._budget["comfyui"]
        while self._used_gb() + incoming["approxGb"] > cap:
            victim = next((mid for mid in self._lru if mid not in self._pinned), None)
            if victim is None:
                raise RuntimeError(
                    f"cannot load {model_id}: {cap} GB budget is fully pinned"
                )
            await self._set_state(victim, "evicting")
            self._lru.remove(victim)
            await self._set_state(victim, "idle")

        await self._set_state(model_id, "loading")
        if not self._simulate:
            await asyncio.sleep(incoming["loadSeconds"])
        await self._set_state(model_id, "resident")
        self._lru.append(model_id)
        return self.entry(model_id)

    async def pin(self, model_id: str, pinned: bool) -> dict[str, Any]:
        if model_id not in self._registry:  # fail before mutating anything
            raise KeyError(model_id)
        if pinned:
            self._pinned.add(model_id)
        else:
            self._pinned.discard(model_id)
        # Pinned is part of the §4 frame, so it broadcasts like a state change.
        await hub.models(self.list())
        return self.entry(model_id)

    def _used_gb(self) -> float:
        used = sum(
            self._registry[mid]["approxGb"]
            for mid, state in self._state.items()
            if state == "resident"
        )
        return round(used, 1)

    def _touch(self, model_id: str) -> None:
        # Re-ensuring a resident model refreshes its recency, nothing else.
        self._lru.remove(model_id)
        self._lru.append(model_id)

    async def _set_state(self, model_id: str, state: str) -> None:
        self._state[model_id] = state
        await hub.models(self.list())

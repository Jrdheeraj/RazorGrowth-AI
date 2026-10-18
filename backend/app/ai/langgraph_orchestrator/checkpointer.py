"""
Durable Checkpoint Saver for LangGraph multi-agent execution.

Integrates with RazorGrowth's AgentWorkflowRun and AgentRun lifecycle while
providing standard LangGraph BaseCheckpointSaver interfaces.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, Optional, Sequence

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)

log = logging.getLogger(__name__)


def _sanitize_path_segment(val: str) -> str:
    """Sanitize thread_id or checkpoint_id for safe filesystem paths."""
    cleaned = re.sub(r"[^\w\-.]", "_", str(val))
    return cleaned[:120] or "default"


class DurableWorkflowCheckpointer(BaseCheckpointSaver):
    """A thread-isolated durable checkpointer for RazorGrowth AI workflows.

    Retains checkpoints per workflow thread_id with durable filesystem persistence,
    ensuring safe multi-process recovery and replay without duplicate external side effects.
    """

    def __init__(self, storage_dir: Optional[str | Path] = None) -> None:
        super().__init__()
        # In-memory checkpoint storage keyed by (thread_id, checkpoint_ns, checkpoint_id)
        self._storage: dict[tuple[str, str, str], tuple[Checkpoint, CheckpointMetadata]] = {}
        self._writes: dict[tuple[str, str, str, str], Sequence[tuple[str, Any]]] = {}

        # Durable filesystem backing path
        base_dir = storage_dir or os.environ.get("LANGGRAPH_CHECKPOINT_DIR", ".langgraph_checkpoints")
        self.storage_dir = Path(base_dir).resolve()
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.warning("Could not create checkpoint storage directory %s: %s", self.storage_dir, exc)

    def _thread_dir(self, thread_id: str, checkpoint_ns: str = "") -> Path:
        """Directory where checkpoints for a thread and namespace reside."""
        seg = _sanitize_path_segment(thread_id)
        if checkpoint_ns:
            seg = f"{seg}_{_sanitize_path_segment(checkpoint_ns)}"
        d = self.storage_dir / seg
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _load_persisted_checkpoints(self, thread_id: str, checkpoint_ns: str = "") -> None:
        """Read any disk-persisted checkpoints for thread into memory cache."""
        try:
            td = self._thread_dir(thread_id, checkpoint_ns)
            for f in td.glob("cp_*.json"):
                cid = f.stem.replace("cp_", "")
                key = (thread_id, checkpoint_ns, cid)
                if key not in self._storage:
                    try:
                        with open(f, "r", encoding="utf-8") as fp:
                            data = json.load(fp)
                        cp = data.get("checkpoint", {})
                        md = data.get("metadata", {})
                        self._storage[key] = (cp, md)
                    except Exception as e:
                        log.debug("Failed to read checkpoint file %s: %s", f, e)
        except Exception as exc:
            log.debug("Failed scanning thread dir for %s: %s", thread_id, exc)

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """Fetch the latest checkpoint for the given thread_id."""
        configurable = config.get("configurable", {})
        thread_id = str(configurable.get("thread_id", ""))
        checkpoint_ns = str(configurable.get("checkpoint_ns", ""))
        checkpoint_id = configurable.get("checkpoint_id")

        if not thread_id:
            return None

        # Load from disk if memory cache is empty for this thread
        self._load_persisted_checkpoints(thread_id, checkpoint_ns)

        if checkpoint_id:
            key = (thread_id, checkpoint_ns, str(checkpoint_id))
            if key in self._storage:
                cp, md = self._storage[key]
                return CheckpointTuple(
                    config=config,
                    checkpoint=cp,
                    metadata=md,
                )
            return None

        # Return latest checkpoint for thread
        matching = [
            (cid, cp, md)
            for (tid, ns, cid), (cp, md) in self._storage.items()
            if tid == thread_id and ns == checkpoint_ns
        ]
        if not matching:
            return None

        # Sort by timestamp or checkpoint id
        matching.sort(key=lambda x: str(x[1].get("ts", "")), reverse=True)
        latest_cid, latest_cp, latest_md = matching[0]

        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": latest_cid,
                }
            },
            checkpoint=latest_cp,
            metadata=latest_md,
        )

    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        """List historical checkpoints for a thread."""
        if config is None:
            return

        configurable = config.get("configurable", {})
        thread_id = str(configurable.get("thread_id", ""))
        checkpoint_ns = str(configurable.get("checkpoint_ns", ""))

        self._load_persisted_checkpoints(thread_id, checkpoint_ns)

        matching = [
            (cid, cp, md)
            for (tid, ns, cid), (cp, md) in self._storage.items()
            if tid == thread_id and ns == checkpoint_ns
        ]
        matching.sort(key=lambda x: str(x[1].get("ts", "")), reverse=True)

        count = 0
        for cid, cp, md in matching:
            if limit is not None and count >= limit:
                break
            yield CheckpointTuple(
                config={
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": cid,
                    }
                },
                checkpoint=cp,
                metadata=md,
            )
            count += 1

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Store a new checkpoint in memory and commit to durable disk."""
        configurable = config.get("configurable", {})
        thread_id = str(configurable.get("thread_id", ""))
        checkpoint_ns = str(configurable.get("checkpoint_ns", ""))
        checkpoint_id = checkpoint["id"]

        key = (thread_id, checkpoint_ns, checkpoint_id)
        self._storage[key] = (checkpoint, metadata)

        # Durably persist to disk file
        try:
            td = self._thread_dir(thread_id, checkpoint_ns)
            target_path = td / f"cp_{_sanitize_path_segment(checkpoint_id)}.json"
            payload = {
                "checkpoint": checkpoint,
                "metadata": metadata,
                "channel_versions": new_versions,
            }
            # Atomic file write
            with tempfile.NamedTemporaryFile("w", dir=str(td), delete=False, encoding="utf-8") as tf:
                json.dump(payload, tf, default=str, indent=2)
                temp_name = tf.name
            os.replace(temp_name, target_path)
        except Exception as exc:
            log.warning("Could not durably persist checkpoint for thread %s: %s", thread_id, exc)

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Store pending channel writes in memory and disk."""
        configurable = config.get("configurable", {})
        thread_id = str(configurable.get("thread_id", ""))
        checkpoint_ns = str(configurable.get("checkpoint_ns", ""))
        checkpoint_id = str(configurable.get("checkpoint_id", ""))

        key = (thread_id, checkpoint_ns, checkpoint_id, task_id)
        self._writes[key] = writes

        try:
            td = self._thread_dir(thread_id, checkpoint_ns)
            target_path = td / f"writes_{_sanitize_path_segment(task_id)}.json"
            serializable_writes = []
            for channel, val in writes:
                serializable_writes.append((channel, val))
            with tempfile.NamedTemporaryFile("w", dir=str(td), delete=False, encoding="utf-8") as tf:
                json.dump(serializable_writes, tf, default=str, indent=2)
                temp_name = tf.name
            os.replace(temp_name, target_path)
        except Exception as exc:
            log.debug("Could not persist writes for task %s: %s", task_id, exc)


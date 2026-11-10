"""Types provided by the interface.ai assignment scoring harness."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

@dataclass(frozen=True)
class Page:
    url: str
    title: str
    markdown: str
    fetched_at: str

@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    taken_on: str
    pages: list[Page]

@dataclass
class Source:
    url: str
    snapshot_id: Optional[str] = None
    quote: Optional[str] = None

@dataclass
class Answer:
    text: str
    sources: list[Source] = field(default_factory=list)
    confident: bool = True
    conflict_note: Optional[str] = None

@dataclass
class Conflict:
    topic: str
    values: list[str]
    sources: list[Source]
    resolution: Optional[str] = None
    reason: Optional[str] = None

@runtime_checkable
class KnowledgeSystem(Protocol):
    def ingest(self, snapshot: Snapshot) -> None: ...
    def answer(self, question: str, as_of: Optional[str] = None) -> Answer: ...
    def conflicts(self) -> list[Conflict]: ...

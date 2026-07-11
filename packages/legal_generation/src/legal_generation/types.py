"""Shared conversation types for multi-turn generation -- see ADR-0003."""

from dataclasses import dataclass


@dataclass
class ConversationTurn:
    question: str
    answer: str

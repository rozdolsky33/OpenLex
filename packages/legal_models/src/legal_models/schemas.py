import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class QueryRequest(BaseModel):
    question: str
    doc_type: Literal["statute", "case"] | None = None
    top_k: int = 8
    conversation_id: str | None = None


class Citation(BaseModel):
    citation: str
    doc_type: str
    title: str | None = None
    court: str | None = None
    date: str | None = None
    url: str | None = None
    snippet: str


DISCLAIMER = (
    "This tool provides general legal information about New York landlord-tenant "
    "law, not legal advice. It is not a substitute for consultation with a "
    "licensed attorney and does not create an attorney-client relationship."
)


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    abstained: bool
    disclaimer: str = DISCLAIMER
    conversation_id: str | None = None


class IngestRequest(BaseModel):
    source: Literal["statutes", "cases", "all"] = "all"
    force: bool = False


class IngestResponse(BaseModel):
    status: str
    documents_ingested: int
    chunks_created: int
    errors: list[str] = []


class HealthResponse(BaseModel):
    status: str
    db: bool
    embedding_model_loaded: bool


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class UserPublic(BaseModel):
    id: uuid.UUID
    email: EmailStr
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

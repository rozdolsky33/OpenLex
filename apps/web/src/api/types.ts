// Mirrors packages/legal_models/src/legal_models/schemas.py exactly -- keep in sync when
// those pydantic models change.

export type DocType = "statute" | "case";

export interface QueryRequest {
  question: string;
  doc_type?: DocType | null;
  top_k?: number;
  conversation_id?: string | null;
}

export interface Citation {
  citation: string;
  doc_type: string;
  title: string | null;
  court: string | null;
  date: string | null;
  url: string | null;
  snippet: string;
}

export type Tier = "silver" | "gold" | "platinum";

export interface UserStatus {
  email: string;
  tier: Tier;
  request_count: number;
  request_limit: number;
  period_reset_at: string;
}

export interface QueryResponse {
  answer: string;
  citations: Citation[];
  abstained: boolean;
  disclaimer: string;
  conversation_id: string | null;
  usage: UserStatus | null;
}

export interface UserCreate {
  email: string;
  password: string;
}

export interface UserPublic {
  id: string;
  email: string;
  created_at: string;
}

export interface Token {
  access_token: string;
  token_type: string;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  db: boolean;
  embedding_model_loaded: boolean;
}

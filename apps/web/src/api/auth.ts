import { request, requestJson } from "./client";
import type { Token, UserCreate, UserPublic, UserStatus } from "./types";

export function registerUser(email: string, password: string): Promise<UserPublic> {
  const body: UserCreate = { email, password };
  return requestJson<UserPublic>("/auth/register", "POST", body, { auth: false });
}

// FastAPI's OAuth2PasswordRequestForm expects application/x-www-form-urlencoded with
// `username`/`password` fields, not a JSON body -- URLSearchParams as the fetch body sets
// that content-type automatically.
export function loginUser(email: string, password: string): Promise<Token> {
  const formBody = new URLSearchParams({ username: email, password });
  return request<Token>("/auth/login", { method: "POST", body: formBody, auth: false });
}

export function getMe(): Promise<UserStatus> {
  return request<UserStatus>("/auth/me");
}

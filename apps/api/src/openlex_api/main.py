from fastapi import FastAPI

app = FastAPI(title="OpenLex API")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}

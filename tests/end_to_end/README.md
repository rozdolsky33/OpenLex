# End-to-end tests

Full-stack smoke test driving the running `docker-compose` stack over real HTTP (see
`test_smoke.py`'s module docstring for exact setup/run commands). Proves the golden path --
login, ask a question, get a cited, disclaimered answer -- actually works end-to-end. This is
deliberately narrow: it does not re-check citation *accuracy* (see `tests/evaluation/` for
that), only that the full request path (auth -> retrieval -> generation -> response shape) is
alive.

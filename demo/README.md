# CloudAgent runnable demo

MVP application code and Docker sandbox image live here. Project specs stay in `../.claude/docs/`.

## Sandbox image

```bash
cd demo
docker build -t cloudagent-sandbox:latest .
```

## Run API + worker

Ubuntu blocks system `pip` (PEP 668). Use the project venv:

```bash
cd demo
./scripts/setup-venv.sh        # once: creates .venv and installs requirements.txt
source scripts/load-env.sh     # TOGETHER_API_KEY
source .venv/bin/activate
python run.py
```

Or without activating: `.venv/bin/python run.py`

Open http://localhost:8000 for the UI.

## Acceptance script

```bash
cd demo
./scripts/demo.sh http://localhost:8000
```

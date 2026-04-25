.PHONY: test test-unit test-golden eval-ragas list-results show-results show-verbose show-failures diff-results up down rebuild logs deploy restart nas-logs

# Run the standard unit test suite (no live server needed)
test-unit:
	cd backend && python -m pytest tests/test_auth.py tests/test_memory.py tests/test_rag.py -v

# Run the golden Q&A harness against the live server (requires docker compose up).
#
# Tag a run with LABEL so you can compare it later:
#   make test-golden LABEL=gpt-4o
#   make test-golden LABEL=after-memory-update
#
# Results land in logs/golden_results_<label>.json AND logs/golden_results_latest.json.
test-golden:
	BASE_URL=http://localhost:5173 LABEL=$(LABEL) python3 -m pytest tests/test_golden.py -v --tb=short 2>&1 | tee logs/golden_run_latest.txt

# Run the RAGAS evaluation (requires OPENAI_API_KEY + live server)
eval-ragas:
	python tests/eval_ragas.py

# ── result inspection ─────────────────────────────────────────────────────────

# List all saved runs: date, score, model/provider, label
list-results:
	python3 tests/show_results.py --list

# Compact table of the latest run. Override: make show-results FILE=logs/golden_results_gpt-4o.json
show-results:
	python3 tests/show_results.py $(FILE)

# Full responses + retrieved chunk details per case
show-verbose:
	python3 tests/show_results.py $(FILE) --verbose

# Only show failing cases
show-failures:
	python3 tests/show_results.py $(FILE) --failures-only

# Compare two runs: regressions, fixes, response changes, chunk diffs.
# Usage: make diff-results FILE_A=logs/golden_results_a.json FILE_B=logs/golden_results_b.json
diff-results:
	python3 tests/show_results.py $(FILE_A) $(FILE_B)

# ── docker ────────────────────────────────────────────────────────────────────

up:
	docker compose up -d

rebuild:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f backend

# ── NAS deployment ────────────────────────────────────────────────────────────

NAS_HOST  = storybrew@192.168.68.200
NAS_PATH  = /volume1/docker/digital_twin

deploy:
	tar --no-xattrs \
	    --exclude='.git' \
	    --exclude='backend/__pycache__' \
	    --exclude='backend/.venv' \
	    --exclude='frontend/node_modules' \
	    --exclude='chroma_db' \
	    --exclude='data' \
	    --exclude='logs' \
	    --exclude='memory' \
	    --exclude='.env' \
	    --exclude='credentials.yaml' \
	    -czf /tmp/digital-twin-deploy.tar.gz .
	scp /tmp/digital-twin-deploy.tar.gz $(NAS_HOST):$(NAS_PATH)/
	ssh -t $(NAS_HOST) "cd $(NAS_PATH) && tar -xzf digital-twin-deploy.tar.gz && rm digital-twin-deploy.tar.gz && sudo docker-compose up --build -d"

restart:
	ssh -t $(NAS_HOST) "cd $(NAS_PATH) && sudo docker-compose restart"

nas-logs:
	ssh -t $(NAS_HOST) "cd $(NAS_PATH) && sudo docker-compose logs --tail=50 -f"

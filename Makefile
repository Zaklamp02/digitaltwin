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

# ── NAS deployment (dual-runtime) ────────────────────────────────────────────

NAS_HOST  = Storybrew@192.168.68.200
NAS_SHARED = /volume1/docker/shared-code
NAS_PUBLIC = /volume1/docker/digital_twin_public
NAS_INTERNAL = /volume1/docker/digital_twin_internal

# Deploy code to NAS (shared codebase for both stacks)
deploy-code:
	@echo "Syncing shared code to NAS (public & internal stacks use same codebase)..."
	rsync -av --exclude='.git' \
	    --exclude='node_modules' \
	    --exclude='__pycache__' \
	    --exclude='.venv' \
	    --exclude='backend/.pytest_cache' \
	    --exclude='data*' \
	    --exclude='chroma_db*' \
	    --exclude='logs*' \
	    --exclude='vault' \
	    --exclude='.env' \
	    --exclude='credentials.yaml' \
	    . $(NAS_HOST):$(NAS_SHARED)/
	@echo "✓ Code deployed to NAS shared directory"

# Build and start both public and internal stacks
deploy-stacks: deploy-code
	@echo "Building and starting public stack..."
	ssh -t $(NAS_HOST) "cd $(NAS_PUBLIC) && sudo docker-compose up -d --build"
	@echo "Building and starting internal stack..."
	ssh -t $(NAS_HOST) "cd $(NAS_INTERNAL) && sudo docker-compose up -d --build"
	@echo "✓ Both stacks are running"

# Restart both stacks (without rebuild)
restart:
	@echo "Restarting public stack..."
	ssh -t $(NAS_HOST) "cd $(NAS_PUBLIC) && sudo docker-compose restart"
	@echo "Restarting internal stack..."
	ssh -t $(NAS_HOST) "cd $(NAS_INTERNAL) && sudo docker-compose restart"
	@echo "✓ Both stacks restarted"

# View logs for public stack
logs-public:
	ssh -t $(NAS_HOST) "cd $(NAS_PUBLIC) && sudo docker-compose logs -f --tail=50"

# View logs for internal stack
logs-internal:
	ssh -t $(NAS_HOST) "cd $(NAS_INTERNAL) && sudo docker-compose logs -f --tail=50"

# View logs for both stacks (public first, then internal)
nas-logs: logs-public

# Publish public projection (sync public-role data from internal to public)
publish-projection:
	@echo "Publishing public projection..."
	ssh $(NAS_HOST) "cd $(NAS_INTERNAL) && sudo docker-compose exec -T backend-internal python scripts/publish_public_projection.py \
	  --internal-db /app/data_internal/knowledge.db \
	  --public-db $(NAS_PUBLIC)/data_public/knowledge.db \
	  --internal-chroma /app/chroma_db_internal \
	  --public-chroma $(NAS_PUBLIC)/chroma_db_public"
	@echo "Restarting public backend to pick up new data..."
	ssh $(NAS_HOST) "cd $(NAS_PUBLIC) && sudo docker-compose restart backend-public"
	@echo "✓ Public projection published and public backend restarted"

# Status of both stacks
status:
	@echo "=== Public Stack Status ===" && \
	ssh $(NAS_HOST) "cd $(NAS_PUBLIC) && sudo docker-compose ps" && \
	echo "\n=== Internal Stack Status ===" && \
	ssh $(NAS_HOST) "cd $(NAS_INTERNAL) && sudo docker-compose ps"

# Stop both stacks
stop:
	@echo "Stopping public stack..."
	ssh $(NAS_HOST) "cd $(NAS_PUBLIC) && sudo docker-compose down"
	@echo "Stopping internal stack..."
	ssh $(NAS_HOST) "cd $(NAS_INTERNAL) && sudo docker-compose down"
	@echo "✓ Both stacks stopped"

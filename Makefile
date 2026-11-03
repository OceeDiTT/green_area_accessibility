.PHONY: prod-up prod-load prod-logs prod-status install test lint run status serve dashboard docker-build docker-run docker-up docker-down smoke
install:        ## local dev install (needs a working geospatial stack; conda-forge recommended)
	pip install -e ".[pipeline,api,dashboard,dev]"
test:
	pytest -q
lint:
	ruff check src tests
run:            ## run the pipeline once
	greenspace run
status:
	greenspace status
serve:
	greenspace serve
dashboard:
	API_URL=http://localhost:8000 streamlit run src/greenspace/dashboard/app.py
docker-build:
	docker compose --profile jobs --profile scheduler build
docker-run:     ## first data load
	docker compose --profile jobs run --rm pipeline
docker-up:
	docker compose up -d api dashboard
docker-down:
	docker compose down
smoke:          ## quick API check
	curl -fsS localhost:8000/ready && curl -fsS "localhost:8000/v1/ranking?limit=3" && echo

PROD = docker compose -f deploy/docker-compose.yml --env-file deploy/.env
prod-up:        ## build + start the production stack
	$(PROD) up -d --build
prod-load:      ## manual data refresh
	$(PROD) --profile jobs run --rm pipeline
prod-logs:
	$(PROD) logs -f --tail=100
prod-status:
	$(PROD) ps

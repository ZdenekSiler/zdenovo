# zdenovo — Deployment automation
# Usage: make <target>  (see 'make help' for full list)
#
# Local targets:  dev, test, build
# Server targets: prod, cert-init, cert-renew, check, logs
# Remote targets: deploy-first, deploy  (SSH from local machine)

-include .env
export

COMPOSE_PROD := docker compose -f docker-compose.prod.yml
SSH_CMD := ssh $(SERVER_USER)@$(SERVER_HOST)

.DEFAULT_GOAL := help

# ─── Help ─────────────────────────────────────────────────────────────────────

.PHONY: help
help:
	@echo ""
	@echo "  zdenovo deployment targets"
	@echo ""
	@echo "  LOCAL DEV"
	@echo "    make dev           Start dev server (http://localhost:8080)"
	@echo "    make dev-logs      Tail dev container logs"
	@echo "    make test          Run test suite with coverage"
	@echo "    make dev-down      Stop and remove dev containers"
	@echo ""
	@echo "  PRODUCTION (run on server OR via make deploy)"
	@echo "    make prod          Build and start production stack"
	@echo "    make prod-logs     Tail production logs"
	@echo "    make prod-stop     Stop production containers (data preserved)"
	@echo "    make prod-down     Remove production containers (data preserved)"
	@echo "    make check         Health check: HTTPS, redirect, API"
	@echo ""
	@echo "  SSL CERTIFICATES"
	@echo "    make cert-init     Bootstrap SSL certificate (first time only)"
	@echo "    make cert-renew    Force certificate renewal"
	@echo ""
	@echo "  REMOTE DEPLOYMENT (run locally — SSHes into Hetzner)"
	@echo "    make deploy-first  One-time server setup + first deploy"
	@echo "    make deploy        Push updates to production server"
	@echo "    make deploy-restart  Restart prod (picks up secret changes)"
	@echo "    make secret-set    Update a secret: make secret-set NAME=x VALUE=y"
	@echo "    make backup        Download blog.db from server"
	@echo ""
	@echo "  Prerequisites: copy .env.example → .env and fill in values"
	@echo ""

# ─── Local dev ────────────────────────────────────────────────────────────────

.PHONY: dev dev-logs dev-down

dev:
	docker compose up --build -d
	@echo "→ Dev server: http://localhost:8080"

dev-logs:
	docker compose logs -f

dev-down:
	docker compose down

# ─── Tests ────────────────────────────────────────────────────────────────────

.PHONY: test

test:
	cd backend && uv run pytest --cov --cov-report=term-missing

# ─── Production ───────────────────────────────────────────────────────────────

.PHONY: prod prod-logs prod-stop prod-down

prod: _require-env _gen-nginx-conf
	$(COMPOSE_PROD) up --build -d
	@echo "→ Production: https://$(DOMAIN)"

prod-logs:
	$(COMPOSE_PROD) logs -f

prod-stop:
	$(COMPOSE_PROD) stop

prod-down:
	$(COMPOSE_PROD) down

# ─── SSL certificates ─────────────────────────────────────────────────────────

.PHONY: cert-init cert-renew

cert-init: _require-env
	@echo "→ [1/3] Starting HTTP-only nginx for ACME challenge..."
	cp nginx/http-only.conf nginx/app.conf
	$(COMPOSE_PROD) up -d nginx certbot
	@echo "→ [2/3] Waiting for nginx to be ready..."
	@sleep 3
	@echo "→ [3/3] Requesting certificate for $(DOMAIN) and www.$(DOMAIN)..."
	$(COMPOSE_PROD) run --rm certbot certonly \
		--webroot \
		--webroot-path=/var/www/certbot \
		--email $(CERTBOT_EMAIL) \
		--agree-tos \
		--no-eff-email \
		-d $(DOMAIN) \
		-d www.$(DOMAIN)
	@echo "→ Certificate issued. Switching to HTTPS config..."
	$(MAKE) _gen-nginx-conf
	$(COMPOSE_PROD) exec nginx nginx -s reload
	@echo "✓ Certificate installed for $(DOMAIN). Run 'make prod' to start all services."

cert-renew: _require-env
	$(COMPOSE_PROD) run --rm certbot renew --quiet
	$(COMPOSE_PROD) exec nginx nginx -s reload
	@echo "✓ Certificate renewed."

# ─── Health check ─────────────────────────────────────────────────────────────

.PHONY: check

check: _require-env
	@echo "Checking $(DOMAIN)..."
	@curl -sf -o /dev/null https://$(DOMAIN)/ \
		&& echo "  ✓ HTTPS OK" \
		|| echo "  ✗ HTTPS failed"
	@curl -sf -o /dev/null -w "%{http_code}" http://$(DOMAIN)/ \
		| grep -q "301\|302" \
		&& echo "  ✓ HTTP→HTTPS redirect OK" \
		|| echo "  ✗ HTTP redirect failed"
	@curl -sf https://$(DOMAIN)/api/posts \
		| python3 -c "import sys,json; p=json.load(sys.stdin); print(f'  ✓ API OK ({len(p)} posts)')" \
		|| echo "  ✗ API failed"

# ─── Remote deployment (run locally) ──────────────────────────────────────────

.PHONY: deploy-first deploy deploy-restart secret-set backup

deploy-first: _require-env _require-secrets
	@echo "→ First-time setup on $(SERVER_USER)@$(SERVER_HOST)..."
	@echo "  This will: install Docker, clone repo, push secrets, obtain SSL cert, start app."
	@read -p "  Continue? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 1
	ssh-copy-id $(SERVER_USER)@$(SERVER_HOST) 2>/dev/null || true
	DEPLOY_DIR=$(DEPLOY_DIR) REPO_URL=$(REPO_URL) \
		$(SSH_CMD) "bash -s" < scripts/server-setup.sh
	@echo "→ Pushing secrets to server..."
	$(SSH_CMD) "mkdir -p $(DEPLOY_DIR)/secrets && chmod 700 $(DEPLOY_DIR)/secrets"
	@echo "$(ANTHROPIC_API_KEY)" | $(SSH_CMD) "cat > $(DEPLOY_DIR)/secrets/anthropic_api_key && chmod 600 $(DEPLOY_DIR)/secrets/anthropic_api_key"
	@echo "$(UNSPLASH_ACCESS_KEY)" | $(SSH_CMD) "cat > $(DEPLOY_DIR)/secrets/unsplash_access_key && chmod 600 $(DEPLOY_DIR)/secrets/unsplash_access_key"
	@echo "$(ADMIN_PASSWORD)" | $(SSH_CMD) "cat > $(DEPLOY_DIR)/secrets/admin_password && chmod 600 $(DEPLOY_DIR)/secrets/admin_password"
	@echo "$(SECRET_KEY)" | $(SSH_CMD) "cat > $(DEPLOY_DIR)/secrets/secret_key && chmod 600 $(DEPLOY_DIR)/secrets/secret_key"
	@echo "→ Pushing non-secret config (.env with DOMAIN + CERTBOT_EMAIL only)..."
	@printf "DOMAIN=$(DOMAIN)\nCERTBOT_EMAIL=$(CERTBOT_EMAIL)\n" | $(SSH_CMD) "cat > $(DEPLOY_DIR)/.env"
	$(SSH_CMD) \
		"cd $(DEPLOY_DIR) && make cert-init && make prod"
	@echo ""
	@echo "✓ Deployment complete. Site live at https://$(DOMAIN)"

deploy: _require-env
	@echo "→ Deploying to $(SERVER_USER)@$(SERVER_HOST):$(DEPLOY_DIR)..."
	$(SSH_CMD) \
		"cd $(DEPLOY_DIR) && git pull --ff-only && make prod"
	@echo "✓ Deploy complete: https://$(DOMAIN)"

deploy-restart: _require-env
	@echo "→ Restarting production on $(SERVER_USER)@$(SERVER_HOST)..."
	$(SSH_CMD) \
		"cd $(DEPLOY_DIR) && $(COMPOSE_PROD) restart web"
	@echo "✓ Restarted."

secret-set: _require-env
	@test -n "$(NAME)" || (echo "ERROR: NAME is required. Usage: make secret-set NAME=anthropic_api_key VALUE=sk-ant-..." && exit 1)
	@test -n "$(VALUE)" || (echo "ERROR: VALUE is required." && exit 1)
	@echo "→ Updating secret '$(NAME)' on server..."
	@echo "$(VALUE)" | $(SSH_CMD) "cat > $(DEPLOY_DIR)/secrets/$(NAME) && chmod 600 $(DEPLOY_DIR)/secrets/$(NAME)"
	$(SSH_CMD) "cd $(DEPLOY_DIR) && $(COMPOSE_PROD) restart web"
	@echo "✓ Secret '$(NAME)' updated and app restarted."

backup: _require-env
	@echo "→ Downloading blog.db from $(SERVER_HOST)..."
	$(SSH_CMD) "cd $(DEPLOY_DIR) && docker compose -f docker-compose.prod.yml exec -T web cat /data/blog.db" > blog.db.bak
	@echo "✓ Saved to blog.db.bak ($(shell wc -c < blog.db.bak 2>/dev/null || echo '?') bytes)"

# ─── Internal helpers ─────────────────────────────────────────────────────────

.PHONY: _require-env _require-secrets _gen-nginx-conf

_require-env:
	@test -f .env \
		|| (echo "ERROR: .env not found — copy .env.example → .env and fill in values." && exit 1)
	@test -n "$(DOMAIN)" \
		|| (echo "ERROR: DOMAIN is not set in .env" && exit 1)
	@test -n "$(CERTBOT_EMAIL)" \
		|| (echo "ERROR: CERTBOT_EMAIL is not set in .env" && exit 1)

_require-secrets:
	@test -n "$(ANTHROPIC_API_KEY)" \
		|| (echo "ERROR: ANTHROPIC_API_KEY is not set in .env" && exit 1)
	@test -n "$(ADMIN_PASSWORD)" \
		|| (echo "ERROR: ADMIN_PASSWORD is not set in .env" && exit 1)
	@test -n "$(SECRET_KEY)" \
		|| (echo "ERROR: SECRET_KEY is not set in .env" && exit 1)

_gen-nginx-conf:
	@DOMAIN=$(DOMAIN) envsubst '$$DOMAIN' < nginx/app.conf.template > nginx/app.conf
	@echo "→ nginx/app.conf generated for $(DOMAIN)"

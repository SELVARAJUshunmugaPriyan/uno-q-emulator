COMPOSE = docker compose
OBJECT_COMPOSE = $(COMPOSE) \
	-p uno-q-object \
	-f compose.yaml \
	-f compose.object.yaml \
	--profile object
KEYWORD_COMPOSE = $(COMPOSE) \
	-p uno-q-keyword \
	-f compose.yaml \
	-f compose.keyword.yaml \
	--profile keyword
OBJECT_MODEL ?= $(firstword $(wildcard models/object-detection/*.eim))
KEYWORD_MODEL ?= $(firstword $(wildcard models/keyword-detection/*.eim))

.PHONY: init doctor ssh runner runner-info \
		keyword-up keyword-down keyword-logs keyword-bridge-test \
		keyword-test-wav keyword-test-samples keyword-model-check keyword-runner \
		keyword-info \
		object-build object-up object-down object-restart object-logs \
		object-shell object-web-check object-import-check object-model-check \
		object-model-info object-runner 

init:
	@mkdir -p models
	@mkdir -p runtime/arduino-keyword runtime/arduino-object
	@mkdir -p models/keyword-detection models/object-detection
	@test -f .env || cp .env.example .env
	@set -- models/keyword-detection/*.eim models/object-detection/*.eim; \
	if [ "$$1" = 'models/keyword-detection/*.eim' ] && \
	   [ "$$2" = 'models/object-detection/*.eim' ]; then \
		echo "No exercise models found."; \
	else \
		echo "Exercise model directories checked."; \
	fi

doctor:
	@./scripts/doctor.sh

keyword-up: init
	@$(KEYWORD_COMPOSE) up --build -d mcu mpu
	@$(MAKE) keyword-runner

keyword-down:
	@$(KEYWORD_COMPOSE) down -v
	@echo "Keyword-detection services stopped."

keyword-logs:
	@$(KEYWORD_COMPOSE) logs -f

keyword-bridge-test:
	@curl -fsS -X POST http://127.0.0.1:9000/bridge/call \
		-H 'Content-Type: application/json' \
		-d '{"method":"keyword_detected","args":["hey_dragon"]}'
	@echo

keyword-test-wav:
	@test -n "$(WAV)" || (echo "Usage: make keyword-test-wav WAV=sample/file.wav" >&2; exit 2)
	@python3 scripts/test-wav.py "$(WAV)"

keyword-test-samples:
	@python3 scripts/test-wav.py sample/*.wav

keyword-model-check:
	@test -n "$(KEYWORD_MODEL)" || \
		(echo "No keyword model found in models/keyword-detection/." >&2; exit 1)
	@test -f "$(KEYWORD_MODEL)" || \
		(echo "Keyword model not found: $(KEYWORD_MODEL)" >&2; exit 1)
	@echo "Keyword model: $(KEYWORD_MODEL)"

keyword-runner: init keyword-model-check
	@COMPOSE_FILE=compose.yaml:compose.keyword.yaml \
		COMPOSE_PROJECT_NAME=uno-q-keyword \
		COMPOSE_PROFILES=keyword \
		RUNNER_SERVICE=runner \
		./scripts/run-model.sh "$(KEYWORD_MODEL)"

keyword-info:
	@curl -fsS http://127.0.0.1:1340/api/info
	@echo

object-model-check:
	@test -n "$(OBJECT_MODEL)" || \
		(echo "No object-detection model found in models/object-detection/." >&2; exit 1)
	@test -f "$(OBJECT_MODEL)" || \
		(echo "Object model not found: $(OBJECT_MODEL)" >&2; exit 1)
	@echo "Object model: $(OBJECT_MODEL)"

object-build: init object-model-check
	@$(OBJECT_COMPOSE) build mpu

object-up: init object-model-check
	@EIM_MODEL=/models/custom/object-detection/$(notdir $(OBJECT_MODEL)) \
		$(OBJECT_COMPOSE) up -d mpu runner

object-down:
	@$(OBJECT_COMPOSE) down -v

object-restart: object-down object-up

object-logs:
	@$(OBJECT_COMPOSE) logs -f mpu runner

object-shell:
	@$(OBJECT_COMPOSE) exec mpu bash

object-web-check:
	@curl -fsS 'http://127.0.0.1:7000/socket.io/?EIO=4&transport=polling' >/dev/null || \
		(echo "Object WebUI Socket.IO endpoint is not reachable on port 7000." >&2; exit 1)
	@echo "Object WebUI is reachable on port 7000."

object-import-check:
	@$(OBJECT_COMPOSE) run --rm --no-deps \
		--entrypoint python mpu -c \
		"from PIL import Image; \
		 from arduino.app_utils import App; \
		 from arduino.app_bricks.web_ui import WebUI; \
		 from arduino.app_bricks.object_detection import ObjectDetection; \
		 print('Object-detection imports succeeded.')"

object-model-info:
	@curl -fsS http://127.0.0.1:1340/api/info
	@echo

object-runner: init object-model-check
	@COMPOSE_FILE=compose.yaml:compose.object.yaml \
		COMPOSE_PROJECT_NAME=uno-q-object \
		COMPOSE_PROFILES=object \
		RUNNER_SERVICE=runner \
		./scripts/run-model.sh "$(OBJECT_MODEL)"

runner: init
	@./scripts/run-model.sh "$(MODEL)"

runner-info:
	@curl -fsS http://127.0.0.1:1340/api/info
	@echo

ssh:
	ssh -o StrictHostKeyChecking=no -p 2222 arduino@127.0.0.1

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
GESTURE_BUILD ?=
GESTURE_MODE ?= collection
GESTURE_MODEL ?= $(firstword $(wildcard models/gesture-recognition/*.eim))
GESTURE_COMPOSE = $(COMPOSE) \
	-p uno-q-gesture \
	-f compose.yaml \
	-f compose.gesture.yaml \
	--profile gesture

.PHONY: init doctor ssh runner runner-info \
		keyword-up keyword-down keyword-logs keyword-bridge-test \
		keyword-test-wav keyword-test-samples keyword-model-check keyword-runner \
		keyword-info keyword-health keyword-status \
		object-build object-up object-down object-restart object-logs \
		object-shell object-web-check object-import-check object-model-check \
		object-model-info object-runner \
		gesture-build gesture-up gesture-down gesture-logs gesture-health gesture-status \
		gesture-model-check gesture-model-info gesture-runner

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

keyword-up: init keyword-model-check
	@EIM_MODEL="/models/custom/keyword-detection/$(notdir $(KEYWORD_MODEL))" \
		$(KEYWORD_COMPOSE) up --build -d mcu runner mpu

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

keyword-health:
	@curl -fsS http://127.0.0.1:$${KEYWORD_PORT:-9200}/health
	@echo

keyword-status:
	@curl -fsS http://127.0.0.1:$${KEYWORD_PORT:-9200}/v1/status
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

gesture-build:
	@$(GESTURE_COMPOSE) build gesture

gesture-up: $(if $(filter detection,$(GESTURE_MODE)),gesture-model-check)
	@mkdir -p app/gesture-recognition/python/data
	@case "$(GESTURE_MODE)" in \
		collection) \
			GESTURE_MODE=collection $(GESTURE_COMPOSE) up $(GESTURE_BUILD) --no-deps -d gesture ;; \
		detection) \
			mkdir -p runtime/arduino-gesture/.arduino-bricks && \
			EIM_MODEL="/models/custom/gesture-recognition/$(notdir $(GESTURE_MODEL))" \
			GESTURE_MODE=detection $(GESTURE_COMPOSE) up $(GESTURE_BUILD) -d gesture runner ;; \
		*) echo "GESTURE_MODE must be collection or detection" >&2; exit 2 ;; \
	esac

gesture-model-check:
	@test -n "$(GESTURE_MODEL)" && test -f "$(GESTURE_MODEL)" || \
		(echo "Place a .eim model in models/gesture-recognition/ or set GESTURE_MODEL." >&2; exit 1)
	@case "$(GESTURE_MODEL)" in models/gesture-recognition/*.eim) ;; \
		*) echo "GESTURE_MODEL must be inside models/gesture-recognition/." >&2; exit 1 ;; esac
	@echo "Gesture model: $(GESTURE_MODEL)"

gesture-runner: gesture-model-check
	@mkdir -p runtime/arduino-gesture/.arduino-bricks
	@COMPOSE_FILE=compose.yaml:compose.gesture.yaml \
		COMPOSE_PROJECT_NAME=uno-q-gesture \
		COMPOSE_PROFILES=gesture \
		RUNNER_SERVICE=runner \
		./scripts/run-model.sh "$(GESTURE_MODEL)"

gesture-model-info:
	@curl -fsS http://127.0.0.1:1340/api/info
	@echo

gesture-down:
	@$(GESTURE_COMPOSE) down -v

gesture-logs:
	@$(GESTURE_COMPOSE) logs -f gesture runner

gesture-health:
	@curl -fsS http://127.0.0.1:$${GESTURE_PORT:-9100}/health
	@echo

gesture-status:
	@curl -fsS http://127.0.0.1:$${GESTURE_PORT:-9100}/v1/status
	@echo

RELEASE ?= 2026Q1

DIST_DIR ?= dist
RELEASE_INVENTORY ?= $(DIST_DIR)/release_sha256_inventory.json
RELEASE_ARCHIVE ?= $(DIST_DIR)/corporate_quarterly_2026Q1_clean.zip

.PHONY: fetch build run test all fetch-v2 build-v2 run-v2 stage2 fetch-v3 build-v3 run-v3 stage3 build-v3-1 stage4 build-v3-2 stage5 package-v3 doctor-release verify-release inventory-release package-release

fetch:
	PYTHONPATH=src python3 -m corporate_quarterly fetch --release $(RELEASE)

build:
	PYTHONPATH=src python3 -m corporate_quarterly build --release $(RELEASE) --offline

run: build

test:
	PYTHONPATH=src python3 -m pytest tests -q

all: fetch build test

fetch-v2:
	PYTHONPATH=src python3 -m corporate_quarterly fetch-stage2 --release $(RELEASE)

build-v2:
	PYTHONPATH=src python3 -m corporate_quarterly build-stage2 --release $(RELEASE) --offline

run-v2:
	PYTHONPATH=src python3 -m corporate_quarterly run-stage2 --release $(RELEASE)

stage2: fetch-v2 build-v2 test

fetch-v3:
	PYTHONPATH=src python3 -m corporate_quarterly fetch-stage3 --release $(RELEASE)

build-v3:
	PYTHONPATH=src python3 -m corporate_quarterly build-stage3 --release $(RELEASE) --offline

run-v3:
	PYTHONPATH=src python3 -m corporate_quarterly run-stage3 --release $(RELEASE)

stage3: fetch-v3 build-v3 test

build-v3-1:
	PYTHONPATH=src python3 -m corporate_quarterly build-stage4 --release $(RELEASE) --offline

stage4: build-v3-1 test

build-v3-2:
	PYTHONPATH=src python3 -m corporate_quarterly build-stage5 --release $(RELEASE) --offline

stage5: build-v3-2

package-v3:
	PYTHONPATH=src python3 -m corporate_quarterly.release_integrity package --output outputs/2026Q1_v3/corporate_quarterly_2026Q1_v3_clean.zip --overwrite

doctor-release:
	PYTHONPATH=src python3 -m corporate_quarterly.release_integrity doctor

verify-release:
	PYTHONPATH=src python3 -m corporate_quarterly.release_integrity verify

inventory-release: verify-release
	PYTHONPATH=src python3 -m corporate_quarterly.release_integrity inventory --output $(RELEASE_INVENTORY)

package-release: doctor-release verify-release
	PYTHONPATH=src python3 -m corporate_quarterly.release_integrity package --output $(RELEASE_ARCHIVE)

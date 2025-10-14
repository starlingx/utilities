SHELL := /bin/bash
TASK  := build
EXCLUDES := build test all

.PHONY: $(EXCLUDES)

BAOMON_NAME ?= baomon

all: $(TASK)

build:
	@if [ -d $* ]; then \
		go mod download; \
		go mod tidy; \
		go build -o $(BAOMON_NAME) .; \
	fi

clean:
	@echo "Clean all build artifacts"
	rm -f $(BAOMON_NAME)

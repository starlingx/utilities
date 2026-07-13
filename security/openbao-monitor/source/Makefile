SHELL := /bin/bash

BAOMON_NAME ?= baomon

.PHONY: all build clean test

all: build

build:
	go mod download
	go build -o $(BAOMON_NAME) .

clean:
	rm -f $(BAOMON_NAME)

test:
	go test ./...

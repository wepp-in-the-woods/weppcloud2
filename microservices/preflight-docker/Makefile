# Detect hostname and set default REDIS_URL
HOSTNAME := $(shell hostname)
ifeq ($(HOSTNAME),wepp1)
REDIS_URL = redis://172.17.0.1:6379
else
REDIS_URL = redis://wepp.cloud:6379
endif

export REDIS_URL

# Docker and SystemD Commands
.PHONY: build restart stop start up down docker-exec

build:
	docker-compose build

up:
	docker-compose up

down:
	docker-compose down

docker-exec:
	docker exec -it preflightdocker_w2_preflight_app_1 bash


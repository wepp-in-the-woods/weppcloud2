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

restart:
	systemctl restart w2-status-docker.service

stop:
	systemctl stop w2-status-docker.service

start:
	systemctl start w2-status-docker.service

up:
	docker-compose up

down:
	docker-compose down

docker-exec:
	docker exec -it statusdocker_w2_status_app_1 bash


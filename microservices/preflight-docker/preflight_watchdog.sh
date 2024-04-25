#!/bin/bash

# Define the name of your service and the Docker Compose project name
SERVICE="w2_preflight_app"
COMPOSE_PROJECT="preflightdocker"

# Check the health status of the container
HEALTH_STATUS=$(docker inspect --format='{{.State.Health.Status}}' "${COMPOSE_PROJECT}_${SERVICE}_1")

# If the health status is "unhealthy", restart the container
if [ "$HEALTH_STATUS" = "unhealthy" ]; then
    echo "Container ${SERVICE} is unhealthy. Attempting to restart..."
    docker restart "${COMPOSE_PROJECT}_${SERVICE}_1"
fi



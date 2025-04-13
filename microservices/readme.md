## Readme 

The *w2-preflight-docker.service* connects to redis and passes
project status changes to the web client. This is used to
populate the checkboxes on the top left navigation bar

The *w2-status-docker.service* connects to redis and passes
build log standard output to the web client. This is used to
populate status feedback when building soils, climates, wepp. 


### Install docker.io

```
sudo apt install docker.io
```

### Install docker-compose

```
sudo apt install docker-compose
```

### Installation

Instructions are for Preflight/Status is the same


#### Build preflight

```
cd microservices/preflight-docker
sudo docker-compose build
```


#### Test with docker-compose

```
sudo docker-compose up
```

##### To stop

```
sudo docker-compose down
```


#### Daemonize service

```
sudo cp w2-preflight-docker.service /etc/systemd/system
sudo systemctl enable w2-preflight-docker.service
```


**Specify REDIS_URL in the Service section**

*wepp1*
```
Environment="REDIS_URL=redis://172.17.0.1:6379"
```

*Not wepp1*
```
Environment="REDIS_URL=redis://wepp.cloud:6379"
```

#### Start Service

```
sudo systemctl start w2-preflight-docker.service
```

#### crontab for watchdog

```
sudo crontab -e
```

```
* * * * * /workdir/weppcloud2/microservices/preflight-docker/preflight_watchdog.sh >> /var/log/preflight_watchdog.log 2>&1
```


### Makefile Usage Documentation

This Makefile automates the process of building, starting, stopping, and managing Docker containers and systemd services for the `w2-status` application. Below is a guide on how to use each command defined in the Makefile.

## Requirements
- Docker and Docker Compose must be installed on the host machine.
- Systemd must be installed and the `w2-status-docker.service` must be properly configured on the host system.
- Ensure you have the necessary permissions to execute Docker and systemd commands.

## Commands

- **Build**
  - **Purpose**: Builds the Docker containers as defined in the `docker-compose.yml`.
  - **Command**: `make build`
  - **Example**:
    ```bash
    make build
    ```

- **Up**
  - **Purpose**: Starts all containers using Docker Compose.
  - **Command**: `make up`
  - **Example**:
    ```bash
    make up
    ```

- **Down**
  - **Purpose**: Stops all containers and removes containers, networks, volumes, and images created by `up`.
  - **Command**: `make down`
  - **Example**:
    ```bash
    make down
    ```

- **Docker-Exec**
  - **Purpose**: Opens a bash shell inside the `w2_status_app_1` container.
  - **Command**: `make docker-exec`
  - **Example**:
    ```bash
    make docker-exec
    ```

## Configuration
- The Makefile automatically sets the `REDIS_URL` environment variable based on the hostname of the machine where it is run. `wepp1` will use a different Redis URL than other hosts.

Ensure that you review and understand each part of the Makefile and the Docker configurations to tailor the setup to your specific needs.
"""


### Troubleshooting


#### Connection to redis-server

If docker-compose container cannot connect to redis server may need to configure firewall

Set ufw rule

```
sudo ufw allow from 172.16.0.0/12 to any port 6379
sudo ufw reload
```

#### Testing firewall

```
nc -zv 172.17.0.1 6379                                 
```

should yield a response

RUN apt-get update && apt-get install -y curl \
    && rm -rf /var/lib/apt/lists/*

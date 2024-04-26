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

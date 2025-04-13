# redis 

### About

`redis` is a in memory key-value store database

### weppcloud uses

#### Event Tracking

##### `wepppy.nodb.RedisPrep` is a client class. 

https://github.com/rogerlew/wepppy/blob/master/wepppy/nodb/redis_prep.py

- `RedisPrep` serializes the event information to `wd/redisprep.dump`
  - Serialization is one-way, state is never deserialized from the dumps
- Events are recorded to `db=0`
- has `.timestamp(key: str)` method to log events. e.g. climate building complete
- `Preflight` microservice subcribes to key events to db=0, queries key, value records 
  for the runid and passes the object to the client


###### Example redis.dump
```json
{
  "attrs:loaded": "true", 
  "attrs:has_sbs": "false",
  "timestamps:landuse_map": "1712535018",
  "timestamps:build_channels": "1712028840",
  "timestamps:set_outlet": "1712515206",
  "timestamps:abstract_watershed": "1712515226",
  "timestamps:build_landuse": "1712535023",
  "timestamps:build_soils": "1712535083",
  "timestamps:build_climate": "1712515667",
  "timestamps:run_wepp": "1714168234"
}
```

##### Preflight Microservice

https://github.com/wepp-in-the-woods/weppcloud2/tree/main/microservices/preflight-docker

`Preflight` is a `docker-compose` application. The preflight server is a Python tornado/aioredis
application. `docker-compose` uses `haproxy` to run multiple instances and load balance.


#### Long running status proxying

##### `wepppy.nodb.StatusMessenger`

https://github.com/rogerlew/wepppy/blob/wepppy/nodb/status_messenger.py

`StatusMessenger` is a factory method Python class that lazy loads redis and provides a
`.publish(channel, message)` method to write messages to `db=2`

Daemonized using systemd as w2-preflight-docker

##### Status Microservice

https://github.com/wepp-in-the-woods/weppcloud2/tree/main/microservices/preflight-docker

`Status` is a `docker-compose` application. The status server is a Python tornado/aioredis
application. `docker-compose` uses `haproxy` to run multiple instances and load balance.
Status proxies messages to websocket clients subscribe to a channel.

Daemonized using systemd as w2-status-docker


## Dev Notes

### Commands and installation

`redis-server` is installed on `wepp1:6379` and daemonized with systemd as `redis.service`

`ufw` is configured to allow connections from `wepp2`

no sensitive information e.g. PII, pw hashes, or persistent data is pushed to redis. This
allows redis to be restarted at anytime with minimal disruption of service

`redis-cli` is shell client for redis

`redis-cli INFO` yields status information for `redis-server`



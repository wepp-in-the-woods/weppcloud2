import redis
import json

# Connect to Redis
r = redis.Redis(host='localhost', port=6379, db=0)
p = r.pubsub(ignore_subscribe_messages=True)

# Subscribe to all events on DB 0
p.psubscribe('__keyspace@0__:*')

# Listen for messages
while True:
    message = p.get_message()
    if message:
      
        # Check if the message is a keyspace notification
        if message['type'] == 'pmessage':
            # Extract the key name from the channel name
            run_id = message['channel'].split(b':')[-1].decode('utf-8')
            # Use hgetall to get all key-value pairs from the hash
            key_value_pairs = r.hgetall(run_id)
            # Decode the bytes to string for easier use (if applicable)
            key_value_pairs_decoded = {
                k.decode('utf-8'): v.decode('utf-8') for k, v in key_value_pairs.items()}
            print(f"run_id: {run_id}, preflight_hashmap: {key_value_pairs_decoded}")


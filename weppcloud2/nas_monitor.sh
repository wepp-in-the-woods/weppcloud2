#!/bin/bash
echo "Monitoring /geodata read/write speeds (MB/s)..."

while true; do
    # Previous stats
    prev_stats=$(cat /proc/self/mountstats | grep -A 10 " /geodata " | grep "bytes")
    prev_read=$(echo "$prev_stats" | awk '{print $2}')  # Field 2: total read bytes
    prev_write=$(echo "$prev_stats" | awk '{print $3}')  # Field 3: total write bytes
    
    # Sanity check
    if [ -z "$prev_read" ] || [ -z "$prev_write" ]; then
        echo "$(date '+%H:%M:%S') - Error: Could not read byte stats"
        sleep 1
        continue
    fi
    
    sleep 1
    
    # Current stats
    curr_stats=$(cat /proc/self/mountstats | grep -A 10 " /geodata " | grep "bytes")
    curr_read=$(echo "$curr_stats" | awk '{print $2}')  # Field 2
    curr_write=$(echo "$curr_stats" | awk '{print $3}')  # Field 3
    
    # Sanity check
    if [ -z "$curr_read" ] || [ -z "$curr_write" ]; then
        echo "$(date '+%H:%M:%S') - Error: Could not read byte stats"
        sleep 1
        continue
    fi
    
    # Calculate differences
    read_diff=$((curr_read - prev_read))
    write_diff=$((curr_write - prev_write))
    
    # Speeds in MB/s with fallback
    read_speed=$(echo "scale=2; if ($read_diff < 0) 0 else $read_diff / 1048576" | bc 2>/dev/null || echo "0.00")
    write_speed=$(echo "scale=2; if ($write_diff < 0) 0 else $write_diff / 1048576" | bc 2>/dev/null || echo "0.00")
    
    echo "$(date '+%H:%M:%S') - Read: $read_speed MB/s, Write: $write_speed MB/s"

    sleep 2
done

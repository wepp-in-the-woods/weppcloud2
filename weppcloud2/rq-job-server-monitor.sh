# console dashboard for rq job-server
# requires expect `sudo apt install expect`
while true; do
  tput cup 0 0
  unbuffer rq info --url redis://129.101.202.237:6379/9
  sleep 5
done

#!/bin/zsh
# Public link for judges: Streamlit app + Cloudflare quick tunnel, detached from any terminal or Claude session.
#
#   scripts/public_link.sh start     # prints the https://<random>.trycloudflare.com link (also in run/url.txt)
#   scripts/public_link.sh status    # is it up? health check through the public link
#   scripts/public_link.sh stop
#
# The link changes at every start: start once, put it on the slide / QR code, don't restart.
# While the tunnel runs, `caffeinate` keeps the Mac awake (lid open, plugged in).
cd "${0:A:h}/.." || exit 1
RUN=run; PORT=${PORT:-8511}; PY=./.venv/bin/python
mkdir -p $RUN

detach() {  # own session/process group: survives the terminal or Claude session that started it
  nohup $PY -c 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' "$@" > "$OUT" 2>&1 &
  echo $!
}

case "$1" in
  start)
    if [[ -f $RUN/tunnel.pid ]] && kill -0 $(cat $RUN/tunnel.pid) 2>/dev/null; then
      echo "Already running: $(cat $RUN/url.txt 2>/dev/null)"; exit 0
    fi
    OUT=$RUN/streamlit.log detach $PY -m streamlit run app.py --server.port $PORT --server.headless true > $RUN/streamlit.pid
    OUT=$RUN/tunnel.log detach cloudflared tunnel --url http://localhost:$PORT --no-autoupdate > $RUN/tunnel.pid
    OUT=/dev/null detach caffeinate -dimsu -w $(cat $RUN/tunnel.pid) > $RUN/caffeinate.pid
    for i in {1..60}; do
      URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' $RUN/tunnel.log | head -1); [[ -n $URL ]] && break; sleep 1
    done
    [[ -z $URL ]] && { echo "No tunnel URL after 60 s: see $RUN/tunnel.log"; exit 1; }
    echo $URL > $RUN/url.txt
    for i in {1..60}; do curl -s -o /dev/null -w "%{http_code}" "$URL/_stcore/health" | grep -q 200 && break; sleep 2; done
    echo "Public link: $URL"
    ;;
  status)
    for n in streamlit tunnel caffeinate; do
      p=$(cat $RUN/$n.pid 2>/dev/null); kill -0 $p 2>/dev/null && echo "$n: running (pid $p)" || echo "$n: STOPPED"
    done
    URL=$(cat $RUN/url.txt 2>/dev/null)
    echo "link: $URL · health: $(curl -s -o /dev/null -w '%{http_code}' "$URL/_stcore/health" 2>/dev/null)"
    ;;
  stop)
    for n in caffeinate tunnel streamlit; do p=$(cat $RUN/$n.pid 2>/dev/null); [[ -n $p ]] && kill $p 2>/dev/null; rm -f $RUN/$n.pid; done
    echo "Stopped."
    ;;
  *) echo "usage: $0 start|status|stop"; exit 1 ;;
esac

export PATH="/root/.local/bin:$PATH"
alias ll='ls -la'
# Setup status written by render_config.py at every start (what is configured, and what is missing).
if [ -z "${PI_BANNER_SHOWN:-}" ] && [ -t 1 ]; then
  export PI_BANNER_SHOWN=1
  [ -f /root/.pi-agent-motd ] && cat /root/.pi-agent-motd
fi

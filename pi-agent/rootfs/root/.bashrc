export PATH="/root/.local/bin:$PATH"
alias ll='ls -la'
if [ -z "${PI_BANNER_SHOWN:-}" ] && [ -t 1 ]; then
  export PI_BANNER_SHOWN=1
  echo "Pi Agent for Home Assistant - type 'pi' to start. Config: \$PI_CODING_AGENT_DIR=$PI_CODING_AGENT_DIR"
fi

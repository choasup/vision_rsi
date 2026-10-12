#!/bin/sh
# POSIX source launcher. Preserve the caller directory for explicit paths.
set -eu
agent_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -n "${VISION_RSI_PYTHON:-}" ]; then
    agent_python=$VISION_RSI_PYTHON
elif [ -x "$agent_dir/.venv/bin/python" ]; then
    agent_python="$agent_dir/.venv/bin/python"
else
    agent_python=python3
fi
exec "$agent_python" -X utf8 "$agent_dir/launch_agent.py" --cli "$@"

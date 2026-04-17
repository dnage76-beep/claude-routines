#!/bin/bash
# attach.sh - attach your terminal to the running Sheldon tmux session.

echo "Attaching to sheldon-tg. Detach with Ctrl-b then d."
exec tmux attach -t sheldon-tg

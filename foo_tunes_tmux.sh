#!/usr/local/bin/bash

PATH=/usr/local/bin

if ! tmux has-session -t footunes 2>/dev/null; then
    # https://stackoverflow.com/questions/25207909/tmux-open-terminal-failed-not-a-terminal
    tmux new-session -d -s footunes python /bebe/script/foo_tunes/foo_tunes.py \
         --jojo \
         --watch_sleep_time=30 \
         --watch_playlist_delay=25 \
         --watch_convert_delay=180 # Three minutes.
fi

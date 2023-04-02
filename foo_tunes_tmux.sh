#!/usr/local/bin/bash

PATH=/usr/local/go/bin:/usr/local/opt/python/libexec/bin:/usr/local/bin:/usr/local/sbin:/opt/local/bin:/opt/local/sbin:/sbin:/usr/sbin:/sbin:/bin:/usr/sbin:/usr/bin:/usr/local/sbin:/usr/local/bin

if ! tmux has-session -t footunes 2>/dev/null; then
    # https://stackoverflow.com/questions/25207909/tmux-open-terminal-failed-not-a-terminal
    tmux new-session -d -s footunes python /bebe/script/foo_tunes/foo_tunes.py \
         --jojo \
         --watch_sleep_time=30 \
         --watch_playlist_delay=25 \
         --watch_convert_delay=180 # Three minutes.
fi

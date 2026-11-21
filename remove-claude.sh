#!/bin/sh
sed -E \
  -e '/^[Cc]o-[Aa]uthored-[Bb]y: Claude Sonnet 5\.5 <noreply@anthropic\.com>[[:space:]]*$/d' \
  -e '/^Claude-Session:[[:space:]]/d' \
  "$1"

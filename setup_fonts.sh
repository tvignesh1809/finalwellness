#!/usr/bin/env bash
# Run this once, locally, inside the ig-wellness-bot/ folder.
# It pulls the two Roboto weights bot.py needs, straight from
# Google's official open-source fonts repo (Apache-licensed).
set -e

curl -L -o Roboto-Bold.ttf "https://github.com/google/fonts/raw/main/apache/roboto/Roboto-Bold.ttf"
curl -L -o Roboto-Regular.ttf "https://github.com/google/fonts/raw/main/apache/roboto/Roboto-Regular.ttf"

echo "Downloaded Roboto-Bold.ttf and Roboto-Regular.ttf into $(pwd)"

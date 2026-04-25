#!/bin/bash
set -e

echo "📡 Fetching data & generating dashboard.html ..."
python3 generate.py

echo "📦 Committing ..."
git add dashboard.html
git commit -m "Update dashboard $(date '+%Y-%m-%d %H:%M')"

echo "🚀 Pushing to GitHub ..."
git push

echo "✅ Done. Pages will update in ~1 min."

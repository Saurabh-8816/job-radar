#!/usr/bin/env bash
# Run state (data/jobs.db + site/index.html) lives on the `state` branch as ONE commit
# that each run replaces, so git history doesn't grow by the whole database every run.
#
#   tools/state.sh load            # before a run: latest state -> working tree
#   tools/state.sh save "message"  # after a run: working tree -> state branch (force)
#
# radar and digest never overlap (workflow concurrency group), and the laptop relay only
# reads, so a force-push can't lose another writer's update.
set -euo pipefail
cd "$(dirname "$0")/.."

case "${1:-}" in
  load)
    if git fetch -q origin state 2>/dev/null; then
      mkdir -p data site
      if git cat-file -e FETCH_HEAD:jobs.db.gz 2>/dev/null; then
        git show FETCH_HEAD:jobs.db.gz | gunzip > data/jobs.db
      else   # state saved before compression
        git show FETCH_HEAD:jobs.db > data/jobs.db
      fi
      git show FETCH_HEAD:index.html > site/index.html 2>/dev/null || true
      echo "state loaded: $(git log -1 --format=%s FETCH_HEAD)"
    else
      echo "no state branch yet: starting from the data/jobs.db in this checkout (if any)"
    fi
    ;;
  save)
    # gzip: GitHub refuses files over 100 MB, and the database compresses about 5x.
    db=$(gzip -c -6 data/jobs.db | git hash-object -w --stdin)
    entries=$(printf '100644 blob %s\tjobs.db.gz' "$db")
    if [ -f site/index.html ]; then
      entries=$(printf '%s\n100644 blob %s\tindex.html' "$entries" "$(git hash-object -w site/index.html)")
    fi
    tree=$(printf '%s\n' "$entries" | git mktree)
    commit=$(git commit-tree "$tree" -m "${2:-state}")   # no parent: history is not kept
    git push -q -f origin "$commit:refs/heads/state"
    echo "state saved: ${2:-state}"
    ;;
  *)
    echo "usage: tools/state.sh load | save \"message\"" >&2
    exit 2
    ;;
esac

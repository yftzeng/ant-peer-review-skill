# Repo checks, sourced by scripts/precommit.sh.
one pytest python3 -m pytest -q -p no:cacheprovider
one compile python3 -m compileall -q src
MIN_TESTS=3

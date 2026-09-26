#!/usr/bin/env bash
# Run the ETL:  bash scripts/etl.sh run|list [options]
# See etl/README.md. In Docker use:  docker compose run --rm etl run
set -euo pipefail
cd "$(dirname "$0")/.."

# As root in the container, Python would leave root-owned __pycache__ folders in the bind-mounted project.
export PYTHONDONTWRITEBYTECODE=1

# In Docker this runs as root, so hand raw/ and staging/ back to whoever owns the project folder
# when we finish, even if a step fails.
fix_owner() { chown -R "$(stat -c '%u:%g' .)" raw staging 2>/dev/null || true; }
trap fix_owner EXIT

python -m etl "$@"

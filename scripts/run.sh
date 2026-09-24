#!/usr/bin/env bash
# Run the whole pipeline: execute the notebook against PostgreSQL/PostGIS,
# then compare the results with the original ones.
#
# Credentials can come from DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME, or from
# CREDENTIALS_FILE (default: Credentials.json) when DB_PASSWORD is unset.
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p output

# The notebook imports scripts/build_story.py. As root in the container, Python would leave a root-owned
# scripts/__pycache__ in the bind-mounted project, so don't write bytecode.
export PYTHONDONTWRITEBYTECODE=1

# In Docker this script runs as root, so on a Linux host (including WSL) the files it writes
# into the bind-mounted project would be owned by root. Hand output/ back to whoever owns
# the project folder when we finish, even if a step fails.
fix_owner() { chown -R "$(stat -c '%u:%g' .)" output 2>/dev/null || true; }
trap fix_owner EXIT

echo "== 1/3 Waiting for the database"
python scripts/wait_for_db.py

echo "== 2/3 Executing bustling_score.ipynb"
# The notebook was saved with a kernel name that only exists on the author's machine
# ("conda-base-py"), so force the standard python3 kernel.
jupyter nbconvert --to notebook --execute bustling_score.ipynb \
    --output-dir output --output bustling_score.executed.ipynb \
    --ExecutePreprocessor.kernel_name=python3 \
    --ExecutePreprocessor.timeout=-1

echo "== 3/3 Checking results"
python scripts/check_results.py

echo
echo "Done. Open output/index.html in a browser to see the story (map, charts and table)."

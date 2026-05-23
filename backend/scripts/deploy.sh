#!/bin/bash
# deploy.sh — deploy zhidang backend changes to production container
#
# Usage: bash scripts/deploy.sh [--server HOST] [--container NAME]
#   Defaults: server=47.98.102.197, container=zhidang-backend-1
#
# Steps:
#   1. SCP changed files to server
#   2. docker cp into container
#   3. restart container
#   4. wait for startup
#   5. run verify_deploy.py (failure prints warning, does NOT abort)

set -euo pipefail

SERVER="${1:-47.98.102.197}"
CONTAINER="${2:-zhidang-backend-1}"
SSH_KEY="${SSH_KEY:-/opt/data/home/.ssh/id_rsa_sync}"
REMOTE_TMP="/tmp/zhidang_deploy_$$"
LOCAL_ROOT="/mnt/d/智档/backend"

# Files to deploy (relative to LOCAL_ROOT)
FILES=(
    "app/main.py"
    "app/services/power_map_service.py"
    "app/schemas/__init__.py"
    "tests/e2e_chat_v2_client.py"
    "tests/check_geometry.py"
    "scripts/verify_deploy.py"
)

echo "🚀 Deploying to ${SERVER}:${CONTAINER}"
echo "   Files: ${FILES[*]}"
echo ""

# Step 1: SCP
echo "📤 SCP to ${SERVER}:${REMOTE_TMP}..."
ssh -i "${SSH_KEY}" "root@${SERVER}" "mkdir -p ${REMOTE_TMP}"
for f in "${FILES[@]}"; do
    scp -i "${SSH_KEY}" "${LOCAL_ROOT}/${f}" "root@${SERVER}:${REMOTE_TMP}/"
done
echo "   ✅ Done"

# Step 2: docker cp
echo "📥 docker cp into ${CONTAINER}..."
for f in "${FILES[@]}"; do
    basename_f=$(basename "$f")
    remote_path="${REMOTE_TMP}/${basename_f}"
    container_path="/app/backend/${f}"
    ssh -i "${SSH_KEY}" "root@${SERVER}" \
        "docker cp '${remote_path}' '${CONTAINER}:${container_path}'"
done
echo "   ✅ Done"

# Step 3: restart
echo "🔄 Restarting ${CONTAINER}..."
ssh -i "${SSH_KEY}" "root@${SERVER}" "docker restart ${CONTAINER}"
echo "   ✅ Restart initiated"

# Step 4: wait for startup
echo "⏳ Waiting for startup..."
sleep 6
for i in {1..10}; do
    if ssh -i "${SSH_KEY}" "root@${SERVER}" \
        "docker logs ${CONTAINER} --tail 3 2>&1 | grep -q 'Uvicorn running'"; then
        echo "   ✅ Container ready"
        break
    fi
    sleep 2
done

# Step 5: verify
echo ""
echo "🔍 Running verify_deploy.py..."
if ssh -i "${SSH_KEY}" "root@${SERVER}" \
    "docker exec -w /app/backend ${CONTAINER} python3 scripts/verify_deploy.py --skip-modules --server http://localhost:8000"; then
    echo "   ✅ Verification passed"
else
    echo "   ⚠️  Verification FAILED — review output above, deploy may be incomplete"
    echo "   (non-fatal: deployment continued)"
fi

echo ""
echo "🏁 Deploy complete."

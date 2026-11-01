#!/usr/bin/env bash
# Start CloakBrowser-Manager on 0.0.0.0:8080 with AUTH_TOKEN from a private registry artifact.
set -eu
# CNB_TOKEN is available to PID 1 and is never copied into the workspace or Git.
: "${CNB_TOKEN:?CNB_TOKEN required}"
REPO_REGISTRY="docker.cnb.cool/$(printf '%s' "${CNB_REPO_SLUG:?CNB_REPO_SLUG required}" | tr '[:upper:]' '[:lower:]')"
SECRET_IMAGE="${MANAGER_SECRET_IMAGE:-$REPO_REGISTRY/manager-secret:latest}"
SECRET_DIR=/tmp/manager-secret
rm -rf "$SECRET_DIR"; mkdir -p "$SECRET_DIR"
printf '%s\n' "$CNB_TOKEN" | crane auth login docker.cnb.cool -u cnb --password-stdin >/dev/null 2>&1
crane export "$SECRET_IMAGE" "$SECRET_DIR/secret.tar.gz" >/dev/null 2>&1 || { echo 'manager secret artifact unavailable' >&2; exit 1; }
tar -xf "$SECRET_DIR/secret.tar.gz" -C "$SECRET_DIR" || { echo 'manager secret artifact invalid' >&2; exit 1; }
set -a
. "$SECRET_DIR/manager.env" 2>/dev/null || { echo 'manager.env missing from secret artifact' >&2; exit 1; }
set +a
: "${AUTH_TOKEN:?AUTH_TOKEN missing from secret artifact}"
mkdir -p /data/profiles /tmp/mgr
pkill -f 'uvicorn backend.main:app' 2>/dev/null || true
cd /app
AUTH_TOKEN="$AUTH_TOKEN" REMOTE_ENVIRONMENT_ENABLED="${REMOTE_ENVIRONMENT_ENABLED:-true}" PROFILE_STORAGE="${PROFILE_STORAGE:-registry}" PROFILE_REGISTRY="${PROFILE_REGISTRY:-$REPO_REGISTRY}" PROFILE_IDLE_STOP_SECONDS="${PROFILE_IDLE_STOP_SECONDS:-300}" CLOAKBROWSER_CACHE_DIR=/opt/cloakbrowser-cache TZ="${TZ:-Asia/Shanghai}" \
  setsid nohup /opt/manager-venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8080 --log-level info \
  >/tmp/mgr/manager.log 2>&1 < /dev/null &
for i in $(seq 1 30); do curl -sf http://127.0.0.1:8080/api/health >/dev/null && break; sleep 1; done
curl -s http://127.0.0.1:8080/api/health; echo

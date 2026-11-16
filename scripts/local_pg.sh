#!/usr/bin/env bash
# Local Postgres without docker. Usage: scripts/local_pg.sh start|stop|status|reset|url
# Port 54329, db/user/password: pnd. Data lives in $PND_PG_DIR (default /tmp/pnd-pg).
# Works as root (sandbox/CI: runs postgres as OS user "pndpg") and as a normal user (macOS brew).
# macOS tip: `brew install postgresql@16`, or just use `docker compose up -d` instead.
set -euo pipefail

PORT="${PND_PG_PORT:-54329}"
DIR="${PND_PG_DIR:-/tmp/pnd-pg}"
DATA="$DIR/data"
RUN_USER="pndpg"
URL="postgresql://pnd:pnd@localhost:${PORT}/pnd"

find_bin() {
  [ -n "${PG_BIN:-}" ] && { echo "$PG_BIN"; return; }
  for d in /usr/lib/postgresql/*/bin /opt/homebrew/opt/postgresql@*/bin /usr/local/opt/postgresql@*/bin; do
    [ -x "$d/initdb" ] && last="$d"
  done
  if [ -n "${last:-}" ]; then echo "$last"; return; fi
  command -v initdb >/dev/null && { dirname "$(command -v initdb)"; return; }
  echo "ERROR: Postgres binaries not found (set PG_BIN or brew install postgresql@16)" >&2; exit 1
}
BIN="$(find_bin)"

# run a command as the unprivileged owner of the cluster
as_pg() {
  if [ "$(id -u)" -eq 0 ]; then
    id "$RUN_USER" >/dev/null 2>&1 || useradd --system --home-dir "$DIR" --shell /bin/bash "$RUN_USER"
    mkdir -p "$DIR"; chown "$RUN_USER" "$DIR"
    su "$RUN_USER" -s /bin/bash -c "$*"
  else
    mkdir -p "$DIR"; bash -c "$*"
  fi
}

is_up() { "$BIN/pg_isready" -q -h localhost -p "$PORT"; }

start() {
  if is_up; then echo "already running: $URL"; return; fi
  if [ ! -s "$DATA/PG_VERSION" ]; then
    as_pg "'$BIN/initdb' -D '$DATA' -U postgres -A trust -E UTF8 --locale=C.UTF-8 >'$DIR/initdb.log' 2>&1" \
      || { cat "$DIR/initdb.log"; exit 1; }
  fi
  as_pg "'$BIN/pg_ctl' -D '$DATA' -l '$DIR/pg.log' -o \"-p $PORT -k '$DIR' -c listen_addresses=localhost -c fsync=off\" -w start" >/dev/null
  psql_admin "SELECT 1 FROM pg_roles WHERE rolname='pnd'" | grep -q 1 \
    || psql_admin "CREATE ROLE pnd LOGIN PASSWORD 'pnd' SUPERUSER" >/dev/null
  psql_admin "SELECT 1 FROM pg_database WHERE datname='pnd'" | grep -q 1 \
    || psql_admin "CREATE DATABASE pnd OWNER pnd" >/dev/null
  echo "started: $URL"
}

psql_admin() { "$BIN/psql" -h "$DIR" -p "$PORT" -U postgres -At -c "$1"; }

stop() {
  if [ -s "$DATA/postmaster.pid" ]; then
    as_pg "'$BIN/pg_ctl' -D '$DATA' -m fast -w stop" >/dev/null && echo "stopped"
  else echo "not running"; fi
}

case "${1:-}" in
  start)  start ;;
  stop)   stop ;;
  status) if is_up; then echo "up: $URL"; else echo "down"; exit 1; fi ;;
  reset)  stop || true; rm -rf "$DATA"; start; echo "fresh database created" ;;
  url)    echo "$URL" ;;
  *) echo "usage: $0 start|stop|status|reset|url" >&2; exit 2 ;;
esac

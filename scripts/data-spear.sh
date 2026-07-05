#!/usr/bin/env bash
# data-spear.sh — bash CLI for the Data-Spear Python agent.
#
# Drives the FastAPI server (data_spear/api/main.py) over HTTP:
#   serve            start the API server (uvicorn)
#   connect          validate Postgres credentials and set the active database
#   ask "prompt"     one-shot question (streams the agent trace)
#   chat             interactive REPL (connect + ask in a loop)
#   ingest           index configured SOURCES into Pinecone
#   health           check the API is up
#
# Environment:
#   DATA_SPEAR_API        API base URL          (default http://localhost:8000)
#   DATA_SPEAR_API_TOKEN  bearer token, if the server sets API_TOKEN
set -euo pipefail

API="${DATA_SPEAR_API:-http://localhost:8000}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# ── ui helpers ───────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  ACCENT=$'\033[36m'; DIM=$'\033[90m'; BOLD=$'\033[1m'
  GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; MAGENTA=$'\033[35m'
  RESET=$'\033[0m'
else
  ACCENT=""; DIM=""; BOLD=""; GREEN=""; YELLOW=""; RED=""; MAGENTA=""; RESET=""
fi

die() { echo "${RED}✗ $*${RESET}" >&2; exit 1; }
note() { echo "${DIM}◆ $*${RESET}"; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}
need curl
need jq

auth_args() {
  if [[ -n "${DATA_SPEAR_API_TOKEN:-}" ]]; then
    printf -- '-H\nAuthorization: Bearer %s\n' "$DATA_SPEAR_API_TOKEN"
  fi
}

# POST a JSON body; prints the response body, returns non-zero on HTTP error.
api_post() { # $1=path $2=json-body $3=max-time
  local path="$1" body="$2" max_time="${3:-120}"
  local args=()
  while IFS= read -r line; do args+=("$line"); done < <(auth_args)
  local out http
  out=$(curl -sS -w '\n%{http_code}' --max-time "$max_time" \
    -H 'Content-Type: application/json' ${args[@]+"${args[@]}"} \
    -d "$body" "$API$path") || return 1
  http="${out##*$'\n'}"
  body="${out%$'\n'*}"
  if [[ "$http" != 2* ]]; then
    echo "$(echo "$body" | jq -r '.detail? // .' 2>/dev/null || echo "$body")" >&2
    return 1
  fi
  echo "$body"
}

# ── serve ────────────────────────────────────────────────────────────────────
cmd_serve() {
  local venv="$REPO_ROOT/.venv"
  local uvicorn="uvicorn"
  [[ -x "$venv/bin/uvicorn" ]] && uvicorn="$venv/bin/uvicorn"
  exec "$uvicorn" data_spear.api.main:app --port "${1:-8000}" --app-dir "$REPO_ROOT"
}

# ── health ───────────────────────────────────────────────────────────────────
cmd_health() {
  if curl -sS --max-time 5 "$API/healthz" | jq -e '.status == "ok"' >/dev/null 2>&1; then
    echo "${GREEN}● API up at $API${RESET}"
  else
    die "API not reachable at $API — start it with: $0 serve"
  fi
}

# ── connect ──────────────────────────────────────────────────────────────────
cmd_connect() {
  local dsn="" host="localhost" port="5432" dbname="postgres" user="postgres"
  local password="" sslmode="" interactive=1

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dsn)      dsn="$2"; shift 2; interactive=0 ;;
      --host)     host="$2"; shift 2; interactive=0 ;;
      --port)     port="$2"; shift 2; interactive=0 ;;
      --dbname)   dbname="$2"; shift 2; interactive=0 ;;
      --user)     user="$2"; shift 2; interactive=0 ;;
      --password) password="$2"; shift 2; interactive=0 ;;
      --sslmode)  sslmode="$2"; shift 2; interactive=0 ;;
      *) die "unknown connect option: $1" ;;
    esac
  done

  if [[ $interactive -eq 1 && -t 0 ]]; then
    echo "${ACCENT}${BOLD}connect to postgresql${RESET}"
    echo "${DIM}Press Enter to accept defaults. Paste a connection URL to skip the fields.${RESET}"
    read -r -p "  Connection URL []: " dsn
    if [[ -z "$dsn" ]]; then
      read -r -p "  Host [localhost]: " host; host="${host:-localhost}"
      read -r -p "  Port [5432]: " port; port="${port:-5432}"
      read -r -p "  Database [postgres]: " dbname; dbname="${dbname:-postgres}"
      read -r -p "  User [postgres]: " user; user="${user:-postgres}"
      read -r -s -p "  Password []: " password; echo
      read -r -p "  SSL mode []: " sslmode
    fi
  fi

  local body
  body=$(jq -n \
    --arg dsn "$dsn" --arg host "$host" --arg port "$port" \
    --arg dbname "$dbname" --arg user "$user" --arg password "$password" \
    --arg sslmode "$sslmode" \
    '{host: $host, port: ($port | tonumber), dbname: $dbname,
      user: $user, password: $password}
     + (if $dsn != "" then {dsn: $dsn} else {} end)
     + (if $sslmode != "" then {sslmode: $sslmode} else {} end)')

  local resp
  resp=$(api_post /connect "$body" 30) || die "could not connect"
  echo "${GREEN}✓ connected to $(echo "$resp" | jq -r '"\(.database) · \(.server)"')${RESET}"
}

# ── ask (streaming) ──────────────────────────────────────────────────────────
# Streams /query/stream and renders each SSE event as a live agent trace.
run_prompt() { # $1=prompt $2=allow_destructive(true|false)
  local prompt="$1" destructive="${2:-false}"
  local body
  body=$(jq -n --arg p "$prompt" --argjson d "$destructive" \
    '{prompt: $p, allow_destructive: $d}')

  local args=()
  while IFS= read -r line; do args+=("$line"); done < <(auth_args)

  local got_final=1
  while IFS= read -r line; do
    [[ "$line" == data:* ]] || continue
    local evt="${line#data: }"
    local type
    type=$(echo "$evt" | jq -r '.type // empty') || continue
    case "$type" in
      retrieval)
        echo "${DIM}  ◈ retrieved $(echo "$evt" | jq -r '.count') context chunks${RESET}" ;;
      thinking)
        echo "${MAGENTA}  ✻ $(echo "$evt" | jq -r '.text' | head -c 200)${RESET}" ;;
      tool_use)
        echo "${YELLOW}  ⚒ $(echo "$evt" | jq -r '"\(.name) \(.detail // "")"')${RESET}" ;;
      tool_result)
        if [[ "$(echo "$evt" | jq -r '.ok')" == "true" ]]; then
          echo "${GREEN}  ✓ $(echo "$evt" | jq -r '"\(.name) → \(.detail // "")"')${RESET}"
        else
          echo "${RED}  ✗ $(echo "$evt" | jq -r '"\(.name) → \(.detail // "")"')${RESET}"
        fi ;;
      final)
        got_final=0
        echo
        echo "$evt" | jq -r '.answer'
        local refs
        refs=$(echo "$evt" | jq -r '[.hits[]? | "[\(.id)] \(.score * 100 | round / 100)"] | join(" · ")')
        [[ -n "$refs" ]] && echo "${DIM}  └ sources $refs${RESET}" ;;
      error)
        echo "${RED}⚠ $(echo "$evt" | jq -r '.message')${RESET}" >&2
        return 1 ;;
    esac
  done < <(curl -sSN --max-time 600 -H 'Content-Type: application/json' \
             ${args[@]+"${args[@]}"} -d "$body" "$API/query/stream")
  return $got_final
}

cmd_ask() {
  local destructive=false
  if [[ "${1:-}" == "--destructive" || "${1:-}" == "-d" ]]; then
    destructive=true; shift
  fi
  local prompt="${*:-}"
  [[ -n "$prompt" ]] || die "usage: $0 ask [--destructive] \"your question\""
  # `!` prefix also authorizes Tier 2 SQL, same as the chat REPL.
  if [[ "$prompt" == '!'* ]]; then
    destructive=true
    prompt="${prompt#!}"; prompt="${prompt# }"
  fi
  run_prompt "$prompt" "$destructive"
}

# ── ingest ───────────────────────────────────────────────────────────────────
cmd_ingest() {
  note "ingesting configured SOURCES…"
  local resp
  resp=$(api_post /ingest '{}' 600) || die "ingest failed"
  echo "${GREEN}✓ ingested: $(echo "$resp" | jq -r 'to_entries | map("\(.key) → \(.value) records") | join(", ")')${RESET}"
}

# ── chat REPL ────────────────────────────────────────────────────────────────
cmd_chat() {
  cmd_health
  cmd_connect "$@"
  echo
  echo "${ACCENT}✦ ${BOLD}Data-Spear${RESET}${DIM}  agentic sql — /help for commands, Ctrl+D to quit${RESET}"
  echo

  local line
  while true; do
    IFS= read -e -r -p "${ACCENT}› ${RESET}" line || { echo; break; }
    line="$(echo "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    [[ -z "$line" ]] && continue
    history -s "$line"

    case "$line" in
      /help)
        note "commands: /help · /ingest · /connect · /quit"
        note "prefix a prompt with ! to authorize destructive SQL (DROP/ALTER/unbounded writes)"
        ;;
      /ingest)  cmd_ingest || true ;;
      /connect) cmd_connect || true ;;
      /quit | /exit) break ;;
      /*) note "unknown command: $line — try /help" ;;
      '!'*)
        local rest="${line#!}"; rest="${rest# }"
        [[ -n "$rest" ]] && { run_prompt "$rest" true || true; echo; }
        ;;
      *) run_prompt "$line" false || true; echo ;;
    esac
  done
}

# ── dispatch ─────────────────────────────────────────────────────────────────
usage() {
  cat <<EOF
usage: $0 <command> [args]

commands:
  serve [port]                       start the API server (default port 8000)
  connect [--dsn URL | --host ...]   set the active database (interactive if no flags)
  ask [--destructive] "prompt"       one-shot question; ! prefix also allows Tier 2 SQL
  chat [connect flags]               interactive REPL
  ingest                             index configured SOURCES into Pinecone
  health                             check the API is reachable

environment:
  DATA_SPEAR_API        API base URL (default http://localhost:8000)
  DATA_SPEAR_API_TOKEN  bearer token, if the server requires one
EOF
}

cmd="${1:-}"; shift || true
case "$cmd" in
  serve)   cmd_serve "$@" ;;
  connect) cmd_connect "$@" ;;
  ask)     cmd_ask "$@" ;;
  chat)    cmd_chat "$@" ;;
  ingest)  cmd_ingest ;;
  health)  cmd_health ;;
  '' | -h | --help | help) usage ;;
  *) usage; die "unknown command: $cmd" ;;
esac

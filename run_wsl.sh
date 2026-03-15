#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv-wsl"
PYTHON_BIN="${PYTHON_BIN:-python3}"

print_usage() {
  cat <<'EOF'
Usage:
  ./run_wsl.sh setup
  ./run_wsl.sh test
  ./run_wsl.sh run [network]
  ./run_wsl.sh help

Commands:
  setup           Create .venv-wsl and install requirements
  test            Run pytest in the WSL virtualenv
  run             Run all parsers
  run kb          Run only KB parser
  run monetka     Run only Monetka parser
  run maria_ra    Run only Maria-Ra parser

Environment overrides:
  PYTHON_BIN      Python executable to use, default: python3
EOF
}

ensure_python() {
  if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    echo "Python executable not found: ${PYTHON_BIN}" >&2
    echo "Install Python in WSL first, for example:" >&2
    echo "  sudo apt update && sudo apt install -y python3 python3-venv python3-pip" >&2
    exit 1
  fi
}

ensure_venv() {
  ensure_python
  if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    echo "Creating WSL virtualenv at ${VENV_DIR}"
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  fi
}

run_in_venv() {
  ensure_venv
  (
    cd "${PROJECT_DIR}"
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"
    "$@"
  )
}

setup_env() {
  ensure_venv
  run_in_venv python -m pip install --upgrade pip
  run_in_venv python -m pip install -r requirements.txt
  echo "WSL environment is ready: ${VENV_DIR}"
}

run_tests() {
  run_in_venv python -m pytest -q
}

run_parsers() {
  local network="${1:-}"
  if [[ -n "${network}" ]]; then
    case "${network}" in
      kb|monetka|maria_ra)
        run_in_venv python main.py run --network "${network}"
        ;;
      *)
        echo "Unsupported network: ${network}" >&2
        print_usage
        exit 1
        ;;
    esac
  else
    run_in_venv python main.py run
  fi
}

main() {
  local command="${1:-help}"
  case "${command}" in
    setup)
      setup_env
      ;;
    test)
      run_tests
      ;;
    run)
      run_parsers "${2:-}"
      ;;
    help|-h|--help)
      print_usage
      ;;
    *)
      echo "Unknown command: ${command}" >&2
      print_usage
      exit 1
      ;;
  esac
}

main "$@"

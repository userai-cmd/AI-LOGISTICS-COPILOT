#!/usr/bin/env bash
# Завантажує змінні з локального .env у поточний сервіс Railway (через CLI).
#
# Одноразово на машині:
#   brew install railway
#   railway login
# У корені репозиторію:
#   railway link     # обери Project + Service (FastAPI-сервіс, не Postgres)
#
# DATABASE_URL краще підключити в UI як Reference із сервісу Postgres — скрипт за
# замовчуванням НЕ надсилає DATABASE_URL із файлу (див. нижче).
#
# Використання:
#   ./scripts/push-env-to-railway.sh              # бере ./.env
#   ./scripts/push-env-to-railway.sh path/to/env
#
# Переглянути без запису в Railway:
#   DRY_RUN=1 ./scripts/push-env-to-railway.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-"${ROOT}/.env"}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "❌ Файл не знайдено: ${ENV_FILE}"
  echo "   Скопіюй .env.example → .env і заповни значення."
  exit 1
fi

if ! command -v railway >/dev/null 2>&1; then
  echo "❌ Railway CLI не знайдено. Встановлення (обери один спосіб):"
  echo "   • bash <(curl -fsSL railway.com/install.sh)"
  echo "   • або: npm i -g @railway/cli"
  echo "   • або (як є Homebrew): brew install railway"
  echo "   Документація: https://docs.railway.com/develop/cli"
  exit 1
fi

DRY_RUN="${DRY_RUN:-0}"
# Якщо 1 — дозволити пуш DATABASE_URL із .env (наприклад копіпаст із Railway Postgres)
PUSH_DATABASE_URL="${PUSH_DATABASE_URL:-0}"

skip_var() {
  local k="$1"
  case "$k" in
    HOST | PORT | "") return 0 ;;
  esac
  return 1
}

echo "📄 Джерело: ${ENV_FILE}"
if [[ "${PUSH_DATABASE_URL}" != "1" ]]; then
  echo "ℹ️  DATABASE_URL з файлу пропускається. Додай у Railway Variables → Reference → Postgres → DATABASE_URL"
  echo "   Або PUSH_DATABASE_URL=1 ./scripts/push-env-to-railway.sh  (не коміть .env із прод-секретами)"
fi

while IFS= read -r raw || [[ -n "${raw}" ]]; do
  # trim whitespace
  line="${raw#"${raw%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"

  [[ -z "${line}" ]] && continue
  [[ "${line}" =~ ^# ]] && continue
  [[ "${line}" =~ ^export[[:space:]]+ ]] && line="${line#export }"

  if [[ ! "${line}" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
    echo "⚠️  Пропускаю некоректний рядок: ${line}"
    continue
  fi

  key="${BASH_REMATCH[1]}"
  val="${BASH_REMATCH[2]}"

  # Прибрати лапки навколо value
  if [[ "${val}" =~ ^\'.*\'$ ]]; then
    val="${val:1:-1}"
  elif [[ "${val}" =~ ^\".*\"$ ]]; then
    val="${val:1:-1}"
  fi

  if skip_var "${key}"; then
    echo "⏭️  Пропуск: ${key} (не потрібно для Railway / задається платформою)"
    continue
  fi

  if [[ "${key}" == "DATABASE_URL" && "${PUSH_DATABASE_URL}" != "1" ]]; then
    echo "⏭️  Пропуск: DATABASE_URL"
    continue
  fi

  if [[ -z "${val}" ]]; then
    echo "⏭️  Пропуск (пусте значення): ${key}"
    continue
  fi

  if [[ "${DRY_RUN}" == "1" ]]; then
    echo "DRY RUN: railway variable set ${key}=*****"
    continue
  fi

  # Один ключ за раз — менше проблем із спецсимволами у values
  if ! railway variable set "${key}=${val}" --skip-deploys; then
    echo "❌ Не вдалося записати змінну: ${key}"
    echo "   Перевір: railway link, доступ до сервісу, синтаксис CLI (railway variable set --help)."
    exit 1
  fi
  echo "✓ ${key}"

done < "${ENV_FILE}"

if [[ "${DRY_RUN}" == "1" ]]; then
  echo ""
  echo "Це був DRY RUN. Прибери DRY_RUN=1 для реального запису в Railway."
  exit 0
fi

echo ""
echo "Готово. Railway зазвичай перезбере/задеплоїть сервіс (або запусти redeploy уручну)."
echo "Перевір GET /health на публічному домені після деплою."

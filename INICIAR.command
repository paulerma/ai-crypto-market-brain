#!/bin/zsh
cd "$(dirname "$0")"

echo "============================================="
echo "   AI Crypto Market Brain PRO 3.7 TODAS LAS TEMPORALIDADES"
echo "============================================="

find_python() {
  for candidate in \
    /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/3.10/bin/python3; do
    if [ -x "$candidate" ]; then
      echo "$candidate"
      return 0
    fi
  done
  command -v python3
}

PY=$(find_python)
if [ -z "$PY" ]; then
  echo "No se encontró Python 3.10 o superior."
  echo "Instala Python desde python.org y vuelve a abrir este archivo."
  read "?Presiona Enter para cerrar..."
  exit 1
fi

VER=$($PY -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
MAJOR=${VER%%.*}
MINOR=${VER##*.}
if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 10 ]; }; then
  echo "Python encontrado: $VER. Se requiere Python 3.10+."
  read "?Presiona Enter para cerrar..."
  exit 1
fi

echo "Python: $VER"

if [ ! -d .venv ]; then
  echo "Primera apertura: preparando el entorno (solo una vez)..."
  "$PY" -m venv .venv || exit 1
fi

source .venv/bin/activate

REQ_HASH=$(shasum -a 256 requirements.txt | awk '{print $1}')
OLD_HASH=""
if [ -f .venv/.requirements.sha256 ]; then
  OLD_HASH=$(cat .venv/.requirements.sha256)
fi
if [ "$REQ_HASH" != "$OLD_HASH" ]; then
  echo "Comprobando dependencias..."
  python -m pip install -r requirements.txt || {
    echo "No se pudieron instalar las dependencias. Revisa tu conexión a internet."
    read "?Presiona Enter para cerrar..."
    exit 1
  }
  echo "$REQ_HASH" > .venv/.requirements.sha256
fi

python run_dashboard.py
status=$?
if [ $status -ne 0 ]; then
  echo ""
  echo "La aplicación terminó con error. Toma una foto de estas últimas líneas."
  read "?Presiona Enter para cerrar..."
fi

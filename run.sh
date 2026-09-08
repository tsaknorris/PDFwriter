#!/usr/bin/env bash
# ==============================================================================
# PDFwriter - Acrobat-tason Offline PDF-Editori (Linux / NixOS)
# Käynnistysskripti: Lataa Nix flake/direnv-ympäristön ja käynnistää sovelluksen
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIUDIU_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Eristyskriitikko: Pakotetaan 100 % offline-tila
export QT_NO_NETWORK="1"

# Varmistetaan näyttömuuttuja (X11 / Wayland)
if [ -z "$DISPLAY" ] && [ -z "$WAYLAND_DISPLAY" ]; then
    export DISPLAY=":0"
fi

# Ladataan Nix flake- ja kirjastoprofiili (XCB, Wayland, Fontconfig, zstd, jne.)
# Siirrytään tilapäisesti emohakemistoon, jotta flake-profiilin .venv-aktivaatio ei kaadu
FLAKE_RC=$(ls -1 "$DIUDIU_DIR/.direnv"/flake-profile-*.rc 2>/dev/null | head -n 1 || true)
if [ -n "$FLAKE_RC" ] && [ -f "$FLAKE_RC" ]; then
    ORIG_DIR="$PWD"
    cd "$DIUDIU_DIR"
    set +e
    source "$FLAKE_RC" 2>/dev/null || true
    cd "$ORIG_DIR"
fi

# Valitaan Python-tulkki (.venv tai flake)
PYTHON_BIN="$DIUDIU_DIR/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

echo " Käynnistetään PDFwriter (100 % Offline, NixOS flake -ympäristö)..."
exec "$PYTHON_BIN" "$SCRIPT_DIR/app.py" "$@"

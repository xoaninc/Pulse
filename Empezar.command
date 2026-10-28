#!/bin/bash
# Doble clic en el Finder: instala (si hace falta), analiza la fototeca y abre la galería.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then ./instalar.sh || { read -p "Pulsa Intro para cerrar"; exit 1; }; fi
./arte todo
read -p "Pulsa Intro para cerrar"

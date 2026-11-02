#!/usr/bin/env bash
# Arranca la app con JDK 21. Maven de Homebrew trae su propio JDK (más nuevo),
# y JavaFX 21 necesita el módulo jdk.jsobject, que los JDK 24+ ya no incluyen.
# Uso:  bash ejecutar.sh        (desde apps/JavaDesktop_app)
set -e
cd "$(dirname "$0")"
if [ -z "${JAVA_HOME:-}" ] && command -v brew > /dev/null && [ -d "$(brew --prefix)/opt/openjdk@21" ]; then
  export JAVA_HOME="$(brew --prefix)/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
fi
exec mvn -q -B javafx:run

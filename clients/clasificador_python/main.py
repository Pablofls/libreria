"""
Punto de entrada para la interfaz gráfica (GUI).

Crea el CloudClassifier y se lo pasa a AppWindow,
garantizando que GUI y CLI compartan la misma lógica de clasificación.
"""

import sys
from classifier.cloud_classifier import CloudClassifier

try:
    from gui.app_window import AppWindow
except ImportError as exc:
    sys.exit(
        f"Error al cargar la GUI: {exc}\n"
        "Instala las dependencias con: pip install -r requirements.txt"
    )


def main() -> None:
    classifier = CloudClassifier()
    app = AppWindow(classifier)
    app.mainloop()


if __name__ == "__main__":
    main()

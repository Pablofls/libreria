"""
Punto de entrada para la interfaz de línea de comandos (CLI).

Reutiliza exactamente el mismo CloudClassifier que la GUI;
no duplica ninguna regla ni lógica NLP.

Uso:
    python classifier.py --text "descripción del servicio"
    python classifier.py --text "función serverless" --verbose
    python classifier.py --text "..." --name "Ana" --lastname "García"
    python classifier.py --help
"""

import argparse
import sys
from classifier.cloud_classifier import CloudClassifier
from classifier.exceptions import ClassificationException
from classifier.models import CloudModel
from classifier.result import ClassificationResult

# ── Colores ANSI ───────────────────────────────────────────────────────────────
R  = "\033[0m"   # reset
B  = "\033[1m"   # bold
BLUE   = "\033[34m"
GREEN  = "\033[32m"
PURPLE = "\033[35m"
ORANGE = "\033[38;5;208m"
GRAY   = "\033[90m"
RED    = "\033[31m"
CYAN   = "\033[36m"

MODEL_COLORS = {
    CloudModel.IAAS:    BLUE,
    CloudModel.PAAS:    GREEN,
    CloudModel.SAAS:    PURPLE,
    CloudModel.FAAS:    ORANGE,
    CloudModel.UNKNOWN: GRAY,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="classifier",
        description="Cloud Models Classifier — IaaS · PaaS · SaaS · FaaS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
ejemplos:
  python classifier.py --text "máquinas virtuales almacenamiento redes"
  python classifier.py --text "función serverless AWS Lambda" --verbose
  python classifier.py --text "Zoom correo suscripción" --name Ana --lastname García
        """,
    )
    parser.add_argument(
        "--text", "-t",
        required=True,
        metavar="\"DESCRIPCION\"",
        help="Texto que describe el servicio Cloud a clasificar.",
    )
    parser.add_argument(
        "--name", "-n",
        default="",
        metavar="NOMBRE",
        help="Nombre del usuario (opcional, solo para la presentación del resultado).",
    )
    parser.add_argument(
        "--lastname", "-l",
        default="",
        metavar="APELLIDO",
        help="Apellido del usuario (opcional).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Muestra el detalle de cada etapa del pipeline NLP.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Desactiva los colores ANSI en la salida.",
    )
    return parser


def print_result(result: ClassificationResult, name: str, lastname: str,
                 verbose: bool, use_color: bool) -> None:
    """Imprime el resultado en la terminal con formato claro."""

    def c(code: str, text: str) -> str:
        return f"{code}{text}{R}" if use_color else text

    model = result.model
    color = MODEL_COLORS.get(model, GRAY)

    # Línea principal (formato requerido por el enunciado)
    print()
    if name or lastname:
        print(c(B, f"{name} {lastname}".strip() + " — "), end="")
    print(c(B, "Modelo identificado: ") + c(color, model.label))
    print(c(GRAY, model.description))
    print()

    # Barras de puntaje
    print(c(B, "Puntajes:"))
    max_s = result.max_score
    _print_bar("IaaS", result.scores[CloudModel.IAAS], max_s, BLUE,   use_color)
    _print_bar("PaaS", result.scores[CloudModel.PAAS], max_s, GREEN,  use_color)
    _print_bar("SaaS", result.scores[CloudModel.SAAS], max_s, PURPLE, use_color)
    _print_bar("FaaS", result.scores[CloudModel.FAAS], max_s, ORANGE, use_color)

    # Detalle NLP con --verbose
    if verbose:
        _print_nlp(result, use_color)

    print()


def _print_bar(name: str, score: int, max_s: int,
               color: str, use_color: bool) -> None:
    TOTAL = 24
    filled = round(score * TOTAL / max_s) if max_s else 0
    bar_filled = "█" * filled
    bar_empty  = "░" * (TOTAL - filled)

    def c(code: str, text: str) -> str:
        return f"{code}{text}{R}" if use_color else text

    bar = c(color, bar_filled) + c(GRAY, bar_empty)
    print(f"  {c(color, f'{name:<4}')} {bar} {B}{score:>2}{R}")


def _print_nlp(result: ClassificationResult, use_color: bool) -> None:
    def c(code: str, text: str) -> str:
        return f"{code}{text}{R}" if use_color else text

    p = result.processed_text
    print()
    print(c(B, "Pipeline NLP:"))
    print(f"  {c(CYAN, '1. Texto limpio  ')}: {p.cleaned}")
    print(f"  {c(CYAN, '2. Tokens        ')}: {', '.join(p.tokens)}")
    print(f"  {c(CYAN, '3. Sin stopwords ')}: {', '.join(p.filtered)}")
    print(f"  {c(CYAN, '4. Stems (match) ')}: {' · '.join(p.stemmed)}")


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()
    use_color = not args.no_color and sys.stdout.isatty()

    classifier = CloudClassifier()

    try:
        result = classifier.classify(args.text)
        print_result(result, args.name, args.lastname,
                     verbose=args.verbose, use_color=use_color)
        sys.exit(0)

    except ClassificationException as exc:
        msg = f"Error de validación: {exc}"
        print(f"\033[31m{msg}\033[0m" if use_color else msg, file=sys.stderr)
        sys.exit(1)

    except Exception as exc:
        msg = f"Error inesperado: {exc}"
        print(f"\033[31m{msg}\033[0m" if use_color else msg, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()

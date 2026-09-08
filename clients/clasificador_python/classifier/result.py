from dataclasses import dataclass
from typing import Dict
from classifier.models import CloudModel
from classifier.nlp.preprocessor import ProcessedText


@dataclass(frozen=True)
class ClassificationResult:
    """
    Resultado completo de una clasificación.

    Incluye el modelo ganador, el mapa de puntajes de los cuatro modelos
    y el detalle de cada etapa del pipeline NLP, para que tanto la GUI
    como la CLI puedan mostrar información transparente sobre la decisión.
    """
    model: CloudModel
    scores: Dict[CloudModel, int]
    processed_text: ProcessedText

    @property
    def max_score(self) -> int:
        """Puntaje máximo entre los cuatro modelos (útil para escalar barras)."""
        return max(self.scores.values(), default=1) or 1

"""
Clasificador de servicios Cloud.

No contiene ningún elemento de presentación (GUI ni CLI).
Expone un único método público: classify(text) → ClassificationResult.

Estrategia de puntuación:
    Cada modelo tiene un conjunto de palabras clave procesadas una sola vez
    al construir el clasificador. Los tokens stemmed del texto del usuario
    se comparan contra ese conjunto. Las frases multi-palabra se buscan como
    substring en el texto limpio (valen 2 puntos por especificidad).
    Gana el modelo con mayor puntaje; en empate: FaaS > SaaS > PaaS > IaaS.
"""

import re
from typing import Dict, Set
from classifier.models import CloudModel
from classifier.exceptions import ClassificationException
from classifier.result import ClassificationResult
from classifier.nlp.preprocessor import TextPreprocessor

MIN_TEXT_LENGTH = 5
MAX_TEXT_LENGTH = 2000

# Orden de prioridad en caso de empate (índice más bajo = mayor prioridad)
TIEBREAK_ORDER = [CloudModel.FAAS, CloudModel.SAAS, CloudModel.PAAS, CloudModel.IAAS]


class CloudClassifier:
    """
    Clasifica texto libre como uno de los modelos Cloud: IaaS, PaaS, SaaS, FaaS.

    Uso:
        clf = CloudClassifier()
        result = clf.classify("función serverless en AWS Lambda")
        print(result.model.label)  # FaaS
    """

    def __init__(self) -> None:
        self._preprocessor = TextPreprocessor()

        # Construir los conjuntos de referencia una sola vez al inicializar.
        # Ambas formas (stemmed + sin stemming) se añaden para cubrir variantes
        # inflexionales sin necesidad de múltiples pasadas del stemmer.
        self._iaas_kw = self._build_keyword_set(
            "infraestructura", "maquina virtual", "servidor", "almacenamiento",
            "red virtual", "red privada", "disco duro", "cpu virtual", "vcpu",
            "hipervisor", "instancias", "balanceador de carga", "load balancer",
            "ip publica", "firewall", "bare metal", "aprovisionamiento",
            "backup", "snapshot", "datacenter", "centro de datos",
            "escalado de infraestructura", "ec2", "azure vm", "compute engine",
            "vpc", "recursos de computo", "virtualizacion", "almacenamiento en bloque",
            "red definida por software",
        )
        self._paas_kw = self._build_keyword_set(
            "plataforma", "entorno de desarrollo", "runtime", "framework",
            "despliegue", "deploy", "base de datos gestionada", "managed database",
            "middleware", "pipeline", "ci cd", "heroku", "google app engine",
            "azure app service", "elastic beanstalk", "openshift",
            "kubernetes gestionado", "contenedor gestionado", "orquestacion",
            "api gateway", "backend como servicio", "devops",
            "integracion continua", "entrega continua", "repositorio gestionado",
            "paas", "aplicacion web", "contenedor", "motor de aplicaciones",
            "plataforma de desarrollo", "entorno gestionado",
        )
        self._saas_kw = self._build_keyword_set(
            "software como servicio", "aplicacion en la nube", "suscripcion",
            "correo electronico", "email", "crm", "erp", "colaboracion",
            "google workspace", "office 365", "microsoft 365", "salesforce",
            "dropbox", "slack", "zoom", "teams", "trello", "notion",
            "aplicacion lista para usar", "usuario final", "sin instalacion",
            "acceso desde navegador", "saas", "gestion empresarial",
            "facturacion en linea", "videoconferencia", "almacenamiento de archivos",
            "herramienta de productividad", "pago por suscripcion",
        )
        self._faas_kw = self._build_keyword_set(
            "funcion", "serverless", "sin servidor", "lambda", "aws lambda",
            "azure functions", "google cloud functions", "event driven",
            "orientado a eventos", "trigger", "disparador",
            "ejecucion bajo demanda", "pago por ejecucion", "faas",
            "funcion asincrona", "webhook", "cold start",
            "sin gestionar servidores", "funcion en la nube", "microservicio",
            "arquitectura dirigida por eventos", "ejecucion por invocacion",
            "funcion activada", "ejecucion efimera",
        )

    # ── API pública ────────────────────────────────────────────────────────────

    def classify(self, raw_text: str) -> ClassificationResult:
        """
        Valida el texto y ejecuta el pipeline NLP completo.

        Args:
            raw_text: Texto introducido por el usuario (sin preprocesar).

        Returns:
            ClassificationResult con modelo ganador, puntajes y etapas NLP.

        Raises:
            ClassificationException: Si el texto no cumple los requisitos mínimos.
        """
        self._validate(raw_text)

        processed  = self._preprocessor.process(raw_text)
        token_set  = set(processed.stemmed)
        clean_text = processed.cleaned

        scores: Dict[CloudModel, int] = {
            CloudModel.IAAS: self._score_iaas(token_set, clean_text),
            CloudModel.PAAS: self._score_paas(token_set, clean_text),
            CloudModel.SAAS: self._score_saas(token_set, clean_text),
            CloudModel.FAAS: self._score_faas(token_set, clean_text),
        }

        winner = self._resolve_winner(scores)
        return ClassificationResult(model=winner, scores=scores,
                                    processed_text=processed)

    # ── Validación ─────────────────────────────────────────────────────────────

    def _validate(self, text: str) -> None:
        """
        Verifica que el texto sea clasificable.
        Lanza ClassificationException con mensaje descriptivo si no cumple.
        """
        if not text or not text.strip():
            raise ClassificationException("La descripción no puede estar vacía.")

        stripped = text.strip()

        if len(stripped) < MIN_TEXT_LENGTH:
            raise ClassificationException(
                f"El texto es demasiado corto. Escribe al menos {MIN_TEXT_LENGTH} caracteres."
            )
        if len(stripped) > MAX_TEXT_LENGTH:
            raise ClassificationException(
                f"El texto supera el límite de {MAX_TEXT_LENGTH} caracteres."
            )
        # Debe contener al menos una letra Unicode
        if not re.search(r"\p{L}" if False else r"[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ]", stripped):
            raise ClassificationException(
                "La descripción debe contener texto legible, no solo números o símbolos."
            )

    # ── Métodos de puntuación por modelo ──────────────────────────────────────
    # Cada método delega a _score_model() con su propio conjunto de keywords.
    # Están separados para mantener la intención clara y facilitar extensión.

    def _score_iaas(self, token_set: Set[str], clean_text: str) -> int:
        return self._score_model(token_set, clean_text, self._iaas_kw)

    def _score_paas(self, token_set: Set[str], clean_text: str) -> int:
        return self._score_model(token_set, clean_text, self._paas_kw)

    def _score_saas(self, token_set: Set[str], clean_text: str) -> int:
        return self._score_model(token_set, clean_text, self._saas_kw)

    def _score_faas(self, token_set: Set[str], clean_text: str) -> int:
        return self._score_model(token_set, clean_text, self._faas_kw)

    # ── Lógica de scoring ──────────────────────────────────────────────────────

    def _score_model(self, token_set: Set[str], clean_text: str,
                     keywords: Set[str]) -> int:
        """
        Cuenta coincidencias entre los tokens stemmed del usuario y el
        conjunto de referencia del modelo.

        Palabras simples: buscadas en token_set (O(1)).
        Frases multi-palabra: buscadas como substring en clean_text (valen 2).
        """
        score = 0
        for kw in keywords:
            if " " in kw:
                if kw in clean_text:
                    score += 2      # bonus por identificar un concepto compuesto
            else:
                if kw in token_set:
                    score += 1
        return score

    def _build_keyword_set(self, *raw_keywords: str) -> Set[str]:
        """
        Procesa los keywords de referencia por el mismo pipeline de limpieza
        y stemming que el texto del usuario, garantizando coherencia en el matching.

        Para cada keyword se guardan:
          - La frase limpia completa (para substring matching de frases).
          - Cada token en forma limpia (sin stemming).
          - Cada token en forma stemmed.
        """
        result: Set[str] = set()
        for raw in raw_keywords:
            cleaned = self._preprocessor.clean(raw)
            if " " in cleaned:
                result.add(cleaned)                          # frase completa
            for token in self._preprocessor.tokenize(cleaned):
                result.add(token)                            # forma limpia
                result.add(self._preprocessor.stem_word(token))  # forma stemmed
        return result

    def _resolve_winner(self, scores: Dict[CloudModel, int]) -> CloudModel:
        """
        Devuelve el modelo con mayor puntaje.
        En empate aplica la prioridad: FaaS > SaaS > PaaS > IaaS.
        Si todos son cero, devuelve UNKNOWN.
        """
        max_score = max(scores.values(), default=0)
        if max_score == 0:
            return CloudModel.UNKNOWN

        for model in TIEBREAK_ORDER:
            if scores.get(model, 0) == max_score:
                return model

        return CloudModel.UNKNOWN

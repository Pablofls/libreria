"""
Pipeline de NLP para preparar el texto antes de la clasificación.

Etapas:
    1. clean()            → minúsculas, normalización de acentos, limpieza
    2. tokenize()         → división en tokens por espacio
    3. remove_stopwords() → eliminación de palabras vacías
    4. stem_all()         → reducción morfológica (stemming)

El resultado de cada etapa queda en ProcessedText para que
la GUI y la CLI puedan mostrar el proceso completo.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List


# ── Stopwords ──────────────────────────────────────────────────────────────────
# Palabras de alta frecuencia que no aportan significado para clasificar
# servicios Cloud. Se incluyen las más comunes del español e inglés técnico.
STOPWORDS: frozenset = frozenset({
    # Artículos y determinantes (ES)
    "el", "la", "los", "las", "un", "una", "unos", "unas", "al", "del",
    # Preposiciones (ES)
    "de", "en", "a", "para", "con", "sin", "sobre", "por", "ante", "bajo",
    "desde", "hasta", "hacia", "entre", "segun", "durante", "mediante", "tras",
    # Conjunciones (ES)
    "y", "o", "u", "e", "ni", "pero", "sino", "aunque", "porque", "que",
    "como", "cuando", "donde", "si",
    # Pronombres (ES)
    "yo", "tu", "el", "ella", "nosotros", "ellos", "me", "te", "se", "nos",
    "le", "les", "lo", "mi",
    # Verbos frecuentes (ES)
    "es", "son", "esta", "estan", "ser", "estar", "hay", "tiene", "tienen",
    "puede", "pueden", "debe", "deben", "quiero", "quiere", "necesito", "necesita",
    # Adverbios y cuantificadores (ES)
    "muy", "mas", "menos", "tambien", "ademas", "ya", "asi", "bien", "solo",
    "mismo", "cada", "todo", "todos", "toda", "todas", "otro", "otros",
    "nueva", "nuevo",
    # Artículos / preposiciones (EN)
    "the", "of", "and", "to", "in", "a", "is", "for", "on", "are", "with",
    "that", "this", "it", "as", "be", "an", "or", "at", "by", "we", "you",
    "i", "our", "us", "my", "its", "can", "not", "they", "their", "from",
    "all", "have", "has", "had", "will", "which", "your",
    # Palabras neutras comunes
    "use", "using", "used", "also", "any", "each", "when",
})

# ── Sufijos para stemming ──────────────────────────────────────────────────────
# Ordenados de mayor a menor longitud: se aplica el primer sufijo que encaje
# y deje una raíz de longitud mínima válida.
SUFFIXES: tuple = (
    "amientos", "imientos",
    "amiento",  "imiento",  "aciones",
    "miento",   "mente",
    "acion",    "iendo",    "ando",
    "idad",     "cion",     "uras",   "ados",  "idas",
    "ura",      "dad",      "ion",    "ado",   "ida",
    "es",       "os",       "ar",     "er",    "ir",
)

MIN_STEM_LENGTH  = 4
MIN_TOKEN_LENGTH = 2


# ── DTO de resultado ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProcessedText:
    """Resultado inmutable de cada etapa del pipeline NLP."""
    cleaned:  str
    tokens:   List[str]
    filtered: List[str]   # sin stopwords
    stemmed:  List[str]   # tras stemming (usados para el matching)


# ── Pipeline ───────────────────────────────────────────────────────────────────

class TextPreprocessor:
    """
    Ejecuta el pipeline NLP completo sobre texto en español/inglés técnico.
    Puede usarse de forma independiente para preprocesar keywords de referencia.
    """

    def process(self, raw_text: str) -> ProcessedText:
        """Ejecuta las cuatro etapas y devuelve el resultado de cada una."""
        cleaned  = self.clean(raw_text)
        tokens   = self.tokenize(cleaned)
        filtered = self.remove_stopwords(tokens)
        stemmed  = self.stem_all(filtered)
        return ProcessedText(cleaned=cleaned, tokens=tokens,
                             filtered=filtered, stemmed=stemmed)

    # ── Etapa 1: Limpieza ────────────────────────────────────────────────────

    def clean(self, text: str) -> str:
        """
        Normaliza el texto:
        1. Convierte a minúsculas.
        2. Descompone caracteres Unicode (NFD) y elimina marcas diacríticas
           excepto la tilde de la ñ (U+0303).
        3. Elimina caracteres que no sean letra, dígito o espacio.
        4. Colapsa espacios múltiples.
        """
        if not text:
            return ""

        lower = text.lower()

        # NFD descompone, por ej., 'á' → 'a' + U+0301 (acento agudo).
        # Se eliminan todas las marcas combinantes excepto U+0303 (tilde de ñ).
        nfd = unicodedata.normalize("NFD", lower)
        no_accents = "".join(
            ch for ch in nfd
            if unicodedata.category(ch) != "Mn" or ch == "̃"
        )
        recomposed = unicodedata.normalize("NFC", no_accents)

        # Mantener solo letras (ñ incluida), dígitos y espacios
        alpha = re.sub(r"[^a-z0-9ñ\s]", " ", recomposed)
        return re.sub(r"\s+", " ", alpha).strip()

    # ── Etapa 2: Tokenización ────────────────────────────────────────────────

    def tokenize(self, cleaned_text: str) -> List[str]:
        """Divide el texto limpio en tokens, descartando los muy cortos."""
        return [t for t in cleaned_text.split() if len(t) >= MIN_TOKEN_LENGTH]

    # ── Etapa 3: Eliminación de stopwords ───────────────────────────────────

    def remove_stopwords(self, tokens: List[str]) -> List[str]:
        """Filtra tokens que pertenecen al diccionario de stopwords."""
        return [t for t in tokens if t not in STOPWORDS]

    # ── Etapa 4: Stemming ────────────────────────────────────────────────────

    def stem_all(self, tokens: List[str]) -> List[str]:
        """Aplica stemming a cada token de la lista."""
        return [self.stem_word(t) for t in tokens]

    def stem_word(self, word: str) -> str:
        """
        Reduce una palabra a su raíz eliminando el primer sufijo conocido
        que deje una raíz con longitud mínima válida.

        Términos técnicos cortos o siglas (ec2, vpc, aws) no se stemman
        porque no coinciden con ningún sufijo de la lista.
        """
        if not word or len(word) <= MIN_STEM_LENGTH:
            return word

        for suffix in SUFFIXES:
            if word.endswith(suffix):
                root_len = len(word) - len(suffix)
                if root_len >= MIN_STEM_LENGTH:
                    return word[:root_len]

        return word

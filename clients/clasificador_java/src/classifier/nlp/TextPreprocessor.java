package classifier.nlp;

import java.text.Normalizer;
import java.util.*;

/**
 * Pipeline de NLP para preparar el texto antes de la clasificación.
 *
 * Etapas en orden:
 *   1. clean()           → minúsculas, normalización de acentos, limpieza de puntuación
 *   2. tokenize()        → división en tokens por espacio
 *   3. removeStopwords() → eliminación de palabras vacías (sin valor semántico)
 *   4. stemAll()         → reducción de cada token a su raíz morfológica
 *
 * El resultado de cada etapa queda accesible en {@link ProcessedText},
 * lo que permite a la GUI mostrar el proceso completo.
 */
public class TextPreprocessor {

    // ── Stopwords ────────────────────────────────────────────────────────────
    // Palabras de alta frecuencia que no aportan significado para clasificar
    // servicios Cloud. Se incluyen las más comunes del español e inglés técnico.
    private static final Set<String> STOPWORDS = new HashSet<>(Arrays.asList(
        // Artículos y determinantes (ES)
        "el", "la", "los", "las", "un", "una", "unos", "unas",
        "al", "del",
        // Preposiciones (ES)
        "de", "en", "a", "para", "con", "sin", "sobre", "por",
        "ante", "bajo", "desde", "hasta", "hacia", "entre", "segun",
        "durante", "mediante", "tras",
        // Conjunciones (ES)
        "y", "o", "u", "e", "ni", "pero", "sino", "aunque",
        "porque", "que", "como", "cuando", "donde", "si",
        // Pronombres (ES)
        "yo", "tu", "el", "ella", "nosotros", "ellos", "me", "te",
        "se", "nos", "le", "les", "lo", "mi",
        // Verbos auxiliares y copulativos frecuentes (ES)
        "es", "son", "esta", "estan", "ser", "estar", "hay",
        "tiene", "tienen", "puede", "pueden", "debe", "deben",
        "quiero", "quiere", "necesito", "necesita",
        // Adverbios y cuantificadores (ES)
        "muy", "mas", "menos", "tambien", "ademas", "ya", "asi",
        "bien", "solo", "mismo", "cada", "todo", "todos", "toda",
        "todas", "otro", "otros", "nueva", "nuevo",
        // Artículos / preposiciones (EN)
        "the", "of", "and", "to", "in", "a", "is", "for", "on",
        "are", "with", "that", "this", "it", "as", "be", "an",
        "or", "at", "by", "we", "you", "i", "our", "us", "my",
        // Auxiliares y pronombres (EN)
        "can", "not", "they", "their", "from", "all", "have",
        "has", "had", "will", "which", "your", "its",
        // Frases de uso común (tokenizadas por separado, eliminar partes neutras)
        "use", "using", "used", "also", "any", "each", "when"
    ));

    // ── Sufijos para stemming ─────────────────────────────────────────────────
    // Ordenados de mayor a menor longitud: se aplica el primero que encaje
    // con la condición de longitud mínima de la raíz resultante.
    private static final String[] SUFFIXES = {
        "amientos", "imientos",                    // 8
        "amiento",  "imiento",  "aciones",          // 7
        "miento",   "mente",                        // 6
        "acion",    "iendo",    "ando",             // 5
        "idad",     "cion",     "uras",  "ados", "idas",  // 4-5
        "ura",      "dad",      "ion",   "ado",  "ida",   // 3-4
        "es",       "os",       "ar",    "er",   "ir"     // 2
    };

    // La raíz resultante debe tener al menos este número de caracteres
    // para que el stemming sea válido (evita raíces sin sentido como "fun").
    private static final int MIN_STEM_LENGTH  = 4;
    private static final int MIN_TOKEN_LENGTH = 2;

    // ── Pipeline principal ────────────────────────────────────────────────────

    /**
     * Ejecuta las cuatro etapas del pipeline sobre el texto crudo.
     *
     * @param rawText texto introducido por el usuario
     * @return objeto con el resultado de cada etapa
     */
    public ProcessedText process(String rawText) {
        String       cleaned  = clean(rawText);
        List<String> tokens   = tokenize(cleaned);
        List<String> filtered = removeStopwords(tokens);
        List<String> stemmed  = stemAll(filtered);
        return new ProcessedText(cleaned, tokens, filtered, stemmed);
    }

    // ── Etapa 1: Limpieza y normalización ─────────────────────────────────────

    /**
     * Normaliza el texto:
     * 1. Convierte a minúsculas.
     * 2. Descompone caracteres Unicode (NFD) y elimina marcas diacríticas
     *    excepto la tilde de la ñ (U+0303), que se conserva.
     * 3. Re-compone a NFC para que ñ quede como un único carácter.
     * 4. Sustituye cualquier carácter que no sea letra, dígito o espacio por espacio.
     * 5. Colapsa espacios múltiples.
     */
    public String clean(String text) {
        if (text == null) return "";

        String lower = text.toLowerCase();

        // NFD descompone, por ejemplo, "á" → "a" + U+0301 (acento agudo).
        // Se eliminan todas las marcas diacríticas SALVO U+0303 (tilde de ñ).
        String nfd = Normalizer.normalize(lower, Normalizer.Form.NFD)
                               .replaceAll("[\\p{InCombiningDiacriticalMarks}&&[^̃]]", "");

        // NFC re-compone "n" + U+0303 → "ñ"
        String recomposed = Normalizer.normalize(nfd, Normalizer.Form.NFC);

        // Conservar letras (incluyendo ñ), dígitos y espacios; reemplazar lo demás
        String alphanum = recomposed.replaceAll("[^a-z0-9ñ\\s]", " ");

        return alphanum.replaceAll("\\s+", " ").trim();
    }

    // ── Etapa 2: Tokenización ─────────────────────────────────────────────────

    /**
     * Divide el texto limpio en tokens separados por espacios.
     * Descarta tokens con longitud menor a {@value #MIN_TOKEN_LENGTH}.
     */
    public List<String> tokenize(String cleanedText) {
        List<String> tokens = new ArrayList<>();
        if (cleanedText == null || cleanedText.isBlank()) return tokens;

        for (String token : cleanedText.split("\\s+")) {
            if (token.length() >= MIN_TOKEN_LENGTH) {
                tokens.add(token);
            }
        }
        return tokens;
    }

    // ── Etapa 3: Eliminación de stopwords ────────────────────────────────────

    /**
     * Elimina del listado de tokens aquellos que pertenecen al diccionario
     * de stopwords: artículos, preposiciones, conjunciones, etc.
     */
    public List<String> removeStopwords(List<String> tokens) {
        List<String> result = new ArrayList<>();
        for (String token : tokens) {
            if (!STOPWORDS.contains(token)) {
                result.add(token);
            }
        }
        return result;
    }

    // ── Etapa 4: Stemming ─────────────────────────────────────────────────────

    /**
     * Aplica stemming (reducción morfológica) a cada token de la lista.
     */
    public List<String> stemAll(List<String> tokens) {
        List<String> stemmed = new ArrayList<>();
        for (String token : tokens) {
            stemmed.add(stemWord(token));
        }
        return stemmed;
    }

    /**
     * Reduce una palabra a su raíz eliminando el primer sufijo conocido que cumpla
     * la condición de longitud mínima de raíz resultante.
     *
     * Términos técnicos cortos o siglas (ec2, vpc, aws, lambda) no se stemman
     * porque no coinciden con ningún sufijo español de la lista.
     *
     * @param word token ya limpio (minúsculas, sin acentos)
     * @return raíz del token, o el token original si no aplica ninguna regla
     */
    public String stemWord(String word) {
        if (word == null || word.length() <= MIN_STEM_LENGTH) return word;

        for (String suffix : SUFFIXES) {
            if (word.endsWith(suffix)) {
                int rootLength = word.length() - suffix.length();
                if (rootLength >= MIN_STEM_LENGTH) {
                    return word.substring(0, rootLength);
                }
            }
        }
        return word;
    }

    // ── DTO de resultado ──────────────────────────────────────────────────────

    /**
     * Contiene el resultado de cada etapa del pipeline NLP.
     * Inmutable: todas las listas son de solo lectura.
     */
    public static class ProcessedText {

        /** Texto tras limpieza y normalización (antes de tokenizar). */
        public final String       cleaned;

        /** Todos los tokens obtenidos al dividir el texto limpio. */
        public final List<String> tokens;

        /** Tokens tras eliminar stopwords. */
        public final List<String> filtered;

        /** Tokens tras aplicar stemming (estos se usan para el matching). */
        public final List<String> stemmed;

        public ProcessedText(String cleaned,
                             List<String> tokens,
                             List<String> filtered,
                             List<String> stemmed) {
            this.cleaned  = cleaned;
            this.tokens   = Collections.unmodifiableList(tokens);
            this.filtered = Collections.unmodifiableList(filtered);
            this.stemmed  = Collections.unmodifiableList(stemmed);
        }
    }
}

package classifier;

import classifier.nlp.TextPreprocessor;
import classifier.nlp.TextPreprocessor.ProcessedText;

import java.util.*;

/**
 * Clasificador de servicios Cloud usando un pipeline NLP.
 *
 * Flujo interno:
 *   texto crudo → {@link TextPreprocessor} → tokens stemmed
 *   → puntuación por modelo → modelo ganador
 *
 * Esta clase no contiene ningún elemento de Swing ni de presentación.
 * Tampoco realiza validaciones de formulario (eso corresponde a la GUI);
 * solo valida que el texto sea semánticamente clasificable.
 *
 * Estrategia de puntuación:
 *   Cada modelo tiene un conjunto de palabras clave de referencia que se
 *   procesa una sola vez al construir el clasificador (en buildKeywordSet).
 *   Los tokens stemmed del texto del usuario se comparan contra ese conjunto.
 *   Las frases multi-palabra se buscan como substring en el texto limpio.
 *   El modelo con mayor puntaje total gana; en empate gana el más específico:
 *   FaaS > SaaS > PaaS > IaaS.
 */
public class CloudClassifier {

    private static final int MIN_TEXT_LENGTH = 5;
    private static final int MAX_TEXT_LENGTH = 2000;

    private final TextPreprocessor preprocessor;

    // Conjuntos de referencia construidos una sola vez al inicializar.
    // Cada set contiene tanto la forma stemmed como la no stemmed de cada keyword,
    // garantizando coincidencia con tokens en cualquier etapa de inflexión.
    private final Set<String> iaasKeywords;
    private final Set<String> paasKeywords;
    private final Set<String> saasKeywords;
    private final Set<String> faasKeywords;

    public CloudClassifier() {
        this.preprocessor = new TextPreprocessor();

        // ── IaaS: Infraestructura como Servicio ──────────────────────────────
        // Conceptos: virtualización de hardware, almacenamiento en bloque,
        // redes definidas por software, instancias de cómputo.
        this.iaasKeywords = buildKeywordSet(
            "infraestructura", "maquina virtual", "servidor", "almacenamiento",
            "red virtual", "red privada", "disco duro", "cpu virtual", "vcpu",
            "hipervisor", "instancias", "balanceador de carga", "load balancer",
            "ip publica", "firewall", "bare metal", "aprovisionamiento",
            "backup", "snapshot", "datacenter", "centro de datos",
            "escalado de infraestructura", "ec2", "azure vm", "compute engine",
            "vpc", "recursos de computo", "virtualizacion", "almacenamiento en bloque",
            "red definida por software", "contenedores de bajo nivel"
        );

        // ── PaaS: Plataforma como Servicio ───────────────────────────────────
        // Conceptos: entornos de desarrollo gestionados, despliegue de apps,
        // bases de datos gestionadas, pipelines CI/CD, runtimes.
        this.paasKeywords = buildKeywordSet(
            "plataforma", "entorno de desarrollo", "runtime", "framework",
            "despliegue", "deploy", "base de datos gestionada", "managed database",
            "middleware", "pipeline", "ci cd", "heroku", "google app engine",
            "azure app service", "elastic beanstalk", "openshift",
            "kubernetes gestionado", "contenedor gestionado", "orquestacion",
            "api gateway", "backend como servicio", "devops",
            "integracion continua", "entrega continua", "repositorio gestionado",
            "paas", "aplicacion web", "contenedor", "motor de aplicaciones",
            "plataforma de desarrollo", "entorno gestionado"
        );

        // ── SaaS: Software como Servicio ─────────────────────────────────────
        // Conceptos: aplicaciones de usuario final, suscripción, acceso via
        // navegador, herramientas de colaboración y productividad empresarial.
        this.saasKeywords = buildKeywordSet(
            "software como servicio", "aplicacion en la nube", "suscripcion",
            "correo electronico", "email", "crm", "erp", "colaboracion",
            "google workspace", "office 365", "microsoft 365", "salesforce",
            "dropbox", "slack", "zoom", "teams", "trello", "notion",
            "aplicacion lista para usar", "usuario final", "sin instalacion",
            "acceso desde navegador", "saas", "gestion empresarial",
            "facturacion en linea", "videoconferencia", "almacenamiento de archivos",
            "suite ofice", "herramienta de productividad", "pago por suscripcion"
        );

        // ── FaaS: Función como Servicio (Serverless) ──────────────────────────
        // Conceptos: funciones activadas por eventos, ejecución bajo demanda,
        // sin gestión de servidores, pago por invocación.
        this.faasKeywords = buildKeywordSet(
            "funcion", "serverless", "sin servidor", "lambda", "aws lambda",
            "azure functions", "google cloud functions", "event driven",
            "orientado a eventos", "trigger", "disparador",
            "ejecucion bajo demanda", "pago por ejecucion", "faas",
            "funcion asincrona", "webhook", "cold start",
            "sin gestionar servidores", "funcion en la nube", "microservicio",
            "arquitectura dirigida por eventos", "ejecucion por invocacion",
            "funcion activada", "ejecucion efimera"
        );
    }

    // ── API pública ───────────────────────────────────────────────────────────

    /**
     * Valida el texto y ejecuta el pipeline NLP completo.
     *
     * @param rawText texto introducido por el usuario (sin preprocesar)
     * @return {@link ClassificationResult} con modelo ganador, puntajes y etapas NLP
     * @throws ClassificationException si el texto no cumple los requisitos mínimos
     */
    public ClassificationResult classify(String rawText) throws ClassificationException {
        validateText(rawText);

        // Ejecutar pipeline NLP
        ProcessedText processed = preprocessor.process(rawText);

        // Conjunto de búsqueda O(1) con los tokens stemmed de la entrada
        Set<String> tokenSet  = new HashSet<>(processed.stemmed);
        String      cleanText = processed.cleaned;

        // Puntaje independiente para cada modelo
        EnumMap<CloudModel, Integer> scores = new EnumMap<>(CloudModel.class);
        scores.put(CloudModel.IAAS, scoreIaaS(tokenSet, cleanText));
        scores.put(CloudModel.PAAS, scorePaaS(tokenSet, cleanText));
        scores.put(CloudModel.SAAS, scoreSaaS(tokenSet, cleanText));
        scores.put(CloudModel.FAAS, scoreFaaS(tokenSet, cleanText));

        CloudModel winner = resolveWinner(scores);
        return new ClassificationResult(winner, scores, processed);
    }

    // ── Validación ────────────────────────────────────────────────────────────

    /**
     * Verifica condiciones necesarias para clasificar el texto.
     * Lanza {@link ClassificationException} con mensaje explicativo si falla alguna.
     */
    private void validateText(String text) throws ClassificationException {
        if (text == null || text.isBlank()) {
            throw new ClassificationException("La descripción no puede estar vacía.");
        }

        String trimmed = text.trim();

        if (trimmed.length() < MIN_TEXT_LENGTH) {
            throw new ClassificationException(
                "El texto es demasiado corto. Escribe al menos " + MIN_TEXT_LENGTH + " caracteres."
            );
        }

        if (trimmed.length() > MAX_TEXT_LENGTH) {
            throw new ClassificationException(
                "El texto supera el límite de " + MAX_TEXT_LENGTH + " caracteres."
            );
        }

        // Debe contener al menos una letra (rechaza entradas de solo números o símbolos)
        if (!trimmed.matches(".*\\p{L}.*")) {
            throw new ClassificationException(
                "La descripción debe contener texto legible, no solo números o símbolos."
            );
        }
    }

    // ── Métodos de puntuación por modelo ────────────────────────────────────
    // Cada método delega a scoreModel() con su propio conjunto de keywords.
    // Están separados para mantener la intención clara y facilitar extensión futura.

    /** Puntúa el texto contra keywords de IaaS. */
    private int scoreIaaS(Set<String> tokenSet, String cleanText) {
        return scoreModel(tokenSet, cleanText, iaasKeywords);
    }

    /** Puntúa el texto contra keywords de PaaS. */
    private int scorePaaS(Set<String> tokenSet, String cleanText) {
        return scoreModel(tokenSet, cleanText, paasKeywords);
    }

    /** Puntúa el texto contra keywords de SaaS. */
    private int scoreSaaS(Set<String> tokenSet, String cleanText) {
        return scoreModel(tokenSet, cleanText, saasKeywords);
    }

    /** Puntúa el texto contra keywords de FaaS. */
    private int scoreFaaS(Set<String> tokenSet, String cleanText) {
        return scoreModel(tokenSet, cleanText, faasKeywords);
    }

    // ── Lógica de scoring ────────────────────────────────────────────────────

    /**
     * Cuenta las coincidencias entre los tokens stemmed del usuario y el conjunto
     * de keywords de referencia.
     *
     * - Palabras simples: se buscan directamente en el conjunto de tokens stemmed.
     * - Frases multi-palabra (contienen espacio): se buscan como substring en el
     *   texto limpio completo y valen 2 puntos (bonus de especificidad).
     *
     * @param tokenSet  tokens stemmed del texto del usuario (acceso O(1))
     * @param cleanText texto limpio (para búsqueda de frases)
     * @param keywords  conjunto de referencia del modelo
     */
    private int scoreModel(Set<String> tokenSet, String cleanText, Set<String> keywords) {
        int score = 0;
        for (String kw : keywords) {
            if (kw.contains(" ")) {
                // Frase exacta: vale más porque identifica el concepto completo
                if (cleanText.contains(kw)) score += 2;
            } else {
                if (tokenSet.contains(kw)) score++;
            }
        }
        return score;
    }

    /**
     * Construye el conjunto de referencia de un modelo procesando cada keyword
     * a través de las mismas etapas de normalización (sin stopwords, porque
     * los keywords ya son términos significativos).
     *
     * Para cada keyword se añaden al set:
     *   - La frase limpia completa (para frases multi-palabra).
     *   - Cada token limpio en forma no stemmed.
     *   - Cada token limpio en forma stemmed.
     *
     * Guardar ambas formas garantiza que una entrada como "funciones" (→ stem "funcion")
     * coincida con el keyword "función" (→ stem "func") O con su forma intermedia.
     */
    private Set<String> buildKeywordSet(String... rawKeywords) {
        Set<String> result = new HashSet<>();
        for (String raw : rawKeywords) {
            String cleaned = preprocessor.clean(raw);

            // Guardar la frase completa para substring matching
            if (cleaned.contains(" ")) {
                result.add(cleaned);
            }

            // Tokenizar y guardar cada token en forma original y stemmed
            for (String token : preprocessor.tokenize(cleaned)) {
                result.add(token);                          // forma limpia
                result.add(preprocessor.stemWord(token));  // forma stemmed
            }
        }
        return result;
    }

    // ── Resolución del ganador ────────────────────────────────────────────────

    /**
     * Devuelve el modelo con mayor puntaje.
     * En caso de empate, el orden de prioridad es:
     *   FaaS > SaaS > PaaS > IaaS (más específico gana).
     * Si todos los puntajes son cero, devuelve UNKNOWN.
     */
    private CloudModel resolveWinner(EnumMap<CloudModel, Integer> scores) {
        int max = scores.values().stream().mapToInt(Integer::intValue).max().orElse(0);
        if (max == 0) return CloudModel.UNKNOWN;

        if (scores.get(CloudModel.FAAS) == max) return CloudModel.FAAS;
        if (scores.get(CloudModel.SAAS) == max) return CloudModel.SAAS;
        if (scores.get(CloudModel.PAAS) == max) return CloudModel.PAAS;
        return CloudModel.IAAS;
    }
}

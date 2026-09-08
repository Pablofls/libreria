import classifier.ClassificationException;
import classifier.ClassificationResult;
import classifier.CloudClassifier;
import classifier.CloudModel;

import java.util.EnumMap;
import java.util.List;

/**
 * Punto de entrada para usar el clasificador desde línea de comandos.
 *
 * Comparte exactamente la misma lógica que la GUI ({@link gui.AppWindow}):
 * ambas instancian {@link CloudClassifier} y llaman a classify().
 * No existe duplicación de reglas ni de pipeline NLP.
 *
 * Uso:
 *   java -cp out CloudClassifierCLI "descripción del servicio"
 *
 * Opciones:
 *   --help          Muestra la ayuda y termina.
 *   --verbose       Muestra también los tokens NLP y el detalle de cada etapa.
 *
 * Códigos de salida:
 *   0 → clasificación exitosa
 *   1 → error de validación o argumento inválido
 *   2 → error inesperado
 */
public class CloudClassifierCLI {

    // Códigos ANSI para colores en terminales compatibles (macOS / Linux)
    private static final String RESET  = "[0m";
    private static final String BOLD   = "[1m";
    private static final String CYAN   = "[36m";
    private static final String GREEN  = "[32m";
    private static final String YELLOW = "[33m";
    private static final String BLUE   = "[34m";
    private static final String PURPLE = "[35m";
    private static final String ORANGE = "[38;5;208m";
    private static final String GRAY   = "[90m";
    private static final String RED    = "[31m";

    public static void main(String[] args) {
        // Parsear flags y texto de entrada
        boolean verbose = false;
        StringBuilder textBuilder = new StringBuilder();

        for (String arg : args) {
            if (arg.equals("--help") || arg.equals("-h")) {
                printUsage();
                System.exit(0);
            } else if (arg.equals("--verbose") || arg.equals("-v")) {
                verbose = true;
            } else {
                if (textBuilder.length() > 0) textBuilder.append(" ");
                textBuilder.append(arg);
            }
        }

        if (textBuilder.length() == 0) {
            printUsage();
            System.exit(1);
        }

        String text = textBuilder.toString();

        // Clasificar usando la misma lógica que la GUI
        CloudClassifier classifier = new CloudClassifier();
        try {
            ClassificationResult result = classifier.classify(text);
            printResult(result, verbose);
            System.exit(0);

        } catch (ClassificationException ex) {
            System.err.println(RED + "Error: " + ex.getMessage() + RESET);
            System.exit(1);

        } catch (Exception ex) {
            System.err.println(RED + "Error inesperado: " + ex.getMessage() + RESET);
            System.exit(2);
        }
    }

    // ── Salida principal ──────────────────────────────────────────────────────

    /**
     * Imprime el resultado en la terminal.
     * En modo normal muestra el modelo y los puntajes.
     * Con --verbose añade el detalle de cada etapa del pipeline NLP.
     */
    private static void printResult(ClassificationResult result, boolean verbose) {
        CloudModel model  = result.getModel();
        String     color  = colorFor(model);
        EnumMap<CloudModel, Integer> scores = result.getScores();
        int max = Math.max(result.getMaxScore(), 1);

        // Línea principal (formato requerido)
        System.out.println();
        System.out.println(BOLD + "Modelo identificado: " + color + model.getLabel() + RESET);
        System.out.println(GRAY + model.getDescription() + RESET);
        System.out.println();

        // Barras de puntaje
        System.out.println(BOLD + "Puntajes:" + RESET);
        printBar("IaaS", scores.get(CloudModel.IAAS), max, BLUE);
        printBar("PaaS", scores.get(CloudModel.PAAS), max, GREEN);
        printBar("SaaS", scores.get(CloudModel.SAAS), max, PURPLE);
        printBar("FaaS", scores.get(CloudModel.FAAS), max, ORANGE);

        // Detalle NLP con --verbose
        if (verbose) {
            printNlpDetail(result);
        }

        System.out.println();
    }

    /** Imprime una barra de puntaje con bloques Unicode. */
    private static void printBar(String name, int score, int max, String color) {
        int totalBlocks = 24;
        int filled = max > 0 ? (score * totalBlocks / max) : 0;
        String bar = "█".repeat(filled) + GRAY + "░".repeat(totalBlocks - filled) + RESET;
        System.out.printf("  %s%-4s%s %s %s%2d%s%n",
                          color, name, RESET, bar, BOLD, score, RESET);
    }

    /** Muestra el detalle de cada etapa del pipeline NLP. */
    private static void printNlpDetail(ClassificationResult result) {
        var processed = result.getProcessedText();
        System.out.println();
        System.out.println(BOLD + "Pipeline NLP:" + RESET);
        printNlpStage("1. Texto limpio  ", processed.cleaned);
        printNlpStage("2. Tokens        ", String.join(", ", processed.tokens));
        printNlpStage("3. Sin stopwords ", String.join(", ", processed.filtered));
        printNlpStage("4. Stems (match) ", String.join(" · ", processed.stemmed));
    }

    private static void printNlpStage(String label, String value) {
        System.out.println("  " + CYAN + label + RESET + ": " + value);
    }

    // ── Ayuda ─────────────────────────────────────────────────────────────────

    private static void printUsage() {
        System.out.println();
        System.out.println(BOLD + "Cloud Models Classifier — CLI" + RESET);
        System.out.println(GRAY + "Clasifica una descripción como IaaS, PaaS, SaaS o FaaS." + RESET);
        System.out.println();
        System.out.println(BOLD + "Uso:" + RESET);
        System.out.println("  java -cp out CloudClassifierCLI [opciones] \"<descripción>\"");
        System.out.println();
        System.out.println(BOLD + "Opciones:" + RESET);
        System.out.println("  --verbose, -v   Muestra el detalle de cada etapa del pipeline NLP");
        System.out.println("  --help,    -h   Muestra esta ayuda");
        System.out.println();
        System.out.println(BOLD + "Ejemplos:" + RESET);
        System.out.println("  java -cp out CloudClassifierCLI \"máquinas virtuales almacenamiento redes\"");
        System.out.println("  java -cp out CloudClassifierCLI --verbose \"función serverless AWS Lambda\"");
        System.out.println("  java -cp out CloudClassifierCLI \"despliegue en Heroku con base de datos gestionada\"");
        System.out.println();
    }

    // ── Colores por modelo ────────────────────────────────────────────────────

    private static String colorFor(CloudModel model) {
        switch (model) {
            case IAAS: return BLUE;
            case PAAS: return GREEN;
            case SAAS: return PURPLE;
            case FAAS: return ORANGE;
            default:   return GRAY;
        }
    }
}

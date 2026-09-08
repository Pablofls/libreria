package classifier;

import classifier.nlp.TextPreprocessor.ProcessedText;
import java.util.EnumMap;

/**
 * Resultado completo de una clasificación.
 *
 * Agrupa el modelo ganador, el mapa de puntajes por modelo y
 * el objeto con el detalle de cada etapa del pipeline NLP.
 * La GUI puede usar todo esto para mostrar información transparente
 * sobre cómo se tomó la decisión.
 */
public class ClassificationResult {

    private final CloudModel              model;
    private final EnumMap<CloudModel, Integer> scores;
    private final ProcessedText           processedText;

    public ClassificationResult(CloudModel model,
                                EnumMap<CloudModel, Integer> scores,
                                ProcessedText processedText) {
        this.model         = model;
        this.scores        = scores;
        this.processedText = processedText;
    }

    public CloudModel getModel()               { return model; }
    public EnumMap<CloudModel, Integer> getScores() { return scores; }
    public ProcessedText getProcessedText()    { return processedText; }

    /** Puntaje máximo entre los cuatro modelos (útil para escalar las barras). */
    public int getMaxScore() {
        return scores.values().stream().mapToInt(Integer::intValue).max().orElse(1);
    }
}

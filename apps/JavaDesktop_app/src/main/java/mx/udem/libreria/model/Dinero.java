package mx.udem.libreria.model;

import com.fasterxml.jackson.databind.JsonNode;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.text.NumberFormat;
import java.util.Locale;

/** Importes en pesos con BigDecimal: nunca double para dinero. */
public final class Dinero {

    private static final NumberFormat MXN = NumberFormat.getCurrencyInstance(Locale.forLanguageTag("es-MX"));

    private Dinero() { }

    /** Los servicios mandan el dinero como número o como texto ("199.00"). */
    public static BigDecimal de(JsonNode n) {
        if (n == null || n.isNull() || n.isMissingNode() || n.asText().isBlank()) return BigDecimal.ZERO;
        return new BigDecimal(n.asText()).setScale(2, RoundingMode.HALF_UP);
    }

    public static String texto(BigDecimal importe) {
        return MXN.format(importe == null ? BigDecimal.ZERO : importe);
    }
}

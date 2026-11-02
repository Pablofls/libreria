package mx.udem.libreria.rastreo;

import java.util.Locale;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Código de rastreo de un pedido: LIB-MTY-&lt;año de creación&gt;-&lt;id en 6 dígitos&gt;,
 * por ejemplo LIB-MTY-2026-000125.
 *
 * Es determinista (sale del pedido real), así que se puede volver a calcular en
 * cualquier momento y no hace falta guardarlo. Conocerlo no da acceso: el
 * servidor de rastreo pregunta al servicio de pedidos, con el JWT del usuario,
 * si ese pedido es suyo. La misma regla vive en gps/microservice/entregas.py.
 */
public final class CodigoRastreo {

    private static final Pattern FORMATO = Pattern.compile("^LIB-MTY-(\\d{4})-(\\d{6})$");

    private CodigoRastreo() { }

    public record Partes(int anio, int pedidoId) { }

    public static String formatear(int pedidoId, int anio) {
        if (pedidoId < 1 || pedidoId > 999_999) throw new IllegalArgumentException("Id de pedido fuera de rango.");
        return String.format("LIB-MTY-%04d-%06d", anio, pedidoId);
    }

    public static Optional<Partes> parsear(String codigo) {
        if (codigo == null) return Optional.empty();
        Matcher m = FORMATO.matcher(codigo.trim().toUpperCase(Locale.ROOT));
        if (!m.matches() || Integer.parseInt(m.group(2)) == 0) return Optional.empty();
        return Optional.of(new Partes(Integer.parseInt(m.group(1)), Integer.parseInt(m.group(2))));
    }

    /** Forma canónica (mayúsculas, sin espacios) o vacío si no es válido. */
    public static Optional<String> normalizar(String codigo) {
        return parsear(codigo).map(p -> formatear(p.pedidoId(), p.anio()));
    }
}

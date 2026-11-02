package mx.udem.libreria.api;

import java.util.List;
import java.util.Map;

/**
 * Error de un microservicio, con el mensaje que el propio servicio escribió para
 * la persona ({"codigo", "mensaje", "detalles"}). Nunca lleva trazas ni SQL.
 */
public class ApiException extends Exception {

    private static final Map<Integer, String> MENSAJES = Map.of(
            0, "No se pudo conectar con el servidor. Revisa tu conexión.",
            400, "Los datos enviados no son válidos.",
            401, "Tu sesión no es válida o venció. Vuelve a iniciar sesión.",
            403, "Tu rol no permite esta operación.",
            404, "No existe lo que buscas.",
            409, "La operación choca con el estado actual.",
            429, "Demasiados intentos. Espera unos minutos.",
            503, "El servicio no está disponible en este momento.");

    private final int estado;
    private final List<String> detalles;

    public ApiException(int estado, String mensaje, List<String> detalles) {
        super(mensaje == null || mensaje.isBlank() ? porDefecto(estado) : mensaje);
        this.estado = estado;
        this.detalles = detalles == null ? List.of() : List.copyOf(detalles);
    }

    public ApiException(int estado, String mensaje) {
        this(estado, mensaje, List.of());
    }

    public static String porDefecto(int estado) {
        return MENSAJES.getOrDefault(estado, "El servicio respondió con un error (" + estado + ").");
    }

    public int estado() { return estado; }

    public List<String> detalles() { return detalles; }

    public boolean sesionPerdida() { return estado == 401; }

    /** Mensaje + detalles, listo para un diálogo. */
    public String texto() {
        if (detalles.isEmpty()) return getMessage();
        return getMessage() + "\n\n• " + String.join("\n• ", detalles);
    }
}

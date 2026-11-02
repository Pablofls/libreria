package mx.udem.libreria.model;

import com.fasterxml.jackson.databind.JsonNode;
import mx.udem.libreria.rastreo.CodigoRastreo;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;

/**
 * Un pedido del microservicio pedidos (GET /orders, GET /orders/{id}).
 * total y pagado vienen de la vista v_pedidos_total: no se calculan aquí.
 * En el listado no vienen líneas ni historial (listas vacías).
 */
public record Pedido(int id, String estado, OffsetDateTime creadoEn, BigDecimal total,
                     BigDecimal pagado, List<Linea> lineas, List<CambioEstado> historial) {

    public record Linea(int libroId, String titulo, int cantidad, BigDecimal precioUnitario, BigDecimal subtotal) { }

    public record CambioEstado(String estado, OffsetDateTime cuando) { }

    public static Pedido desde(JsonNode n) {
        List<Linea> lineas = new ArrayList<>();
        for (JsonNode l : n.path("lineas")) {
            lineas.add(new Linea(l.path("libro_id").asInt(), l.path("titulo").asText(), l.path("cantidad").asInt(),
                    Dinero.de(l.path("precio_unitario")), Dinero.de(l.path("subtotal"))));
        }
        List<CambioEstado> historial = new ArrayList<>();
        for (JsonNode h : n.path("historial")) {
            historial.add(new CambioEstado(h.path("estado").asText(), fecha(h.path("cambiado_en").asText(null))));
        }
        return new Pedido(n.path("id").asInt(), n.path("estado").asText(), fecha(n.path("creado_en").asText(null)),
                Dinero.de(n.path("total")), Dinero.de(n.path("pagado")), List.copyOf(lineas), List.copyOf(historial));
    }

    static OffsetDateTime fecha(String iso) {
        if (iso == null || iso.isBlank()) return null;
        String t = iso.replace(" ", "T");
        try {
            return OffsetDateTime.parse(t);
        } catch (java.time.format.DateTimeParseException sinZona) {
            return java.time.LocalDateTime.parse(t).atOffset(java.time.ZoneOffset.UTC);
        }
    }

    /** Código de rastreo, determinista: año de creación + id. */
    public String codigoRastreo() {
        return CodigoRastreo.formatear(id, creadoEn == null ? OffsetDateTime.now().getYear() : creadoEn.getYear());
    }

    /** Sólo un pedido pagado (o ya enviado) tiene un envío que rastrear. */
    public boolean rastreable() {
        return "pagado".equals(estado) || "enviado".equals(estado);
    }
}

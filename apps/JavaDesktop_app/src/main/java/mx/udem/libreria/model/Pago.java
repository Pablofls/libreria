package mx.udem.libreria.model;

import com.fasterxml.jackson.databind.JsonNode;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/** Un pago simulado del microservicio pagos (GET/POST /payments). */
public record Pago(int id, int pedidoId, String metodo, String estado, BigDecimal monto,
                   String referencia, OffsetDateTime creadoEn, String pedidoEstado) {

    public static Pago desde(JsonNode n) {
        return new Pago(n.path("id").asInt(), n.path("pedido_id").asInt(), n.path("metodo").asText(),
                n.path("estado").asText(), Dinero.de(n.path("monto")), n.path("referencia").asText(null),
                Pedido.fecha(n.path("creado_en").asText(null)), n.path("pedido_estado").asText(null));
    }
}

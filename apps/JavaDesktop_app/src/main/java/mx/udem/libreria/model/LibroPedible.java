package mx.udem.libreria.model;

import com.fasterxml.jackson.databind.JsonNode;

import java.math.BigDecimal;

/**
 * Libro según el servicio de pedidos (GET /orders/books): trae el id numérico
 * que piden las líneas del pedido —el catálogo no lo expone— y el precio y el
 * stock vigentes, que son los que valen al comprar.
 */
public record LibroPedible(int id, String isbn, String titulo, BigDecimal precio, int stock) {

    public static LibroPedible desde(JsonNode n) {
        return new LibroPedible(n.path("id").asInt(), n.path("isbn").asText(), n.path("titulo").asText(),
                Dinero.de(n.path("precio")), n.path("stock").asInt(0));
    }
}

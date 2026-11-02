package mx.udem.libreria.model;

import com.fasterxml.jackson.databind.JsonNode;

import java.time.OffsetDateTime;

/** Perfil del microservicio users (GET /users/{id}). */
public record Usuario(int id, String email, String rol, boolean activo, OffsetDateTime creadoEn,
                      String nombre, String apellidoPaterno, String apellidoMaterno) {

    public static Usuario desde(JsonNode n) {
        return new Usuario(n.path("id").asInt(), n.path("email").asText(), n.path("rol").asText(),
                n.path("activo").asBoolean(true), Pedido.fecha(n.path("creado_en").asText(null)),
                n.path("nombre").asText(""), n.path("apellido_paterno").asText(""),
                n.path("apellido_materno").asText(""));
    }

    public String nombreCompleto() {
        return String.join(" ", nombre, apellidoPaterno, apellidoMaterno).trim().replaceAll(" +", " ");
    }
}

package mx.udem.libreria.model;

import com.fasterxml.jackson.databind.JsonNode;

/** Un autor del microservicio authors (GET /authors). */
public record Autor(int id, String nombre, String nacionalidad, String biografia, int libros) {

    public static Autor desde(JsonNode n) {
        return new Autor(n.path("id").asInt(), n.path("nombre").asText(),
                n.path("nacionalidad").asText(null), n.path("biografia").asText(null),
                n.path("libros").asInt(0));
    }
}

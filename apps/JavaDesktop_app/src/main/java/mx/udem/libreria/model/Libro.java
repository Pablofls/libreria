package mx.udem.libreria.model;

import com.fasterxml.jackson.databind.JsonNode;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

/**
 * Un libro tal como lo publica el microservicio de catálogo (GET /books).
 * Las claves del JSON están en inglés porque así es el contrato del catálogo.
 *
 * @param portada nombre del archivo de la portada (images[].file con cover=true),
 *                o null si el libro no tiene imagen.
 */
public record Libro(String isbn, String titulo, List<AutorRef> autores, Integer anio,
                    String sinopsis, BigDecimal precio, int stock, String formato,
                    List<String> generos, String portada) {

    /** Autor tal como viene dentro de un libro del catálogo (sin id). */
    public record AutorRef(String nombre, String nacionalidad) { }

    public static Libro desde(JsonNode n) {
        List<AutorRef> autores = new ArrayList<>();
        for (JsonNode a : n.path("authors")) {
            autores.add(new AutorRef(a.path("name").asText(), a.path("nationality").asText(null)));
        }
        List<String> generos = new ArrayList<>();
        n.path("genres").forEach(g -> generos.add(g.asText()));
        String portada = null;
        for (JsonNode img : n.path("images")) {
            if (portada == null || img.path("cover").asBoolean()) {
                portada = img.path("file").asText(null);
                if (img.path("cover").asBoolean()) break;
            }
        }
        return new Libro(
                n.path("isbn").asText(),
                n.path("title").asText(),
                List.copyOf(autores),
                n.hasNonNull("year") ? n.get("year").asInt() : null,
                n.path("synopsis").asText(null),
                Dinero.de(n.path("price")),
                n.path("stock").asInt(0),
                n.path("format").asText(""),
                List.copyOf(generos),
                portada);
    }

    public String autoresTexto() {
        if (autores.isEmpty()) return "Autor desconocido";
        return String.join(", ", autores.stream().map(AutorRef::nombre).toList());
    }

    public boolean disponible() { return stock > 0; }
}

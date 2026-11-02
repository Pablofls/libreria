package mx.udem.libreria.api;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import mx.udem.libreria.model.Autor;
import mx.udem.libreria.model.Libro;
import mx.udem.libreria.model.LibroPedible;
import mx.udem.libreria.model.Pago;
import mx.udem.libreria.model.Pedido;
import mx.udem.libreria.model.Usuario;

import java.math.BigDecimal;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.function.Function;

/**
 * Las operaciones de negocio, una por endpoint REST real de los microservicios.
 * Rutas, métodos y cuerpos salen del código de cada servicio en apps/services/;
 * aquí no se inventa ninguno ni se toca la base de datos.
 *
 *   login    (5000)  POST /login · POST /token/refresh · POST /logout   (en ApiClient)
 *   users    (5003)  GET /users/{id}
 *   catalogo (5002)  GET /books · GET /books/search?titulo= · GET /books/{isbn}
 *   authors  (5004)  GET /authors · GET /authors/{id} · GET /authors/{id}/books
 *   pedidos  (5005)  GET /orders/books · POST /orders · GET /orders · GET /orders/{id}
 *                    POST /orders/{id}/cancel
 *   pagos    (5006)  POST /payments · GET /payments?pedido_id=
 */
public final class LibreriaApi {

    private final ApiClient api;

    public LibreriaApi(ApiClient api) { this.api = api; }

    public ApiClient cliente() { return api; }

    // --- users ------------------------------------------------------------------

    public Usuario perfil() throws ApiException {
        return Usuario.desde(api.get("/users/" + api.sesion().usuarioId()));
    }

    // --- catálogo (público) -----------------------------------------------------

    public List<Libro> catalogo() throws ApiException {
        return lista(api.getPublico("/books").path("books"), Libro::desde);
    }

    public List<Libro> buscarPorTitulo(String titulo) throws ApiException {
        return lista(api.getPublico("/books/search?titulo=" + url(titulo)).path("books"), Libro::desde);
    }

    public Libro libro(String isbn) throws ApiException {
        JsonNode libros = api.getPublico("/books/" + url(isbn)).path("books");
        if (!libros.isArray() || libros.isEmpty()) throw new ApiException(404, "No existe un libro con ese ISBN.");
        return Libro.desde(libros.get(0));
    }

    // --- authors (GET públicos) ---------------------------------------------------

    public List<Autor> autores() throws ApiException {
        return lista(api.getPublico("/authors"), Autor::desde);
    }

    /** Títulos de los libros de un autor (id, isbn, titulo, orden). */
    public List<String> librosDeAutor(int autorId) throws ApiException {
        List<String> titulos = new ArrayList<>();
        api.getPublico("/authors/" + autorId + "/books").forEach(n -> titulos.add(n.path("titulo").asText()));
        return titulos;
    }

    // --- pedidos ------------------------------------------------------------------

    /** Id, precio y stock vigentes de cada libro (lo que vale al comprar). */
    public List<LibroPedible> librosParaPedir() throws ApiException {
        return lista(api.get("/orders/books"), LibroPedible::desde);
    }

    /** Crea el pedido. El precio de cada línea lo pone el servidor, nunca el cliente. */
    public Pedido crearPedido(Map<Integer, Integer> cantidadesPorLibroId) throws ApiException {
        ObjectNode cuerpo = api.json().createObjectNode();
        ArrayNode lineas = cuerpo.putArray("lineas");
        cantidadesPorLibroId.forEach((id, cantidad) -> lineas.addObject().put("libro_id", id).put("cantidad", cantidad));
        return Pedido.desde(api.post("/orders", cuerpo));
    }

    public List<Pedido> misPedidos() throws ApiException {
        return lista(api.get("/orders"), Pedido::desde);
    }

    public Pedido pedido(int id) throws ApiException {
        return Pedido.desde(api.get("/orders/" + id));
    }

    /** El dueño cancela su pedido mientras está pendiente (el stock vuelve). */
    public Pedido cancelarPedido(int id) throws ApiException {
        return Pedido.desde(api.post("/orders/" + id + "/cancel", null));
    }

    // --- pagos (simulados) ----------------------------------------------------------

    public Pago pagar(int pedidoId, BigDecimal monto, String metodo, String referencia) throws ApiException {
        ObjectNode cuerpo = api.json().createObjectNode()
                .put("pedido_id", pedidoId)
                .put("monto", monto.toPlainString())
                .put("metodo", metodo)
                .put("referencia", referencia);
        return Pago.desde(api.post("/payments", cuerpo));
    }

    public List<Pago> pagosDe(int pedidoId) throws ApiException {
        return lista(api.get("/payments?pedido_id=" + pedidoId), Pago::desde);
    }

    // --------------------------------------------------------------------------------

    private static <T> List<T> lista(JsonNode arreglo, Function<JsonNode, T> convertir) {
        List<T> salida = new ArrayList<>();
        if (arreglo != null && arreglo.isArray()) arreglo.forEach(n -> salida.add(convertir.apply(n)));
        return salida;
    }

    private static String url(String texto) {
        return URLEncoder.encode(texto, StandardCharsets.UTF_8);
    }
}

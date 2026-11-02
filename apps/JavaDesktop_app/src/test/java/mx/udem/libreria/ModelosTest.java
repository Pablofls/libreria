package mx.udem.libreria;

import com.fasterxml.jackson.databind.ObjectMapper;
import mx.udem.libreria.model.Libro;
import mx.udem.libreria.model.Pedido;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** JSON con la forma exacta que devuelven catálogo y pedidos. */
class ModelosTest {

    private final ObjectMapper json = new ObjectMapper();

    @Test
    void libroDelCatalogo() throws Exception {
        Libro l = Libro.desde(json.readTree("""
                {"isbn": "978-607-00-0001-1", "title": "Nubes", "authors": [{"name": "Ana", "order": 1,
                 "nationality": "Mexicana"}], "year": 2021, "genres": ["Técnico"], "price": "349.00",
                 "stock": 4, "format": "Pasta blanda", "synopsis": "Un libro sobre la nube.",
                 "images": [{"cover": false, "type": "image/png", "file": "a.png"},
                            {"cover": true, "type": "image/png", "file": "b.png"}], "concepts": []}"""));
        assertEquals("Nubes", l.titulo());
        assertEquals("Ana", l.autoresTexto());
        assertEquals(new BigDecimal("349.00"), l.precio());
        assertEquals("b.png", l.portada());
        assertEquals("Un libro sobre la nube.", l.sinopsis());
        assertTrue(l.disponible());
    }

    @Test
    void libroSinImagenNiSinopsis() throws Exception {
        Libro l = Libro.desde(json.readTree("""
                {"isbn": "1", "title": "T", "authors": [], "year": null, "genres": [], "price": 10,
                 "stock": 0, "format": "x", "images": [], "concepts": []}"""));
        assertNull(l.portada());
        assertNull(l.sinopsis());
        assertNull(l.anio());
        assertEquals("Autor desconocido", l.autoresTexto());
    }

    @Test
    void pedidoConLineasHistorialYCodigo() throws Exception {
        Pedido p = Pedido.desde(json.readTree("""
                {"id": 125, "usuario_id": 7, "estado": "pagado", "creado_en": "2026-10-30T18:05:00.123456-06:00",
                 "total": 698.0, "pagado": 698.0,
                 "lineas": [{"libro_id": 3, "titulo": "Nubes", "cantidad": 2, "precio_unitario": 349.0, "subtotal": 698.0}],
                 "historial": [{"estado": "pendiente", "cambiado_en": "2026-10-30T18:05:00-06:00", "cambiado_por": 7},
                               {"estado": "pagado", "cambiado_en": "2026-10-30T18:05:01-06:00", "cambiado_por": 7}]}"""));
        assertEquals(new BigDecimal("698.00"), p.total());
        assertEquals(2, p.lineas().get(0).cantidad());
        assertEquals(2, p.historial().size());
        assertEquals("LIB-MTY-2026-000125", p.codigoRastreo());
        assertTrue(p.rastreable());
    }
}

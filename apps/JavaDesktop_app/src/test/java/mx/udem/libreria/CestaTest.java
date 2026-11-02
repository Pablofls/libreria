package mx.udem.libreria;

import mx.udem.libreria.cesta.Cesta;
import mx.udem.libreria.model.Libro;
import mx.udem.libreria.model.LibroPedible;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class CestaTest {

    static Libro libro(String isbn, String precio, int stock) {
        return new Libro(isbn, "Libro " + isbn, List.of(), 2020, null, new BigDecimal(precio), stock,
                "Pasta blanda", List.of(), null);
    }

    @Test
    void agregarJuntaElMismoLibroYCalculaTotales() {
        Cesta c = new Cesta();
        c.agregar(libro("111", "199.90", 10), 1);
        c.agregar(libro("111", "199.90", 10), 2);
        c.agregar(libro("222", "50.00", 10), 1);
        assertEquals(2, c.items().size());
        assertEquals(4, c.unidades());
        assertEquals(new BigDecimal("649.70"), c.total());
    }

    @Test
    void cambiarCantidadYQuitar() {
        Cesta c = new Cesta();
        c.agregar(libro("111", "10.00", 10), 1);
        c.cambiarCantidad("111", 5);
        assertEquals(new BigDecimal("50.00"), c.total());
        c.cambiarCantidad("111", 0);
        assertTrue(c.vacia());
    }

    @Test
    void validarUsaPrecioYStockDelServicioDePedidos() {
        Cesta c = new Cesta();
        c.agregar(libro("111", "100.00", 10), 3);   // precio subió
        c.agregar(libro("222", "50.00", 10), 5);    // sólo quedan 2
        c.agregar(libro("333", "20.00", 10), 1);    // agotado
        c.agregar(libro("444", "20.00", 10), 1);    // ya no existe
        List<String> avisos = c.validar(List.of(
                new LibroPedible(1, "111", "Libro 111", new BigDecimal("120.00"), 10),
                new LibroPedible(2, "222", "Libro 222", new BigDecimal("50.00"), 2),
                new LibroPedible(3, "333", "Libro 333", new BigDecimal("20.00"), 0)));
        assertEquals(4, avisos.size());
        assertEquals(new BigDecimal("460.00"), c.total());   // 3×120 + 2×50
        assertEquals(Map.of(1, 3, 2, 2), c.lineasParaPedido());
    }

    @Test
    void sinValidarNoSeArmanLineas() {
        Cesta c = new Cesta();
        c.agregar(libro("111", "10.00", 10), 1);
        assertThrows(IllegalStateException.class, c::lineasParaPedido);
    }
}

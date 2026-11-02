package mx.udem.libreria.cesta;

import javafx.collections.FXCollections;
import javafx.collections.ObservableList;
import mx.udem.libreria.model.Dinero;
import mx.udem.libreria.model.Libro;
import mx.udem.libreria.model.LibroPedible;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * Cesta de compras en memoria. No se guarda en disco ni en ningún servicio:
 * dura lo que dura la sesión de la app. El precio que muestra es el del
 * catálogo hasta que {@link #validar} lo contrasta con el servicio de pedidos,
 * que es el que manda al crear el pedido.
 */
public final class Cesta {

    public static final int MAX_CANTIDAD = 1000;   // mismo tope que el servicio de pedidos

    /** Una línea de la cesta. Mutable sólo en cantidad y precio (tras validar). */
    public static final class Item {
        private final Libro libro;
        private int cantidad;
        private BigDecimal precio;
        private Integer libroId;   // id numérico; lo da /orders/books al validar

        Item(Libro libro, int cantidad) {
            this.libro = libro;
            this.cantidad = cantidad;
            this.precio = libro.precio();
        }

        public Libro libro() { return libro; }
        public int cantidad() { return cantidad; }
        public BigDecimal precio() { return precio; }
        public Integer libroId() { return libroId; }
        public BigDecimal subtotal() { return precio.multiply(BigDecimal.valueOf(cantidad)); }
    }

    private final ObservableList<Item> items = FXCollections.observableArrayList();

    public ObservableList<Item> items() { return items; }

    public void agregar(Libro libro, int cantidad) {
        if (cantidad < 1) throw new IllegalArgumentException("La cantidad debe ser al menos 1.");
        Optional<Item> existente = buscar(libro.isbn());
        if (existente.isPresent()) {
            cambiarCantidad(libro.isbn(), existente.get().cantidad + cantidad);
        } else {
            items.add(new Item(libro, Math.min(cantidad, MAX_CANTIDAD)));
        }
    }

    public void cambiarCantidad(String isbn, int cantidad) {
        if (cantidad < 1) {
            quitar(isbn);
            return;
        }
        buscar(isbn).ifPresent(item -> {
            item.cantidad = Math.min(cantidad, MAX_CANTIDAD);
            refrescar(item);
        });
    }

    public void quitar(String isbn) {
        items.removeIf(i -> i.libro.isbn().equals(isbn));
    }

    public void vaciar() { items.clear(); }

    public boolean vacia() { return items.isEmpty(); }

    public int unidades() { return items.stream().mapToInt(Item::cantidad).sum(); }

    public BigDecimal total() {
        return items.stream().map(Item::subtotal).reduce(BigDecimal.ZERO, BigDecimal::add);
    }

    private Optional<Item> buscar(String isbn) {
        return items.stream().filter(i -> i.libro.isbn().equals(isbn)).findFirst();
    }

    /** Fuerza a la lista observable a avisar que el item cambió. */
    private void refrescar(Item item) {
        int i = items.indexOf(item);
        if (i >= 0) items.set(i, item);
    }

    /**
     * Contrasta la cesta con los datos vigentes del servicio de pedidos: asigna
     * el id de cada libro, actualiza precios que cambiaron, y avisa de libros que
     * ya no existen o no tienen stock suficiente. Devuelve los avisos; vacío =
     * todo cuadra y se puede comprar.
     */
    public List<String> validar(List<LibroPedible> vigentes) {
        Map<String, LibroPedible> porIsbn = new LinkedHashMap<>();
        vigentes.forEach(v -> porIsbn.put(v.isbn(), v));
        List<String> avisos = new ArrayList<>();
        for (Item item : List.copyOf(items)) {
            LibroPedible v = porIsbn.get(item.libro.isbn());
            if (v == null) {
                avisos.add("«" + item.libro.titulo() + "» ya no está a la venta; se quitó de la cesta.");
                quitar(item.libro.isbn());
                continue;
            }
            item.libroId = v.id();
            if (v.precio().compareTo(item.precio) != 0) {
                avisos.add("«" + item.libro.titulo() + "» cambió de precio: " + Dinero.texto(item.precio)
                        + " → " + Dinero.texto(v.precio()) + ".");
                item.precio = v.precio();
            }
            if (v.stock() < item.cantidad) {
                if (v.stock() == 0) {
                    avisos.add("«" + item.libro.titulo() + "» está agotado; se quitó de la cesta.");
                    quitar(item.libro.isbn());
                    continue;
                }
                avisos.add("De «" + item.libro.titulo() + "» sólo quedan " + v.stock() + "; se ajustó la cantidad.");
                item.cantidad = v.stock();
            }
            refrescar(item);
        }
        return avisos;
    }

    /** Líneas para POST /orders: libro_id → cantidad. Requiere haber validado. */
    public Map<Integer, Integer> lineasParaPedido() {
        Map<Integer, Integer> lineas = new LinkedHashMap<>();
        for (Item item : items) {
            if (item.libroId == null) throw new IllegalStateException("Valida la cesta antes de crear el pedido.");
            lineas.merge(item.libroId, item.cantidad, Integer::sum);
        }
        return lineas;
    }
}

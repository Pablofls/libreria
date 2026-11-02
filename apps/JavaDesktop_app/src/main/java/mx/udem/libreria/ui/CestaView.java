package mx.udem.libreria.ui;

import javafx.collections.ListChangeListener;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.Node;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.ScrollPane;
import javafx.scene.control.Spinner;
import javafx.scene.layout.BorderPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.VBox;
import mx.udem.libreria.cesta.Cesta;
import mx.udem.libreria.model.Dinero;

/**
 * La cesta (en memoria): cantidades, quitar, precio por libro, subtotales y
 * total. "Confirmar compra" valida contra el servicio de pedidos y lanza el
 * flujo de compra simulada.
 */
public final class CestaView implements MainView.Seccion {

    private final Contexto ctx;
    private final BorderPane raiz = new BorderPane();
    private final VBox filas = new VBox(8);
    private final Label resumen = Ui.etiqueta("", "subtitulo");
    private final Label total = Ui.etiqueta("", "precio-grande");
    private final Button confirmar = new Button("Confirmar compra");
    private final Button vaciar = new Button("Vaciar cesta");

    public CestaView(Contexto ctx) {
        this.ctx = ctx;
        confirmar.getStyleClass().add("acento");
        confirmar.setOnAction(e -> new CompraFlujo(ctx).iniciar());
        vaciar.setOnAction(e -> {
            if (Ui.confirmar("Vaciar la cesta", "¿Quitar todos los libros de la cesta?")) ctx.cesta().vaciar();
        });
        ctx.cesta().items().addListener((ListChangeListener<Cesta.Item>) c -> pintar());

        ScrollPane scroll = new ScrollPane(filas);
        scroll.setFitToWidth(true);
        scroll.getStyleClass().add("sin-borde");
        HBox pie = new HBox(14, resumen, Ui.espacio(), Ui.etiqueta("Total", "seccion"), total, vaciar, confirmar);
        pie.setAlignment(Pos.CENTER_LEFT);
        pie.setPadding(new Insets(14, 0, 0, 0));
        pie.getStyleClass().add("pie");

        raiz.setTop(Ui.encabezado("Cesta de compras",
                "Precios del catálogo; se confirman con el servicio de pedidos antes de comprar"));
        raiz.setCenter(scroll);
        raiz.setBottom(pie);
        pintar();
    }

    private void pintar() {
        Cesta cesta = ctx.cesta();
        filas.getChildren().clear();
        if (cesta.vacia()) {
            Button ir = new Button("Ir al catálogo");
            ir.setOnAction(e -> ctx.irA(MainView.CATALOGO));
            filas.getChildren().addAll(Ui.etiqueta("Tu cesta está vacía.", "subtitulo"), ir);
        }
        for (Cesta.Item item : cesta.items()) filas.getChildren().add(fila(item));
        int u = cesta.unidades();
        resumen.setText(cesta.items().size() + " títulos · " + u + (u == 1 ? " libro" : " libros"));
        total.setText(Dinero.texto(cesta.total()));
        confirmar.setDisable(cesta.vacia());
        vaciar.setDisable(cesta.vacia());
    }

    private Node fila(Cesta.Item item) {
        String isbn = item.libro().isbn();
        Spinner<Integer> cantidad = new Spinner<>(1, Cesta.MAX_CANTIDAD, item.cantidad());
        cantidad.setEditable(true);
        cantidad.setPrefWidth(90);
        cantidad.valueProperty().addListener((o, viejo, nuevo) -> {
            if (nuevo != null && nuevo != item.cantidad()) ctx.cesta().cambiarCantidad(isbn, nuevo);
        });
        Button quitar = new Button("Quitar");
        quitar.setOnAction(e -> ctx.cesta().quitar(isbn));

        VBox datos = new VBox(3, Ui.etiqueta(item.libro().titulo(), "tarjeta-titulo"),
                Ui.etiqueta(item.libro().autoresTexto(), "tarjeta-autor"),
                Ui.etiqueta("ISBN " + isbn, "nota"));
        datos.setPrefWidth(360);
        Label precio = Ui.etiqueta(Dinero.texto(item.precio()) + " c/u", "texto");
        Label subtotal = Ui.etiqueta(Dinero.texto(item.subtotal()), "precio");
        subtotal.setMinWidth(110);
        HBox fila = new HBox(16, ctx.portadas().nodo(item.libro(), 56, 84), datos, Ui.espacio(), precio,
                cantidad, subtotal, quitar);
        fila.setAlignment(Pos.CENTER_LEFT);
        fila.setPadding(new Insets(10));
        fila.getStyleClass().add("tarjeta");
        return fila;
    }

    @Override
    public void alMostrar() { pintar(); }

    @Override
    public Node vista() { return raiz; }
}

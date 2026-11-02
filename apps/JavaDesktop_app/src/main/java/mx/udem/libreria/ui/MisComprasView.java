package mx.udem.libreria.ui;

import javafx.beans.property.SimpleStringProperty;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.Node;
import javafx.scene.control.Button;
import javafx.scene.control.ChoiceDialog;
import javafx.scene.control.Label;
import javafx.scene.control.ScrollPane;
import javafx.scene.control.SplitPane;
import javafx.scene.control.TableColumn;
import javafx.scene.control.TableView;
import javafx.scene.layout.BorderPane;
import javafx.scene.layout.GridPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.VBox;
import mx.udem.libreria.model.Dinero;
import mx.udem.libreria.model.Pago;
import mx.udem.libreria.model.Pedido;

import java.util.List;
import java.util.UUID;
import java.util.function.Function;

/**
 * "Mis compras": los pedidos del usuario autenticado (GET /orders; el servicio
 * filtra por el usuario del JWT) y, al elegir uno, su detalle (GET /orders/{id})
 * y sus pagos (GET /payments?pedido_id=). Los estados son los de los servicios.
 */
public final class MisComprasView implements MainView.Seccion {

    private final Contexto ctx;
    private final BorderPane raiz = new BorderPane();
    private final TableView<Pedido> tabla = new TableView<>();
    private final VBox detalle = new VBox(10);
    private final Label estado = Ui.etiqueta("", "nota");

    public MisComprasView(Contexto ctx) {
        this.ctx = ctx;
        tabla.getColumns().add(columna("Pedido", p -> "#" + p.id()));
        tabla.getColumns().add(columna("Fecha", p -> Ui.fecha(p.creadoEn())));
        tabla.getColumns().add(columna("Estado", Pedido::estado));
        tabla.getColumns().add(columna("Total", p -> Dinero.texto(p.total())));
        tabla.getColumns().add(columna("Pagado", p -> Dinero.texto(p.pagado())));
        tabla.getColumns().add(columna("Código de rastreo", Pedido::codigoRastreo));
        tabla.setColumnResizePolicy(TableView.CONSTRAINED_RESIZE_POLICY_FLEX_LAST_COLUMN);
        tabla.setPlaceholder(new Label("Aún no tienes compras."));
        tabla.getSelectionModel().selectedItemProperty().addListener((o, v, p) -> {
            if (p != null) cargarDetalle(p.id());
        });

        detalle.setPadding(new Insets(4, 4, 4, 14));
        detalle.getChildren().add(Ui.etiqueta("Selecciona un pedido para ver su detalle.", "subtitulo"));
        ScrollPane scrollDetalle = new ScrollPane(detalle);
        scrollDetalle.setFitToWidth(true);
        scrollDetalle.getStyleClass().add("sin-borde");

        SplitPane split = new SplitPane(tabla, scrollDetalle);
        split.setDividerPositions(0.55);

        Button actualizar = new Button("Actualizar");
        actualizar.setOnAction(e -> cargar());
        HBox barra = new HBox(10, actualizar, Ui.espacio(), estado);
        barra.setAlignment(Pos.CENTER_LEFT);
        barra.setPadding(new Insets(0, 0, 10, 0));

        raiz.setTop(new VBox(Ui.encabezado("Mis compras", "Tus pedidos, sus pagos y su seguimiento"), barra));
        raiz.setCenter(split);
    }

    private static TableColumn<Pedido, String> columna(String titulo, Function<Pedido, String> valor) {
        TableColumn<Pedido, String> c = new TableColumn<>(titulo);
        c.setCellValueFactory(d -> new SimpleStringProperty(valor.apply(d.getValue())));
        return c;
    }

    @Override
    public void alMostrar() { cargar(); }

    private void cargar() {
        estado.setText("Cargando…");
        Integer elegido = tabla.getSelectionModel().getSelectedItem() == null ? null
                : tabla.getSelectionModel().getSelectedItem().id();
        Ui.enFondo(ctx, () -> ctx.servicios().misPedidos(), pedidos -> {
            tabla.getItems().setAll(pedidos);
            estado.setText(pedidos.size() + (pedidos.size() == 1 ? " pedido" : " pedidos"));
            if (elegido != null) {
                pedidos.stream().filter(p -> p.id() == elegido).findFirst()
                        .ifPresent(p -> tabla.getSelectionModel().select(p));
            }
        }, err -> {
            estado.setText("");
            Ui.error(err);
        });
    }

    record Detalle(Pedido pedido, List<Pago> pagos) { }

    private void cargarDetalle(int id) {
        Ui.enFondo(ctx, () -> new Detalle(ctx.servicios().pedido(id), ctx.servicios().pagosDe(id)), this::pintar);
    }

    private void pintar(Detalle d) {
        Pedido p = d.pedido();
        detalle.getChildren().clear();
        detalle.getChildren().add(new HBox(10, Ui.etiqueta("Pedido #" + p.id(), "titulo"), Ui.pastilla(p.estado())));
        detalle.getChildren().add(Ui.etiqueta(Ui.fecha(p.creadoEn()), "nota"));

        detalle.getChildren().add(Ui.etiqueta("Libros", "seccion"));
        GridPane lineas = new GridPane();
        lineas.setHgap(14);
        lineas.setVgap(4);
        int r = 0;
        for (Pedido.Linea l : p.lineas()) {
            lineas.addRow(r++, new Label(l.titulo()), new Label(l.cantidad() + " × " + Dinero.texto(l.precioUnitario())),
                    Ui.etiqueta(Dinero.texto(l.subtotal()), "precio"));
        }
        lineas.addRow(r, Ui.etiqueta("Total", "seccion"), new Label("pagado " + Dinero.texto(p.pagado())),
                Ui.etiqueta(Dinero.texto(p.total()), "precio"));
        detalle.getChildren().add(lineas);

        detalle.getChildren().add(Ui.etiqueta("Pagos", "seccion"));
        if (d.pagos().isEmpty()) detalle.getChildren().add(Ui.etiqueta("Sin pagos registrados.", "nota"));
        for (Pago pg : d.pagos()) {
            detalle.getChildren().add(new HBox(10, new Label("#" + pg.id() + "  " + pg.metodo() + "  "
                    + Dinero.texto(pg.monto()) + (pg.referencia() != null ? "  ref. " + pg.referencia() : "")
                    + "  ·  " + Ui.fecha(pg.creadoEn())), Ui.pastilla(pg.estado())));
        }

        detalle.getChildren().add(Ui.etiqueta("Historial del pedido", "seccion"));
        for (Pedido.CambioEstado h : p.historial()) {
            detalle.getChildren().add(new Label("• " + h.estado() + "  —  " + Ui.fecha(h.cuando())));
        }

        detalle.getChildren().add(Ui.etiqueta("Código de rastreo", "seccion"));
        detalle.getChildren().add(Ui.etiqueta(p.codigoRastreo(), "codigo-rastreo"));

        HBox acciones = new HBox(8);
        if (p.rastreable()) {
            Button rastrear = new Button("Rastrear pedido");
            rastrear.getStyleClass().add("acento");
            rastrear.setOnAction(e -> ctx.rastrear(p.codigoRastreo()));
            acciones.getChildren().add(rastrear);
        } else if ("pendiente".equals(p.estado())) {
            Button pagar = new Button("Pagar (simulado)");
            pagar.getStyleClass().add("acento");
            pagar.setOnAction(e -> pagar(p));
            Button cancelar = new Button("Cancelar pedido");
            cancelar.setOnAction(e -> cancelar(p));
            acciones.getChildren().addAll(pagar, cancelar);
            detalle.getChildren().add(Ui.etiqueta("El envío se rastrea cuando el pedido está pagado.", "nota"));
        } else {
            detalle.getChildren().add(Ui.etiqueta("Este pedido no tiene un envío que rastrear.", "nota"));
        }
        detalle.getChildren().add(acciones);
    }

    private void pagar(Pedido p) {
        ChoiceDialog<String> elegir = new ChoiceDialog<>("tarjeta", "tarjeta", "transferencia", "efectivo");
        elegir.setHeaderText("Pagar " + Dinero.texto(p.total().subtract(p.pagado())) + " del pedido #" + p.id()
                + "\n(simulado: sin datos bancarios)");
        elegir.setContentText("Método");
        elegir.showAndWait().ifPresent(metodo -> Ui.enFondo(ctx,
                () -> ctx.servicios().pagar(p.id(), p.total().subtract(p.pagado()), metodo,
                        "SIM-" + UUID.randomUUID().toString().substring(0, 8).toUpperCase()),
                pago -> {
                    Ui.info("Pago " + pago.estado(), "El pedido quedó " + pago.pedidoEstado()
                            + ".\nCódigo de rastreo: " + p.codigoRastreo());
                    cargar();
                }));
    }

    private void cancelar(Pedido p) {
        if (!Ui.confirmar("Cancelar pedido #" + p.id(), "Los libros vuelven al inventario. ¿Continuar?")) return;
        Ui.enFondo(ctx, () -> ctx.servicios().cancelarPedido(p.id()), x -> cargar());
    }

    @Override
    public Node vista() { return raiz; }
}

package mx.udem.libreria.ui;

import javafx.geometry.Insets;
import javafx.scene.control.ButtonBar;
import javafx.scene.control.ButtonType;
import javafx.scene.control.ComboBox;
import javafx.scene.control.Dialog;
import javafx.scene.control.Label;
import javafx.scene.input.Clipboard;
import javafx.scene.input.ClipboardContent;
import javafx.scene.layout.GridPane;
import javafx.scene.layout.VBox;
import mx.udem.libreria.api.ApiException;
import mx.udem.libreria.cesta.Cesta;
import mx.udem.libreria.model.Dinero;
import mx.udem.libreria.model.Pago;
import mx.udem.libreria.model.Pedido;

import java.util.List;
import java.util.UUID;

/**
 * Compra simulada, paso a paso, con los servicios reales:
 *
 *  1. GET  /orders/books  → validar ids, precios y stock de la cesta
 *  2. el usuario revisa y elige un método de pago simulado
 *  3. POST /orders        → pedido 'pendiente' (el servidor pone los precios y descuenta stock)
 *  4. POST /payments      → pago 'aprobado' por el total; el pedido pasa a 'pagado'
 *  5. GET  /orders/{id} y GET /payments?pedido_id= → se muestra lo que dicen los servicios
 *  6. código de rastreo LIB-MTY-AAAA-NNNNNN del pedido real
 *
 * No se piden ni se envían datos bancarios: sólo el nombre del método.
 */
final class CompraFlujo {

    private static final List<String> METODOS = List.of("tarjeta", "transferencia", "efectivo");

    private final Contexto ctx;

    CompraFlujo(Contexto ctx) { this.ctx = ctx; }

    void iniciar() {
        Ui.enFondo(ctx, () -> ctx.servicios().librosParaPedir(), vigentes -> {
            List<String> avisos = ctx.cesta().validar(vigentes);
            if (ctx.cesta().vacia()) {
                Ui.info("La cesta quedó vacía", String.join("\n", avisos));
                return;
            }
            revisar(avisos);
        });
    }

    private void revisar(List<String> avisos) {
        Dialog<String> d = new Dialog<>();
        d.setTitle("Confirmar compra");
        d.setHeaderText("Revisa tu pedido");
        d.getDialogPane().getStylesheets().add(getClass().getResource("/css/tema.css").toExternalForm());
        ButtonType pagar = new ButtonType("Pagar (simulado)", ButtonBar.ButtonData.OK_DONE);
        d.getDialogPane().getButtonTypes().addAll(ButtonType.CANCEL, pagar);

        GridPane tabla = new GridPane();
        tabla.setHgap(18);
        tabla.setVgap(6);
        int r = 0;
        for (String h : List.of("Libro", "Precio", "Cant.", "Subtotal")) tabla.add(Ui.etiqueta(h, "seccion"), r++, 0);
        r = 1;
        for (Cesta.Item item : ctx.cesta().items()) {
            tabla.addRow(r++, new Label(item.libro().titulo()), new Label(Dinero.texto(item.precio())),
                    new Label(String.valueOf(item.cantidad())), new Label(Dinero.texto(item.subtotal())));
        }
        tabla.add(Ui.etiqueta("Total", "seccion"), 2, r);
        tabla.add(Ui.etiqueta(Dinero.texto(ctx.cesta().total()), "precio"), 3, r);

        ComboBox<String> metodo = new ComboBox<>();
        metodo.getItems().addAll(METODOS);
        String porOmision = ctx.api().config().metodoPago;
        metodo.setValue(METODOS.contains(porOmision) ? porOmision : METODOS.get(0));

        VBox cuerpo = new VBox(12);
        if (!avisos.isEmpty()) {
            cuerpo.getChildren().add(Ui.etiqueta("Se actualizó tu cesta con los datos vigentes:\n• "
                    + String.join("\n• ", avisos), "aviso"));
        }
        cuerpo.getChildren().addAll(tabla, new Label("Método de pago (simulado)"), metodo,
                Ui.etiqueta("Pago simulado: no se solicita ni se envía ningún dato bancario.", "nota"));
        cuerpo.setPadding(new Insets(8));
        cuerpo.setPrefWidth(560);
        d.getDialogPane().setContent(cuerpo);
        d.setResultConverter(b -> b == pagar ? metodo.getValue() : null);
        d.showAndWait().ifPresent(this::comprar);
    }

    record Resultado(Pedido pedido, Pago pago, List<Pago> pagos) { }

    private void comprar(String metodo) {
        var lineas = ctx.cesta().lineasParaPedido();
        String referencia = "SIM-" + UUID.randomUUID().toString().substring(0, 8).toUpperCase();
        int[] creado = {0};
        Ui.enFondo(ctx, () -> {
            Pedido pedido = ctx.servicios().crearPedido(lineas);
            creado[0] = pedido.id();
            Pago pago = ctx.servicios().pagar(pedido.id(), pedido.total(), metodo, referencia);
            return new Resultado(ctx.servicios().pedido(pedido.id()), pago, ctx.servicios().pagosDe(pedido.id()));
        }, res -> {
            ctx.cesta().vaciar();
            confirmacion(res);
        }, (ApiException err) -> {
            if (creado[0] > 0) {
                // El pedido existe pero el pago falló: queda pendiente y se puede pagar en Mis compras.
                ctx.cesta().vaciar();
                Ui.info("El pedido " + creado[0] + " se creó, pero el pago no se registró",
                        err.texto() + "\n\nQueda como pendiente: puedes pagarlo o cancelarlo en «Mis compras».");
            } else {
                Ui.error(err);
            }
        });
    }

    private void confirmacion(Resultado res) {
        Pedido p = res.pedido();
        String codigo = p.codigoRastreo();
        Dialog<ButtonType> d = new Dialog<>();
        d.setTitle("Compra confirmada");
        d.setHeaderText("¡Gracias por tu compra!");
        d.getDialogPane().getStylesheets().add(getClass().getResource("/css/tema.css").toExternalForm());
        ButtonType rastrear = new ButtonType("Rastrear pedido", ButtonBar.ButtonData.OK_DONE);
        ButtonType copiar = new ButtonType("Copiar código", ButtonBar.ButtonData.LEFT);
        d.getDialogPane().getButtonTypes().addAll(copiar, ButtonType.CLOSE, rastrear);

        GridPane g = new GridPane();
        g.setHgap(16);
        g.setVgap(8);
        int r = 0;
        g.addRow(r++, Ui.etiqueta("Pedido", "seccion"), new Label("#" + p.id() + "  ·  " + Ui.fecha(p.creadoEn())));
        g.addRow(r++, Ui.etiqueta("Estado del pedido", "seccion"), Ui.pastilla(p.estado()));
        g.addRow(r++, Ui.etiqueta("Pago", "seccion"), new Label("#" + res.pago().id() + "  ·  " + res.pago().metodo()
                + "  ·  " + Dinero.texto(res.pago().monto()) + "  ·  ref. " + res.pago().referencia()));
        g.addRow(r++, Ui.etiqueta("Estado del pago", "seccion"), Ui.pastilla(res.pago().estado()));
        g.addRow(r++, Ui.etiqueta("Total / pagado", "seccion"),
                new Label(Dinero.texto(p.total()) + " / " + Dinero.texto(p.pagado())));
        for (Pedido.Linea l : p.lineas()) {
            g.addRow(r++, new Label(""), new Label(l.cantidad() + " × " + l.titulo() + "  " + Dinero.texto(l.subtotal())));
        }
        Label cod = Ui.etiqueta(codigo, "codigo-rastreo");
        VBox cuerpo = new VBox(14, g, Ui.etiqueta("Código de rastreo", "seccion"), cod,
                Ui.etiqueta("Con este código puedes seguir la entrega en el mapa en cualquier momento.", "nota"));
        cuerpo.setPadding(new Insets(8));
        d.getDialogPane().setContent(cuerpo);

        d.getDialogPane().lookupButton(copiar).addEventFilter(javafx.event.ActionEvent.ACTION, e -> {
            ClipboardContent c = new ClipboardContent();
            c.putString(codigo);
            Clipboard.getSystemClipboard().setContent(c);
            e.consume();   // no cerrar el diálogo
        });
        d.showAndWait().filter(b -> b == rastrear).ifPresent(b -> ctx.rastrear(codigo));
    }
}

package mx.udem.libreria.ui;

import com.fasterxml.jackson.databind.JsonNode;
import javafx.application.Platform;
import javafx.concurrent.Worker;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.Node;
import javafx.scene.control.Button;
import javafx.scene.control.ComboBox;
import javafx.scene.control.Label;
import javafx.scene.control.ProgressBar;
import javafx.scene.control.TextField;
import javafx.scene.layout.BorderPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.VBox;
import javafx.scene.web.WebEngine;
import javafx.scene.web.WebView;
import mx.udem.libreria.model.Pedido;
import mx.udem.libreria.rastreo.CodigoRastreo;
import mx.udem.libreria.rastreo.RastreoClient;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Seguimiento de un pedido en el mapa de Monterrey.
 *
 * La app Java abre el WebSocket (RastreoClient) y, por cada mensaje, llama a
 * las funciones JavaScript del mapa Leaflet que vive en el WebView
 * (resources/mapa/mapa.html). El mapa no abre conexiones ni ve el JWT: sólo
 * dibuja lo que Java le pasa. No hay que recargar nada: cada segundo llega
 * una posición nueva y el vehículo avanza.
 */
public final class RastreoView implements MainView.Seccion {

    static final String[] ESTADOS = {"Pedido confirmado", "Preparando pedido", "Pedido enviado",
            "En ruta de entrega", "Entregado"};

    private final Contexto ctx;
    private final BorderPane raiz = new BorderPane();
    private final TextField codigo = new TextField();
    private final ComboBox<Pedido> misPedidos = new ComboBox<>();
    private final WebEngine motor;
    private final List<String> pendientes = new ArrayList<>();   // llamadas JS antes de que cargue el mapa
    private boolean mapaListo;
    private RastreoClient cliente;

    private final Label conexion = Ui.etiqueta("Sin rastreo activo", "conexion");
    private final Label titulo = Ui.etiqueta("—", "titulo");
    private final Label estadoGrande = Ui.etiqueta("Ingresa o elige un código", "estado-grande");
    private final List<Label> pasos = new ArrayList<>();
    private final ProgressBar progreso = new ProgressBar(0);
    private final Label posicion = Ui.etiqueta("—", "texto");
    private final Label velocidad = Ui.etiqueta("—", "texto");
    private final Label restante = Ui.etiqueta("—", "texto");
    private final Label eta = Ui.etiqueta("—", "texto");
    private final Label mensaje = Ui.etiqueta("", "mensaje-error");

    public RastreoView(Contexto ctx) {
        this.ctx = ctx;

        codigo.setPromptText("LIB-MTY-2026-000125");
        codigo.setPrefColumnCount(18);
        Button rastrear = new Button("Rastrear");
        rastrear.getStyleClass().add("acento");
        rastrear.setDefaultButton(true);
        rastrear.setOnAction(e -> rastrear(codigo.getText()));
        misPedidos.setPromptText("…o elige uno de tus pedidos pagados");
        misPedidos.setConverter(new javafx.util.StringConverter<>() {
            @Override public String toString(Pedido p) {
                return p == null ? "" : "#" + p.id() + "  " + p.codigoRastreo() + "  (" + p.estado() + ")";
            }
            @Override public Pedido fromString(String s) { return null; }
        });
        misPedidos.setOnAction(e -> {
            Pedido p = misPedidos.getValue();
            if (p != null) rastrear(p.codigoRastreo());
        });
        HBox barra = new HBox(8, new Label("Código"), codigo, rastrear, misPedidos, Ui.espacio(), conexion);
        barra.setAlignment(Pos.CENTER_LEFT);
        barra.setPadding(new Insets(0, 0, 10, 0));

        WebView web = new WebView();
        motor = web.getEngine();
        motor.getLoadWorker().stateProperty().addListener((o, v, s) -> {
            if (s == Worker.State.SUCCEEDED) {
                mapaListo = true;
                pendientes.forEach(motor::executeScript);
                pendientes.clear();
            }
        });
        motor.load(getClass().getResource("/mapa/mapa.html").toExternalForm());

        VBox lineaTiempo = new VBox(6);
        for (String e : ESTADOS) {
            Label l = Ui.etiqueta("○  " + e, "paso");
            pasos.add(l);
            lineaTiempo.getChildren().add(l);
        }
        progreso.setMaxWidth(Double.MAX_VALUE);
        VBox panel = new VBox(10, titulo, estadoGrande, lineaTiempo, progreso,
                Ui.etiqueta("Ubicación actual", "seccion"), posicion,
                Ui.etiqueta("Velocidad", "seccion"), velocidad,
                Ui.etiqueta("Distancia restante", "seccion"), restante,
                Ui.etiqueta("Llegada estimada", "seccion"), eta, mensaje);
        panel.setPadding(new Insets(14));
        panel.setPrefWidth(270);
        panel.getStyleClass().add("tarjeta");

        BorderPane centro = new BorderPane(web);
        centro.setRight(panel);
        BorderPane.setMargin(panel, new Insets(0, 0, 0, 12));
        raiz.setTop(new VBox(Ui.encabezado("Rastrear pedido",
                "Ubicación del vehículo de reparto en tiempo real, por WebSocket"), barra));
        raiz.setCenter(centro);
    }

    @Override
    public void alMostrar() {
        Ui.enFondo(ctx, () -> ctx.servicios().misPedidos(),
                pedidos -> misPedidos.getItems().setAll(pedidos.stream().filter(Pedido::rastreable).toList()),
                err -> { });
    }

    /** Abre (o cambia a) el seguimiento de un código. */
    public void rastrear(String texto) {
        var normal = CodigoRastreo.normalizar(texto);
        if (normal.isEmpty()) {
            mensaje.setText("Código inválido. Formato: LIB-MTY-AAAA-NNNNNN");
            return;
        }
        String cod = normal.get();
        codigo.setText(cod);
        detener();
        reiniciarPanel(cod);
        js("limpiar()");
        RastreoClient[] este = new RastreoClient[1];
        este[0] = new RastreoClient(ctx.api(), cod, new RastreoClient.Oyente() {
            // Un cliente anterior (otro código) que aún habla no pinta encima del actual.
            private boolean vigente() { return cliente == este[0]; }

            @Override public void mensaje(JsonNode m) { Platform.runLater(() -> { if (vigente()) recibir(m); }); }

            @Override public void error(String motivo) {
                Platform.runLater(() -> {
                    if (!vigente()) return;
                    mensaje.setText(motivo);
                    estadoGrande.setText("No disponible");
                    js("aviso(" + ctx.api().json().valueToTree(motivo) + ")");
                });
            }

            @Override public void estadoConexion(boolean conectado, String detalle) {
                Platform.runLater(() -> {
                    if (!vigente()) return;
                    conexion.setText((conectado ? "● " : "○ ") + detalle);
                    conexion.getStyleClass().removeAll("conectado", "desconectado");
                    conexion.getStyleClass().add(conectado ? "conectado" : "desconectado");
                });
            }
        });
        cliente = este[0];
        cliente.conectar();
    }

    private void reiniciarPanel(String cod) {
        titulo.setText(cod);
        estadoGrande.setText("Conectando…");
        mensaje.setText("");
        progreso.setProgress(0);
        for (Label l : posicionYDatos()) l.setText("—");
        for (int i = 0; i < pasos.size(); i++) {
            pasos.get(i).setText("○  " + ESTADOS[i]);
            pasos.get(i).getStyleClass().removeAll("hecho", "actual");
        }
    }

    private List<Label> posicionYDatos() { return List.of(posicion, velocidad, restante, eta); }

    private void recibir(JsonNode m) {
        String tipo = m.path("type").asText();
        if ("snapshot".equals(tipo)) {
            titulo.setText(m.path("code").asText() + "  ·  pedido #" + m.path("pedido_id").asInt());
            js("iniciar(" + m + ")");
        } else if ("update".equals(tipo)) {
            js("actualizar(" + m + ")");
        } else {
            return;
        }
        String estado = m.path("estado").asText();
        int paso = m.path("paso").asInt(1);
        estadoGrande.setText(estado);
        for (int i = 0; i < pasos.size(); i++) {
            Label l = pasos.get(i);
            l.getStyleClass().removeAll("hecho", "actual");
            boolean hecho = i < paso - 1 || (i == paso - 1 && paso == ESTADOS.length);
            l.setText((hecho ? "✓  " : i == paso - 1 ? "●  " : "○  ") + ESTADOS[i]);
            l.getStyleClass().add(hecho ? "hecho" : i == paso - 1 ? "actual" : "pendiente");
        }
        progreso.setProgress(m.path("progreso").asDouble());
        posicion.setText(String.format(Locale.ROOT, "%.5f, %.5f", m.path("lat").asDouble(), m.path("lon").asDouble()));
        velocidad.setText(String.format(Locale.ROOT, "%.0f km/h  ·  rumbo %d°  ·  simulación ×%.0f",
                m.path("speed").asDouble(), m.path("heading").asInt(), m.path("aceleracion").asDouble(1)));
        restante.setText(String.format(Locale.ROOT, "%.2f km de %.2f km", m.path("restante_m").asDouble() / 1000,
                m.path("distancia_m").asDouble() / 1000));
        int s = m.path("eta_s").asInt();
        eta.setText("Entregado".equals(estado) ? "Entregado ✓" : String.format("%d:%02d min", s / 60, s % 60));
    }

    private void js(String llamada) {
        if (mapaListo) motor.executeScript(llamada);
        else pendientes.add(llamada);
    }

    /** Corta el WebSocket activo (al cambiar de código, salir o cerrar la app). */
    public void detener() {
        if (cliente != null) {
            cliente.cerrar();
            cliente = null;
        }
    }

    @Override
    public Node vista() { return raiz; }
}

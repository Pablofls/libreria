package mx.udem.libreria.ui;

import javafx.collections.ListChangeListener;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.Node;
import javafx.scene.Parent;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.layout.BorderPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.VBox;
import mx.udem.libreria.api.Sesion;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.Supplier;

/**
 * Ventana principal tras el login: barra superior con el usuario autenticado y
 * la cesta, menú lateral y el contenido de la sección elegida.
 */
public final class MainView {

    public static final String CATALOGO = "Catálogo";
    public static final String CESTA = "Cesta";
    public static final String COMPRAS = "Mis compras";
    public static final String RASTREO = "Rastrear pedido";
    public static final String PERFIL = "Mi perfil";
    public static final String SOAP = "SOAP (admin)";

    private final Contexto ctx;
    private final BorderPane raiz = new BorderPane();
    private final Map<String, Button> botones = new LinkedHashMap<>();
    private final Map<String, Supplier<Seccion>> fabricas = new LinkedHashMap<>();
    private final Map<String, Seccion> creadas = new LinkedHashMap<>();
    private RastreoView rastreo;

    /** Una sección del menú: su nodo y qué hacer al mostrarla. */
    public interface Seccion {
        Node vista();

        default void alMostrar() { }
    }

    public MainView(Contexto ctx, Runnable alSalir) {
        this.ctx = ctx;
        Sesion s = ctx.api().sesion();

        fabricas.put(CATALOGO, () -> new CatalogoView(ctx));
        fabricas.put(CESTA, () -> new CestaView(ctx));
        fabricas.put(COMPRAS, () -> new MisComprasView(ctx));
        fabricas.put(RASTREO, () -> rastreo = new RastreoView(ctx));
        fabricas.put(PERFIL, () -> new PerfilView(ctx));
        if (s.esAdmin()) fabricas.put(SOAP, () -> new SoapView(ctx));

        // Barra superior
        Label usuario = Ui.etiqueta(s.nombre() + "  ·  " + s.rol() + "  ·  id " + s.usuarioId(), "usuario");
        Button cesta = new Button();
        cesta.getStyleClass().add("boton-cesta");
        Runnable contar = () -> cesta.setText("Cesta (" + ctx.cesta().unidades() + ")");
        contar.run();
        ctx.cesta().items().addListener((ListChangeListener<Object>) c -> contar.run());
        cesta.setOnAction(e -> mostrar(CESTA));
        Button salir = new Button("Cerrar sesión");
        salir.setOnAction(e -> Ui.enFondo(ctx, () -> {
            ctx.api().cerrarSesion();
            return true;
        }, ok -> alSalir.run()));
        HBox barra = new HBox(14, Ui.etiqueta("Librería Online", "marca"), Ui.espacio(), usuario, cesta, salir);
        barra.setAlignment(Pos.CENTER_LEFT);
        barra.setPadding(new Insets(10, 18, 10, 18));
        barra.getStyleClass().add("barra");

        // Menú lateral
        VBox menu = new VBox(4);
        menu.setPadding(new Insets(16, 10, 16, 10));
        menu.getStyleClass().add("menu");
        for (String nombre : fabricas.keySet()) {
            Button b = new Button(nombre);
            b.setMaxWidth(Double.MAX_VALUE);
            b.getStyleClass().add("menu-boton");
            b.setOnAction(e -> mostrar(nombre));
            botones.put(nombre, b);
            menu.getChildren().add(b);
        }
        menu.getChildren().addAll(Ui.espacio(), Ui.etiqueta("REST + JWT · WebSocket · SOAP", "nota-menu"));

        raiz.setTop(barra);
        raiz.setLeft(menu);
        ctx.navegacion(this::mostrar, codigo -> {
            mostrar(RASTREO);
            rastreo.rastrear(codigo);
        });
        mostrar(CATALOGO);
    }

    public void mostrar(String nombre) {
        Seccion sec = creadas.computeIfAbsent(nombre, n -> fabricas.get(n).get());
        botones.forEach((n, b) -> b.getStyleClass().remove("activo"));
        botones.get(nombre).getStyleClass().add("activo");
        BorderPane contenido = new BorderPane(sec.vista());
        contenido.setPadding(new Insets(18, 22, 18, 22));
        contenido.getStyleClass().add("contenido");
        raiz.setCenter(contenido);
        sec.alMostrar();
    }

    /** Al salir o cerrar la ventana: cortar el WebSocket del rastreo. */
    public void detener() {
        if (rastreo != null) rastreo.detener();
    }

    public Parent vista() { return raiz; }
}

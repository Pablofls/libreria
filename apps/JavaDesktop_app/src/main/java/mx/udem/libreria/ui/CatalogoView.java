package mx.udem.libreria.ui;

import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.Node;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.ScrollPane;
import javafx.scene.control.TextField;
import javafx.scene.layout.BorderPane;
import javafx.scene.layout.FlowPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Priority;
import javafx.scene.layout.VBox;
import mx.udem.libreria.model.Autor;
import mx.udem.libreria.model.Dinero;
import mx.udem.libreria.model.Libro;

import java.util.List;

/**
 * Catálogo en cuadrícula, del microservicio de catálogo (GET /books y
 * GET /books/search?titulo=). Las fichas de autor vienen de authors.
 */
public final class CatalogoView implements MainView.Seccion {

    private final Contexto ctx;
    private final BorderPane raiz = new BorderPane();
    private final FlowPane cuadricula = new FlowPane(16, 16);
    private final Label estado = Ui.etiqueta("", "nota");
    private final TextField buscar = new TextField();
    private List<Autor> autores;   // se piden una vez, para las fichas
    private boolean cargado;

    public CatalogoView(Contexto ctx) {
        this.ctx = ctx;
        buscar.setPromptText("Buscar por título…");
        buscar.setPrefColumnCount(26);
        Button bBuscar = new Button("Buscar");
        bBuscar.setDefaultButton(true);
        bBuscar.setOnAction(e -> cargar(buscar.getText().trim()));
        Button bTodos = new Button("Ver todo");
        bTodos.setOnAction(e -> {
            buscar.clear();
            cargar("");
        });
        HBox filtros = new HBox(8, buscar, bBuscar, bTodos, Ui.espacio(), estado);
        filtros.setAlignment(Pos.CENTER_LEFT);
        filtros.setPadding(new Insets(0, 0, 12, 0));

        cuadricula.setPadding(new Insets(4));
        ScrollPane scroll = new ScrollPane(cuadricula);
        scroll.setFitToWidth(true);
        scroll.getStyleClass().add("sin-borde");

        raiz.setTop(new VBox(Ui.encabezado("Catálogo", "Libros de la librería, con su portada, precio y disponibilidad"), filtros));
        raiz.setCenter(scroll);
    }

    @Override
    public void alMostrar() {
        if (!cargado) cargar("");
    }

    private void cargar(String titulo) {
        cargado = true;
        estado.setText("Cargando…");
        Ui.enFondo(ctx, () -> titulo.isEmpty() ? ctx.servicios().catalogo() : ctx.servicios().buscarPorTitulo(titulo),
                libros -> {
                    cuadricula.getChildren().setAll(libros.stream().map(this::tarjeta).toList());
                    estado.setText(libros.size() + (libros.size() == 1 ? " libro" : " libros"));
                    if (libros.isEmpty()) cuadricula.getChildren().add(Ui.etiqueta("No hay libros con ese título.", "subtitulo"));
                },
                err -> {
                    estado.setText("");
                    Ui.error(err);
                });
    }

    private Node tarjeta(Libro libro) {
        Label titulo = Ui.etiqueta(libro.titulo(), "tarjeta-titulo");
        titulo.setMaxWidth(170);
        titulo.setMinHeight(38);
        Label autores = Ui.etiqueta(libro.autoresTexto(), "tarjeta-autor");
        autores.setMaxWidth(170);
        Label precio = Ui.etiqueta(Dinero.texto(libro.precio()), "precio");
        Label disp = Ui.etiqueta(libro.disponible() ? "Disponible (" + libro.stock() + ")" : "Agotado",
                libro.disponible() ? "disponible" : "agotado");

        Button ver = new Button("Detalle");
        ver.setOnAction(e -> detalle(libro));
        Button agregar = new Button("Agregar");
        agregar.getStyleClass().add("acento");
        agregar.setDisable(!libro.disponible());
        agregar.setOnAction(e -> agregar(libro));
        HBox acciones = new HBox(6, ver, agregar);

        Node portada = ctx.portadas().nodo(libro, 170, 250);
        portada.setOnMouseClicked(e -> detalle(libro));
        VBox tarjeta = new VBox(6, portada, titulo, autores, new HBox(8, precio, Ui.espacio(), disp), acciones);
        tarjeta.getStyleClass().addAll("tarjeta", "tarjeta-libro");
        tarjeta.setPadding(new Insets(10));
        tarjeta.setPrefWidth(192);
        VBox.setVgrow(titulo, Priority.NEVER);
        return tarjeta;
    }

    private void agregar(Libro libro) {
        ctx.cesta().agregar(libro, 1);
        estado.setText("«" + libro.titulo() + "» se agregó a la cesta");
    }

    private void detalle(Libro resumen) {
        // Ficha fresca del libro y la lista de autores para sus biografías.
        Ui.enFondo(ctx, () -> {
            Libro libro = ctx.servicios().libro(resumen.isbn());
            if (autores == null) autores = ctx.servicios().autores();
            return libro;
        }, libro -> new DetalleLibroDialog(ctx, libro, autores).showAndWait());
    }

    @Override
    public Node vista() { return raiz; }
}

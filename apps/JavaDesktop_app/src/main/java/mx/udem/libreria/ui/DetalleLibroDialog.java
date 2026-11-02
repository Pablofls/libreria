package mx.udem.libreria.ui;

import javafx.geometry.Insets;
import javafx.scene.control.Button;
import javafx.scene.control.ButtonType;
import javafx.scene.control.Dialog;
import javafx.scene.control.Label;
import javafx.scene.control.ScrollPane;
import javafx.scene.control.Spinner;
import javafx.scene.layout.HBox;
import javafx.scene.layout.VBox;
import mx.udem.libreria.model.Autor;
import mx.udem.libreria.model.Dinero;
import mx.udem.libreria.model.Libro;

import java.util.List;
import java.util.Optional;

/**
 * Ficha de un libro: portada, autores (con nacionalidad, biografía y otros
 * libros, del microservicio authors), sinopsis, precio, ISBN y stock.
 */
final class DetalleLibroDialog extends Dialog<Void> {

    DetalleLibroDialog(Contexto ctx, Libro libro, List<Autor> autores) {
        setTitle(libro.titulo());
        getDialogPane().getButtonTypes().add(ButtonType.CLOSE);
        getDialogPane().getStylesheets().add(getClass().getResource("/css/tema.css").toExternalForm());

        VBox datos = new VBox(8,
                Ui.etiqueta(libro.titulo(), "titulo"),
                Ui.etiqueta(libro.autoresTexto(), "tarjeta-autor"),
                Ui.etiqueta(Dinero.texto(libro.precio()), "precio-grande"),
                Ui.etiqueta(libro.disponible() ? "Disponible: " + libro.stock() + " en existencia" : "Agotado",
                        libro.disponible() ? "disponible" : "agotado"),
                Ui.etiqueta("ISBN " + libro.isbn()
                        + (libro.anio() != null ? "  ·  " + libro.anio() : "")
                        + (libro.formato().isBlank() ? "" : "  ·  " + libro.formato())
                        + (libro.generos().isEmpty() ? "" : "  ·  " + String.join(", ", libro.generos())), "nota"),
                Ui.etiqueta("Descripción", "seccion"),
                Ui.etiqueta(libro.sinopsis() == null || libro.sinopsis().isBlank()
                        ? "Este libro no tiene sinopsis registrada en el catálogo." : libro.sinopsis(), "texto"));

        Spinner<Integer> cantidad = new Spinner<>(1, Math.max(1, Math.min(libro.stock(), 1000)), 1);
        cantidad.setPrefWidth(80);
        Button agregar = new Button("Agregar a la cesta");
        agregar.getStyleClass().add("acento");
        agregar.setDisable(!libro.disponible());
        Label hecho = Ui.etiqueta("", "nota");
        agregar.setOnAction(e -> {
            ctx.cesta().agregar(libro, cantidad.getValue());
            hecho.setText("Agregado ✓");
        });
        datos.getChildren().add(new HBox(8, new Label("Cantidad"), cantidad, agregar, hecho));

        datos.getChildren().add(Ui.etiqueta("Sobre " + (libro.autores().size() == 1 ? "el autor" : "los autores"), "seccion"));
        for (Libro.AutorRef ref : libro.autores()) {
            Optional<Autor> ficha = autores.stream().filter(a -> a.nombre().equalsIgnoreCase(ref.nombre())).findFirst();
            VBox caja = new VBox(4, Ui.etiqueta(ref.nombre()
                    + (ref.nacionalidad() != null ? "  (" + ref.nacionalidad() + ")" : ""), "tarjeta-titulo"));
            ficha.ifPresent(a -> {
                caja.getChildren().add(Ui.etiqueta(a.biografia() == null ? "Sin biografía registrada." : a.biografia(), "texto"));
                Label otros = Ui.etiqueta("Libros en la librería: " + a.libros(), "nota");
                caja.getChildren().add(otros);
                Ui.enFondo(ctx, () -> ctx.servicios().librosDeAutor(a.id()),
                        titulos -> otros.setText("Libros en la librería: " + String.join(" · ", titulos)), err -> { });
            });
            caja.getStyleClass().add("caja-autor");
            caja.setPadding(new Insets(8));
            datos.getChildren().add(caja);
        }

        datos.setPrefWidth(440);
        ScrollPane scroll = new ScrollPane(datos);
        scroll.setFitToWidth(true);
        scroll.setPrefHeight(520);
        scroll.getStyleClass().add("sin-borde");
        HBox cuerpo = new HBox(20, ctx.portadas().nodo(libro, 240, 360), scroll);
        cuerpo.setPadding(new Insets(10));
        getDialogPane().setContent(cuerpo);
    }
}

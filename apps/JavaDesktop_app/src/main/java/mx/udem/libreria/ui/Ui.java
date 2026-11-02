package mx.udem.libreria.ui;

import javafx.application.Platform;
import javafx.geometry.Insets;
import javafx.scene.Node;
import javafx.scene.control.Alert;
import javafx.scene.control.ButtonType;
import javafx.scene.control.Label;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Priority;
import javafx.scene.layout.Region;
import javafx.scene.layout.VBox;
import mx.udem.libreria.api.ApiException;
import mx.udem.libreria.api.SesionPerdida;

import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.Locale;
import java.util.concurrent.Callable;
import java.util.function.Consumer;

/** Utilidades de interfaz: trabajo en segundo plano, diálogos y etiquetas. */
public final class Ui {

    private static final DateTimeFormatter FECHA = DateTimeFormatter
            .ofPattern("d MMM yyyy, HH:mm", Locale.forLanguageTag("es-MX"));

    private Ui() { }

    /**
     * Ejecuta una llamada de red fuera del hilo de JavaFX y vuelve a él con el
     * resultado. Una sesión perdida ya la maneja ApiClient (regresa al login),
     * así que aquí no se muestra otro diálogo encima.
     */
    public static <T> void enFondo(Contexto ctx, Callable<T> trabajo, Consumer<T> alTerminar, Consumer<ApiException> alFallar) {
        ctx.hilos().submit(() -> {
            try {
                T resultado = trabajo.call();
                Platform.runLater(() -> alTerminar.accept(resultado));
            } catch (SesionPerdida e) {
                // ApiClient ya regresó al login con su aviso.
            } catch (ApiException e) {
                Platform.runLater(() -> alFallar.accept(e));
            } catch (Exception e) {
                Platform.runLater(() -> alFallar.accept(new ApiException(0, "Error inesperado: " + e.getClass().getSimpleName())));
            }
        });
    }

    public static <T> void enFondo(Contexto ctx, Callable<T> trabajo, Consumer<T> alTerminar) {
        enFondo(ctx, trabajo, alTerminar, Ui::error);
    }

    public static void error(ApiException e) {
        Alert a = new Alert(Alert.AlertType.ERROR, e.texto(), ButtonType.OK);
        a.setHeaderText(e.estado() == 0 ? "Sin conexión" : "No se pudo completar la operación");
        a.showAndWait();
    }

    public static void info(String titulo, String texto) {
        Alert a = new Alert(Alert.AlertType.INFORMATION, texto, ButtonType.OK);
        a.setHeaderText(titulo);
        a.showAndWait();
    }

    public static boolean confirmar(String titulo, String texto) {
        Alert a = new Alert(Alert.AlertType.CONFIRMATION, texto, ButtonType.CANCEL, ButtonType.OK);
        a.setHeaderText(titulo);
        return a.showAndWait().filter(b -> b == ButtonType.OK).isPresent();
    }

    public static Label etiqueta(String texto, String... clases) {
        Label l = new Label(texto);
        l.getStyleClass().addAll(clases);
        l.setWrapText(true);
        return l;
    }

    public static Region espacio() {
        Region r = new Region();
        HBox.setHgrow(r, Priority.ALWAYS);
        VBox.setVgrow(r, Priority.ALWAYS);
        return r;
    }

    /** Encabezado de sección: título grande y subtítulo. */
    public static VBox encabezado(String titulo, String subtitulo) {
        VBox v = new VBox(2, etiqueta(titulo, "titulo"), etiqueta(subtitulo, "subtitulo"));
        v.setPadding(new Insets(0, 0, 12, 0));
        return v;
    }

    /** Pastilla de color para estados (pagado, pendiente…). */
    public static Label pastilla(String texto) {
        Label l = new Label(texto);
        l.getStyleClass().addAll("pastilla", "estado-" + texto.toLowerCase(Locale.ROOT).replace(' ', '-'));
        return l;
    }

    public static String fecha(OffsetDateTime f) {
        return f == null ? "—" : f.atZoneSameInstant(ZoneId.systemDefault()).format(FECHA);
    }

    public static Node tarjeta(Node... hijos) {
        VBox v = new VBox(8, hijos);
        v.getStyleClass().add("tarjeta");
        v.setPadding(new Insets(14));
        return v;
    }
}

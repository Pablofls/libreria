package mx.udem.libreria.ui;

import javafx.application.Platform;
import javafx.geometry.Pos;
import javafx.scene.control.Label;
import javafx.scene.image.Image;
import javafx.scene.image.ImageView;
import javafx.scene.layout.StackPane;
import javafx.scene.paint.Color;
import javafx.scene.shape.Rectangle;
import mx.udem.libreria.api.ApiClient;
import mx.udem.libreria.model.Libro;

import java.io.ByteArrayInputStream;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;

/**
 * Portadas de los libros, descargadas de https://VM/uploads/&lt;archivo&gt; (nginx
 * las sirve desde uploads/ del monolito) y guardadas en memoria. Si el libro no
 * tiene imagen o la descarga falla se ve la portada genérica "Portada no
 * disponible", dibujada aquí mismo.
 */
public final class Portadas {

    private static final String[] COLORES = {"#6b4f3a", "#3f5d54", "#7b3f4a", "#4a4e69", "#8a6a3b", "#355c7d"};

    private final ApiClient api;
    private final ExecutorService hilos;
    private final Map<String, Image> cache = new ConcurrentHashMap<>();

    Portadas(ApiClient api, ExecutorService hilos) {
        this.api = api;
        this.hilos = hilos;
    }

    /** Nodo de portada de ancho×alto; se rellena cuando llega la imagen. */
    public StackPane nodo(Libro libro, double ancho, double alto) {
        StackPane caja = new StackPane(generica(libro, ancho, alto));
        caja.setMinSize(ancho, alto);
        caja.setMaxSize(ancho, alto);
        caja.getStyleClass().add("portada");
        String archivo = libro.portada();
        if (archivo == null || !archivo.matches("[0-9a-fA-F-]{36}\\.(png|jpe?g|webp)")) return caja;
        Image enCache = cache.get(archivo);
        if (enCache != null) {
            caja.getChildren().setAll(vista(enCache, ancho, alto));
            return caja;
        }
        hilos.submit(() -> {
            try {
                Image img = new Image(new ByteArrayInputStream(api.descargar("/uploads/" + archivo)));
                if (img.isError()) return;   // p. ej. webp, que JavaFX no decodifica
                cache.put(archivo, img);
                Platform.runLater(() -> caja.getChildren().setAll(vista(img, ancho, alto)));
            } catch (Exception ignorada) {
                // Se queda la portada genérica.
            }
        });
        return caja;
    }

    private static ImageView vista(Image img, double ancho, double alto) {
        ImageView v = new ImageView(img);
        v.setFitWidth(ancho);
        v.setFitHeight(alto);
        v.setPreserveRatio(false);
        v.setSmooth(true);
        return v;
    }

    /** Portada genérica: color según el ISBN, título y la leyenda. */
    private static StackPane generica(Libro libro, double ancho, double alto) {
        Rectangle fondo = new Rectangle(ancho, alto,
                Color.web(COLORES[Math.floorMod(libro.isbn().hashCode(), COLORES.length)]));
        Label titulo = new Label(libro.titulo());
        titulo.setWrapText(true);
        titulo.setMaxWidth(ancho - 16);
        titulo.getStyleClass().add("portada-titulo");
        Label leyenda = new Label("Portada no disponible");
        leyenda.getStyleClass().add("portada-leyenda");
        StackPane p = new StackPane(fondo, titulo, leyenda);
        StackPane.setAlignment(leyenda, Pos.BOTTOM_CENTER);
        return p;
    }
}

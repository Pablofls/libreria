package mx.udem.libreria;

import javafx.application.Application;
import javafx.application.Platform;
import javafx.scene.Scene;
import javafx.stage.Stage;
import mx.udem.libreria.api.ApiClient;
import mx.udem.libreria.config.Config;
import mx.udem.libreria.ui.Contexto;
import mx.udem.libreria.ui.LoginView;
import mx.udem.libreria.ui.MainView;

/**
 * Librería Online — cliente de escritorio JavaFX.
 *
 * Consume los microservicios REST de la VM (login, users, catálogo, authors,
 * pedidos, pagos), el servicio SOAP y el rastreo GPS por WebSocket. No conoce
 * PostgreSQL: no hay ni una cadena de conexión en esta app.
 */
public class App extends Application {

    private Stage ventana;
    private Contexto ctx;
    private MainView principal;

    @Override
    public void start(Stage ventana) {
        this.ventana = ventana;
        ApiClient api = new ApiClient(Config.cargar());
        ctx = new Contexto(api);
        // Token vencido o revocado sin posibilidad de renovar: de vuelta al login.
        api.alPerderSesion(() -> Platform.runLater(() ->
                mostrarLogin("Tu sesión venció o fue cerrada. Vuelve a iniciar sesión.")));

        ventana.setTitle("Librería Online");
        ventana.setMinWidth(1000);
        ventana.setMinHeight(680);
        mostrarLogin(null);
        ventana.show();
    }

    private void mostrarLogin(String aviso) {
        if (principal != null) {
            principal.detener();
            principal = null;
        }
        ctx.cesta().vaciar();
        LoginView login = new LoginView(ctx, this::mostrarPrincipal);
        if (aviso != null) login.aviso(aviso);
        poner(new Scene(login.vista(), 1180, 760));
    }

    private void mostrarPrincipal() {
        principal = new MainView(ctx, () -> mostrarLogin(null));
        poner(new Scene(principal.vista(), 1180, 760));
    }

    private void poner(Scene escena) {
        escena.getStylesheets().add(getClass().getResource("/css/tema.css").toExternalForm());
        ventana.setScene(escena);
    }

    @Override
    public void stop() {
        if (principal != null) principal.detener();
        ctx.cerrar();
    }

    public static void main(String[] args) {
        launch(args);
    }
}

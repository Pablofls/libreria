package mx.udem.libreria.ui;

import javafx.geometry.Insets;
import javafx.scene.Node;
import javafx.scene.control.Label;
import javafx.scene.layout.GridPane;
import javafx.scene.layout.VBox;
import mx.udem.libreria.api.Sesion;

import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;

/**
 * Perfil del usuario autenticado, del microservicio users (GET /users/{id}).
 * Un lector sólo puede consultar su propia cuenta: el id sale del JWT.
 */
public final class PerfilView implements MainView.Seccion {

    private final Contexto ctx;
    private final VBox raiz = new VBox(12);
    private final GridPane datos = new GridPane();

    public PerfilView(Contexto ctx) {
        this.ctx = ctx;
        datos.setHgap(18);
        datos.setVgap(8);
        raiz.getChildren().addAll(Ui.encabezado("Mi perfil", "Datos de tu cuenta según el servicio de usuarios"),
                Ui.tarjeta(datos), sesion());
    }

    @Override
    public void alMostrar() {
        Ui.enFondo(ctx, () -> ctx.servicios().perfil(), u -> {
            datos.getChildren().clear();
            int r = 0;
            datos.addRow(r++, Ui.etiqueta("Nombre", "seccion"), new Label(u.nombreCompleto()));
            datos.addRow(r++, Ui.etiqueta("Correo", "seccion"), new Label(u.email()));
            datos.addRow(r++, Ui.etiqueta("Rol", "seccion"), new Label(u.rol()));
            datos.addRow(r++, Ui.etiqueta("Id de usuario", "seccion"), new Label(String.valueOf(u.id())));
            datos.addRow(r++, Ui.etiqueta("Cuenta", "seccion"), Ui.pastilla(u.activo() ? "activa" : "inactiva"));
            datos.addRow(r, Ui.etiqueta("Alta", "seccion"), new Label(Ui.fecha(u.creadoEn())));
        });
    }

    /** Lo que la app sabe del JWT (sin mostrar el token). */
    private Node sesion() {
        Sesion s = ctx.api().sesion();
        DateTimeFormatter f = DateTimeFormatter.ofPattern("HH:mm:ss").withZone(ZoneId.systemDefault());
        Label vence = new Label();
        Runnable pintar = () -> {
            Sesion actual = ctx.api().sesion();
            if (actual != null) vence.setText(f.format(actual.expira()) + "  (se renueva solo con el refresh token)");
        };
        pintar.run();
        GridPane g = new GridPane();
        g.setHgap(18);
        g.setVgap(8);
        g.addRow(0, Ui.etiqueta("Autenticación", "seccion"), new Label("JWT HS256 emitido por el servicio login"));
        g.addRow(1, Ui.etiqueta("El token vence a las", "seccion"), vence);
        g.addRow(2, Ui.etiqueta("Consultado", "seccion"), new Label(f.format(Instant.now())));
        g.setPadding(new Insets(4));
        raiz.sceneProperty().addListener((o, v, n) -> pintar.run());
        return Ui.tarjeta(Ui.etiqueta("Sesión", "tarjeta-titulo"), g,
                Ui.etiqueta("Cada petición protegida envía Authorization: Bearer <token>. "
                        + "Si el token vence o se revoca, la app pide iniciar sesión de nuevo.", "nota"));
    }

    @Override
    public Node vista() { return raiz; }
}

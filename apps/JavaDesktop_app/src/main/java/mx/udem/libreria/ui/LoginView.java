package mx.udem.libreria.ui;

import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.Parent;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.PasswordField;
import javafx.scene.control.TextField;
import javafx.scene.layout.StackPane;
import javafx.scene.layout.VBox;
import mx.udem.libreria.api.ApiException;

/**
 * Inicio de sesión contra el microservicio login (POST /login). La contraseña
 * sólo pasa por memoria: no se guarda ni se registra en ningún log.
 */
public final class LoginView {

    private final Contexto ctx;
    private final Runnable alEntrar;
    private final Label mensaje = Ui.etiqueta("", "mensaje-error");
    private final StackPane raiz;

    public LoginView(Contexto ctx, Runnable alEntrar) {
        this.ctx = ctx;
        this.alEntrar = alEntrar;

        TextField correo = new TextField();
        correo.setPromptText("correo@ejemplo.com");
        PasswordField clave = new PasswordField();
        clave.setPromptText("Contraseña");
        Button entrar = new Button("Iniciar sesión");
        entrar.getStyleClass().add("acento");
        entrar.setDefaultButton(true);
        entrar.setMaxWidth(Double.MAX_VALUE);

        entrar.setOnAction(e -> {
            String email = correo.getText().trim();
            if (email.isEmpty() || clave.getText().isEmpty()) {
                mensaje.setText("Escribe tu correo y tu contraseña.");
                return;
            }
            entrar.setDisable(true);
            mensaje.setText("");
            String password = clave.getText();
            Ui.enFondo(ctx, () -> ctx.api().iniciarSesion(email, password), sesion -> {
                clave.clear();
                alEntrar.run();
            }, (ApiException err) -> {
                entrar.setDisable(false);
                clave.clear();
                mensaje.setText(err.getMessage());
            });
        });

        VBox caja = new VBox(10,
                Ui.etiqueta("Librería Online", "marca-grande"),
                Ui.etiqueta("Inicia sesión para comprar y rastrear tus pedidos", "subtitulo"),
                new Label("Correo"), correo, new Label("Contraseña"), clave, entrar, mensaje,
                Ui.etiqueta("Servidor: " + ctx.api().config().apiBase, "nota"));
        caja.getStyleClass().add("tarjeta");
        caja.setPadding(new Insets(28));
        caja.setMaxWidth(380);
        caja.setMaxHeight(VBox.USE_PREF_SIZE);

        raiz = new StackPane(caja);
        raiz.getStyleClass().add("fondo-login");
        StackPane.setAlignment(caja, Pos.CENTER);
    }

    public void aviso(String texto) { mensaje.setText(texto); }

    public Parent vista() { return raiz; }
}

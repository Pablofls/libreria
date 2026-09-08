import gui.AppWindow;
import javax.swing.SwingUtilities;
import javax.swing.UIManager;

/**
 * Punto de entrada de la aplicación.
 * Inicializa el Look & Feel y lanza la ventana en el hilo de eventos de Swing.
 */
public class Main {

    public static void main(String[] args) {
        try {
            UIManager.setLookAndFeel(UIManager.getSystemLookAndFeelClassName());
        } catch (Exception ignored) {
            // Si no está disponible el LnF del sistema, Swing usa el predeterminado
        }

        SwingUtilities.invokeLater(() -> new AppWindow().setVisible(true));
    }
}

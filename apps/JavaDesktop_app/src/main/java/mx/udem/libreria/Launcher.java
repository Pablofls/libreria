package mx.udem.libreria;

/**
 * Punto de entrada que no extiende Application: permite arrancar la app con
 * `java -cp …` sin module-path (JavaFX lo exige para la clase principal).
 */
public final class Launcher {
    public static void main(String[] args) {
        App.main(args);
    }
}

package classifier;

/**
 * Excepción comprobada (checked) lanzada cuando el texto de entrada
 * no cumple las condiciones mínimas para ser clasificado.
 *
 * Al ser checked, obliga al llamador (la GUI) a manejarla explícitamente,
 * separando los errores de validación de los errores inesperados del sistema.
 */
public class ClassificationException extends Exception {

    public ClassificationException(String message) {
        super(message);
    }
}

package mx.udem.libreria.config;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Properties;

/**
 * Configuración de la app: a dónde conectarse y en qué certificado confiar.
 *
 * Orden: variable de entorno → config.properties (en la carpeta desde donde se
 * arranca) → valor por omisión. Aquí no hay ninguna credencial: el usuario las
 * escribe en la pantalla de login y sólo viven en memoria.
 */
public final class Config {

    /** nginx en la VM de GCP (443). Todo pasa por aquí: REST, portadas, WebSocket y SOAP. */
    public final String apiBase;
    /** Copia del certificado autofirmado de la VM (~/libreria-api.crt). */
    public final Path caCert;
    /** Método de pago simulado por omisión. */
    public final String metodoPago;

    private Config(String apiBase, Path caCert, String metodoPago) {
        this.apiBase = apiBase.replaceAll("/+$", "");
        this.caCert = caCert;
        this.metodoPago = metodoPago;
    }

    public static Config cargar() {
        Properties archivo = new Properties();
        Path ruta = Path.of("config.properties");
        if (Files.isRegularFile(ruta)) {
            try (InputStream in = Files.newInputStream(ruta)) {
                archivo.load(in);
            } catch (IOException ignorada) {
                // Sin archivo legible se sigue con entorno y valores por omisión.
            }
        }
        String base = valor("API_BASE", archivo, "https://34.51.108.167");
        String cert = valor("CA_CERT", archivo, "~/libreria-api.crt");
        if (cert.startsWith("~")) {
            cert = System.getProperty("user.home") + cert.substring(1);
        }
        return new Config(base, cert.isBlank() ? null : Path.of(cert),
                valor("METODO_PAGO", archivo, "tarjeta"));
    }

    private static String valor(String clave, Properties archivo, String defecto) {
        String env = System.getenv(clave);
        if (env != null && !env.isBlank()) return env.trim();
        return archivo.getProperty(clave, defecto).trim();
    }

    /** URL WebSocket equivalente a la base HTTP (https → wss). */
    public String wsBase() {
        return apiBase.replaceFirst("^http", "ws");
    }
}

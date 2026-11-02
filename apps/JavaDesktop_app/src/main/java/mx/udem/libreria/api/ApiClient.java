package mx.udem.libreria.api;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import mx.udem.libreria.config.Config;

import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManagerFactory;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.security.KeyStore;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

/**
 * Cliente HTTP único de la aplicación: todas las llamadas REST pasan por aquí.
 *
 *  - HTTPS contra nginx, confiando SÓLO en el certificado de la VM (CA_CERT) y en
 *    los de sistema; nunca se desactiva la verificación.
 *  - Las rutas protegidas llevan siempre  Authorization: Bearer <JWT>.
 *  - Antes de que el JWT venza (20 min) se renueva con /token/refresh, que
 *    devuelve un refresh nuevo (rotación, un solo uso). Si un servicio responde
 *    401 se intenta UNA renovación y un reintento; si tampoco, la sesión se dio
 *    por perdida y se avisa a la interfaz para volver al login.
 *  - login y catálogo hablan XML por omisión: a esas rutas se les añade
 *    ?format=json. Los demás servicios son sólo JSON.
 */
public final class ApiClient {

    private static final int MARGEN_RENOVACION_S = 60;
    private static final Duration TIMEOUT = Duration.ofSeconds(20);

    private final Config config;
    private final HttpClient http;
    private final SSLContext ssl;
    private final ObjectMapper json = new ObjectMapper();
    private final Object cerrojo = new Object();
    private volatile Sesion sesion;
    private volatile Runnable alPerderSesion = () -> { };

    public ApiClient(Config config) {
        this.config = config;
        this.ssl = contextoSsl(config);
        this.http = HttpClient.newBuilder()
                .sslContext(ssl)
                .connectTimeout(Duration.ofSeconds(10))
                .followRedirects(HttpClient.Redirect.NEVER)
                .build();
    }

    /** SSLContext que confía en los certificados del sistema MÁS el de la VM. */
    static SSLContext contextoSsl(Config config) {
        try {
            if (config.caCert == null || !Files.isRegularFile(config.caCert)) {
                return SSLContext.getDefault();
            }
            KeyStore almacen = KeyStore.getInstance(KeyStore.getDefaultType());
            almacen.load(null, null);
            // Certificados del sistema, para que también funcione con un dominio real.
            TrustManagerFactory sistema = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
            sistema.init((KeyStore) null);
            int i = 0;
            for (var tm : sistema.getTrustManagers()) {
                if (tm instanceof javax.net.ssl.X509TrustManager x) {
                    for (X509Certificate c : x.getAcceptedIssuers()) almacen.setCertificateEntry("sistema-" + i++, c);
                }
            }
            try (InputStream in = Files.newInputStream(config.caCert)) {
                X509Certificate vm = (X509Certificate) CertificateFactory.getInstance("X.509").generateCertificate(in);
                almacen.setCertificateEntry("libreria-vm", vm);
            }
            TrustManagerFactory tmf = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
            tmf.init(almacen);
            SSLContext ctx = SSLContext.getInstance("TLS");
            ctx.init(null, tmf.getTrustManagers(), null);
            return ctx;
        } catch (Exception e) {
            throw new IllegalStateException("No se pudo leer el certificado " + config.caCert, e);
        }
    }

    public Config config() { return config; }
    public HttpClient http() { return http; }
    public ObjectMapper json() { return json; }
    public Sesion sesion() { return sesion; }

    public void alPerderSesion(Runnable accion) { this.alPerderSesion = accion; }

    // --- Sesión ----------------------------------------------------------------

    public Sesion iniciarSesion(String email, String password) throws ApiException {
        ObjectNode cuerpo = json.createObjectNode().put("email", email).put("password", password);
        Respuesta r = enviar("POST", "/login", cuerpo, null);
        if (r.estado != 200 || !r.datos.hasNonNull("token")) throw error(r);
        synchronized (cerrojo) {
            sesion = new Sesion(r.datos);
        }
        return sesion;
    }

    /** Revoca JWT y refresh en el servidor. Si no se puede, la sesión NO se olvida. */
    public void cerrarSesion() throws ApiException {
        Sesion s = sesion;
        if (s == null) return;
        ObjectNode cuerpo = json.createObjectNode().put("refresh_token", s.refreshToken());
        Respuesta r = enviar("POST", "/logout", cuerpo, s.token());
        if (r.estado != 200) throw error(r);
        sesion = null;
    }

    /** Sólo local: para cuando el servidor ya dio la sesión por perdida. */
    public void olvidarSesion() { sesion = null; }

    /** true si hay sesión válida tras renovar; false si ya no existe. */
    boolean renovar() throws ApiException {
        synchronized (cerrojo) {
            Sesion s = sesion;
            if (s == null || s.refreshToken() == null) return false;
            ObjectNode cuerpo = json.createObjectNode().put("refresh_token", s.refreshToken());
            Respuesta r = enviar("POST", "/token/refresh", cuerpo, null);
            if (r.estado == 200 && r.datos.hasNonNull("token")) {
                sesion = new Sesion(r.datos);
                return true;
            }
            if (r.estado == 401) {
                sesion = null;
                return false;
            }
            throw error(r);
        }
    }

    /** JWT vigente, renovándolo si le queda menos de un minuto. */
    public String tokenVigente() throws ApiException {
        Sesion s = sesion;
        if (s == null) throw perdida();
        if (s.segundosRestantes() < MARGEN_RENOVACION_S && !renovar()) throw perdida();
        return sesion.token();
    }

    private ApiException perdida() {
        sesion = null;
        alPerderSesion.run();
        return new SesionPerdida();
    }

    // --- Peticiones -------------------------------------------------------------

    public JsonNode get(String ruta) throws ApiException { return peticion("GET", ruta, null, true); }

    public JsonNode getPublico(String ruta) throws ApiException { return peticion("GET", ruta, null, false); }

    public JsonNode post(String ruta, JsonNode cuerpo) throws ApiException { return peticion("POST", ruta, cuerpo, true); }

    public JsonNode peticion(String metodo, String ruta, JsonNode cuerpo, boolean autenticada) throws ApiException {
        String token = autenticada ? tokenVigente() : null;
        Respuesta r = enviar(metodo, ruta, cuerpo, token);
        if (r.estado == 401 && autenticada) {
            // El token pudo vencer o revocarse en el camino: una renovación y un reintento.
            if (!renovar()) throw perdida();
            r = enviar(metodo, ruta, cuerpo, sesion.token());
            if (r.estado == 401) throw perdida();
        }
        if (r.estado >= 400) throw error(r);
        return r.datos;
    }

    /** Bytes de una imagen (portadas en /uploads/…), sin autenticación. */
    public byte[] descargar(String ruta) throws ApiException {
        try {
            HttpRequest req = HttpRequest.newBuilder(URI.create(config.apiBase + ruta))
                    .timeout(TIMEOUT).header("Accept", "image/*").GET().build();
            HttpResponse<byte[]> resp = http.send(req, HttpResponse.BodyHandlers.ofByteArray());
            if (resp.statusCode() != 200) throw new ApiException(resp.statusCode(), null);
            return resp.body();
        } catch (ApiException e) {
            throw e;
        } catch (Exception e) {
            throw new ApiException(0, null);
        }
    }

    record Respuesta(int estado, JsonNode datos) { }

    static boolean necesitaFormato(String ruta) {
        for (String p : List.of("/login", "/logout", "/token", "/session", "/books", "/concepts")) {
            if (ruta.startsWith(p)) return true;
        }
        return false;
    }

    private Respuesta enviar(String metodo, String ruta, JsonNode cuerpo, String token) throws ApiException {
        if (necesitaFormato(ruta) && !ruta.contains("format=")) {
            ruta += (ruta.contains("?") ? "&" : "?") + "format=json";
        }
        try {
            HttpRequest.Builder b = HttpRequest.newBuilder(URI.create(config.apiBase + ruta))
                    .timeout(TIMEOUT)
                    .header("Accept", "application/json");
            if (token != null) b.header("Authorization", "Bearer " + token);
            if (cuerpo != null) {
                b.header("Content-Type", "application/json");
                b.method(metodo, HttpRequest.BodyPublishers.ofString(json.writeValueAsString(cuerpo)));
            } else {
                b.method(metodo, HttpRequest.BodyPublishers.noBody());
            }
            HttpResponse<String> resp = http.send(b.build(), HttpResponse.BodyHandlers.ofString());
            JsonNode datos;
            try {
                datos = resp.body() == null || resp.body().isBlank()
                        ? json.createObjectNode() : json.readTree(resp.body());
            } catch (Exception noJson) {
                datos = json.createObjectNode();   // p. ej. un 502 en HTML de nginx
            }
            return new Respuesta(resp.statusCode(), datos);
        } catch (java.io.IOException | InterruptedException e) {
            if (e instanceof InterruptedException) Thread.currentThread().interrupt();
            throw new ApiException(0, null);
        }
    }

    private ApiException error(Respuesta r) {
        String mensaje = r.datos.path("mensaje").asText(r.datos.path("message").asText(null));
        List<String> detalles = new ArrayList<>();
        JsonNode d = r.datos.has("detalles") ? r.datos.get("detalles") : r.datos.path("details");
        if (d.isArray()) d.forEach(x -> detalles.add(x.asText()));
        return new ApiException(r.estado, mensaje, detalles);
    }

    /** Para WebSocket y SOAP: mismo SSLContext que las llamadas REST. */
    public SSLContext ssl() { return ssl; }
}

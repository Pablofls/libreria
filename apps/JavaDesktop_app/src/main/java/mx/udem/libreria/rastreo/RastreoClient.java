package mx.udem.libreria.rastreo;

import com.fasterxml.jackson.databind.JsonNode;
import mx.udem.libreria.api.ApiClient;
import mx.udem.libreria.api.ApiException;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.WebSocket;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * Cliente WebSocket del rastreo, dentro de la app Java (java.net.http.WebSocket).
 *
 *   wss://<VM>/track/ws?code=LIB-MTY-2026-000125
 *   Authorization: Bearer <JWT>
 *
 * nginx lo reenvía al microservicio GPS (Flask + flask-sock, 5900), que valida
 * el JWT y la propiedad del pedido con el servicio de pedidos y transmite la
 * posición del vehículo cada segundo. El JWT viaja en la cabecera, nunca en la
 * URL (las URLs acaban en logs) ni dentro del mapa.
 *
 * Si la conexión se cae (red, reinicio del servicio) se reconecta sola; el
 * primer mensaje tras reconectar es un snapshot con todo el recorrido, así que
 * el mapa se repone sin perder nada. Un error del servidor (código ajeno,
 * sesión vencida) NO se reintenta.
 */
public final class RastreoClient {

    /** Lo que recibe la interfaz; se llama desde hilos de red. */
    public interface Oyente {
        void mensaje(JsonNode mensaje);

        void error(String motivo);

        void estadoConexion(boolean conectado, String detalle);
    }

    private static final long REINTENTO_S = 3;

    private final ApiClient api;
    private final String codigo;
    private final Oyente oyente;
    private final ScheduledExecutorService reloj = Executors.newSingleThreadScheduledExecutor(r -> {
        Thread t = new Thread(r, "rastreo-reconexion");
        t.setDaemon(true);
        return t;
    });
    private volatile WebSocket ws;
    private volatile boolean cerrado;
    private volatile boolean errorDelServidor;

    public RastreoClient(ApiClient api, String codigo, Oyente oyente) {
        this.api = api;
        this.codigo = codigo;
        this.oyente = oyente;
    }

    public void conectar() {
        if (cerrado) return;
        String token;
        try {
            token = api.tokenVigente();
        } catch (ApiException e) {
            oyente.error(e.getMessage());
            return;
        }
        URI uri = URI.create(api.config().wsBase() + "/track/ws?code="
                + URLEncoder.encode(codigo, StandardCharsets.UTF_8));
        oyente.estadoConexion(false, "Conectando…");
        api.http().newWebSocketBuilder()
                .header("Authorization", "Bearer " + token)
                .connectTimeout(Duration.ofSeconds(10))
                .buildAsync(uri, new Escucha())
                .whenComplete((socket, falla) -> {
                    if (falla != null) {
                        oyente.estadoConexion(false, "Sin conexión con el servidor de rastreo; reintentando…");
                        reintentar();
                    } else {
                        ws = socket;
                        oyente.estadoConexion(true, "Conectado por WebSocket");
                    }
                });
    }

    public void cerrar() {
        cerrado = true;
        WebSocket s = ws;
        if (s != null) s.sendClose(WebSocket.NORMAL_CLOSURE, "adios");
        reloj.shutdownNow();
    }

    private void reintentar() {
        if (cerrado || errorDelServidor) return;
        reloj.schedule(this::conectar, REINTENTO_S, TimeUnit.SECONDS);
    }

    private final class Escucha implements WebSocket.Listener {
        private final StringBuilder parcial = new StringBuilder();

        @Override
        public CompletionStage<?> onText(WebSocket socket, CharSequence datos, boolean ultimo) {
            parcial.append(datos);
            if (ultimo) {
                String texto = parcial.toString();
                parcial.setLength(0);
                try {
                    JsonNode m = api.json().readTree(texto);
                    if ("error".equals(m.path("type").asText())) {
                        errorDelServidor = true;
                        oyente.error(m.path("message").asText("Error del servidor de rastreo."));
                    } else {
                        oyente.mensaje(m);
                    }
                } catch (Exception ignorado) {
                    // Un mensaje que no es JSON no se dibuja.
                }
            }
            socket.request(1);
            return null;
        }

        @Override
        public CompletionStage<?> onClose(WebSocket socket, int estado, String motivo) {
            ws = null;
            if (!cerrado && !errorDelServidor) {
                oyente.estadoConexion(false, "Conexión cerrada; reintentando…");
                reintentar();
            } else {
                oyente.estadoConexion(false, "Desconectado");
            }
            return null;
        }

        @Override
        public void onError(WebSocket socket, Throwable error) {
            ws = null;
            if (!cerrado && !errorDelServidor) {
                oyente.estadoConexion(false, "Se perdió la conexión; reintentando…");
                reintentar();
            }
        }
    }
}

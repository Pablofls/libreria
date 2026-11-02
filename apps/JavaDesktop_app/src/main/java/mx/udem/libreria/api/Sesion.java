package mx.udem.libreria.api;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Base64;

/**
 * La sesión autenticada: JWT, refresh token y usuario. Sólo vive en memoria;
 * nada se escribe en disco.
 *
 * Los claims se leen SIN verificar la firma: aquí sólo sirven para saber cuándo
 * vence el token y renovarlo a tiempo. Quien decide si el token vale es cada
 * microservicio, que sí verifica firma, emisor, expiración y revocación.
 */
public final class Sesion {

    private static final ObjectMapper JSON = new ObjectMapper();

    private final String token;
    private final String refreshToken;
    private final Instant expira;
    private final int usuarioId;
    private final int roleId;
    private final String rol;
    private final String email;
    private final String nombre;

    Sesion(JsonNode respuestaLogin) {
        this.token = respuestaLogin.path("token").asText();
        this.refreshToken = respuestaLogin.path("refresh_token").asText(null);
        JsonNode usuario = respuestaLogin.path("usuario");
        JsonNode claims = claims(token);
        this.expira = Instant.ofEpochSecond(claims.path("exp").asLong(
                Instant.now().getEpochSecond() + respuestaLogin.path("expira_en").asLong(1200)));
        this.usuarioId = claims.path("user_id").asInt(usuario.path("id").asInt());
        this.roleId = claims.path("role_id").asInt(2);
        this.rol = claims.path("rol").asText(usuario.path("rol").asText("lector"));
        this.email = usuario.path("email").asText(claims.path("email").asText(""));
        String completo = usuario.path("nombre_completo").asText("");
        this.nombre = completo.isBlank() ? usuario.path("nombre").asText(email) : completo;
    }

    /** Payload del JWT (segunda parte, base64url). Sin verificar: ver la nota de la clase. */
    static JsonNode claims(String jwt) {
        try {
            String[] partes = jwt.split("\\.");
            byte[] crudo = Base64.getUrlDecoder().decode(partes[1]);
            return JSON.readTree(new String(crudo, StandardCharsets.UTF_8));
        } catch (Exception e) {
            return JSON.createObjectNode();
        }
    }

    public String token() { return token; }
    public String refreshToken() { return refreshToken; }
    public Instant expira() { return expira; }
    public int usuarioId() { return usuarioId; }
    public String rol() { return rol; }
    public String email() { return email; }
    public String nombre() { return nombre; }

    /** admin = role_id 1 (mapa ROLES_ID del servicio login). */
    public boolean esAdmin() { return roleId == 1 || "admin".equals(rol); }

    public long segundosRestantes() {
        return expira.getEpochSecond() - Instant.now().getEpochSecond();
    }
}

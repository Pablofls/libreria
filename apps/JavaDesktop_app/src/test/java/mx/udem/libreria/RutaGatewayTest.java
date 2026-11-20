package mx.udem.libreria;

import mx.udem.libreria.api.ApiClient;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

import static org.junit.jupiter.api.Assertions.assertEquals;

/** Misma tabla que deploy/nginx-api-tls.conf (API Gateway, rutas /api/*). */
class RutaGatewayTest {

    @ParameterizedTest
    @CsvSource({
            "/login?format=json,          /api/login?format=json",
            "/logout?format=json,         /api/login/logout?format=json",
            "/token/refresh?format=json,  /api/login/token/refresh?format=json",
            "/books?format=json,          /api/books?format=json",
            "/books/search?titulo=x,      /api/books/search?titulo=x",
            "/authors/3/books,            /api/autores/3/books",
            "/orders/books,               /api/pedidos/books",
            "/orders/7/cancel,            /api/pedidos/7/cancel",
            "/payments?pedido_id=7,       /api/pagos?pedido_id=7",
            "/users/2,                    /api/users/2",
            // Fuera de la tabla del gateway: tal cual.
            "/uploads/a.png,              /uploads/a.png",
            "/soap,                       /soap",
            "/track/ws?code=X,            /track/ws?code=X",
            "/health/login,               /health/login",
            "/booksx,                     /booksx",
    })
    void traduceAlPrefijoDelGateway(String propia, String esperada) {
        assertEquals(esperada, ApiClient.rutaGateway(propia));
    }
}

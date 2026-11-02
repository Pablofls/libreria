package mx.udem.libreria;

import mx.udem.libreria.rastreo.CodigoRastreo;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Mismas reglas que gps/microservice/entregas.py (parsear_codigo / codigo_para). */
class CodigoRastreoTest {

    @Test
    void formatoDelEnunciado() {
        assertEquals("LIB-MTY-2026-000125", CodigoRastreo.formatear(125, 2026));
    }

    @Test
    void idaYVuelta() {
        var p = CodigoRastreo.parsear("LIB-MTY-2026-000125").orElseThrow();
        assertEquals(2026, p.anio());
        assertEquals(125, p.pedidoId());
    }

    @Test
    void normalizaMinusculasYEspacios() {
        assertEquals("LIB-MTY-2026-000125", CodigoRastreo.normalizar("  lib-mty-2026-000125 ").orElseThrow());
    }

    @ParameterizedTest
    @ValueSource(strings = {"", "LIB-MTY-2026-125", "LIB-GDL-2026-000125", "LIB-MTY-2026-000000",
            "LIB-MTY-2026-000125; DROP", "../orders/1"})
    void rechazaCodigosInvalidos(String malo) {
        assertTrue(CodigoRastreo.parsear(malo).isEmpty());
    }

    @Test
    void idFueraDeRango() {
        assertThrows(IllegalArgumentException.class, () -> CodigoRastreo.formatear(0, 2026));
        assertThrows(IllegalArgumentException.class, () -> CodigoRastreo.formatear(1_000_000, 2026));
    }
}

package mx.udem.libreria.api;

/**
 * La sesión ya no se puede usar ni renovar (token vencido, revocado o refresh
 * agotado). ApiClient ya avisó a la interfaz, que vuelve al login: quien la
 * reciba no debe mostrar otro diálogo.
 */
public final class SesionPerdida extends ApiException {
    SesionPerdida() {
        super(401, null);
    }
}

package soap;

import java.util.Map;

/**
 * Un SOAP Fault ya traducido a algo que se le puede mostrar a una persona.
 *
 * El codigo del contrato es estable y es lo que la aplicacion programa; el
 * mensaje es para el usuario y puede cambiar sin romper a nadie. La GUI nunca
 * muestra el faultstring crudo que envia el servidor.
 */
public class SoapFault extends Exception {

    /** Codigos que NO son fallas: para quien estrena la aplicacion son el
     *  estado normal, y pintarlos de rojo asusta sin motivo. */
    private static final java.util.Set<String> ESPERADOS =
            java.util.Set.of("CLASIFICADOR_INEXISTENTE");

    private static final Map<String, String> MENSAJES = Map.ofEntries(
        Map.entry("CLASIFICACION_DUPLICADA",
                  "Ya clasificaste ese concepto antes. Elige otro de la lista."),
        Map.entry("CONCEPTO_INEXISTENTE",
                  "Ese concepto ya no esta disponible. Actualiza la lista."),
        Map.entry("LIBRO_INEXISTENTE",
                  "El libro asociado ya no esta en el catalogo. Actualiza la lista."),
        Map.entry("MODELO_INVALIDO",
                  "Selecciona uno de los cuatro modelos de la lista."),
        Map.entry("DATO_INVALIDO",
                  "Revisa los datos capturados: hay un campo incompleto o mal escrito."),
        Map.entry("CLASIFICADOR_INEXISTENTE",
                  "Todavia no tienes clasificaciones registradas con ese correo."),
        Map.entry("NO_AUTORIZADO",
                  "No tienes permiso para esta operacion."),
        Map.entry("XML_INVALIDO",
                  "La aplicacion envio una peticion mal formada. Reporta este error."),
        Map.entry("OPERACION_DESCONOCIDA",
                  "Esta version de la aplicacion no coincide con el servidor. Actualizala."),
        Map.entry("ERROR_SERVIDOR",
                  "El servicio no esta disponible en este momento. Intenta mas tarde.")
    );

    private final String codigo;
    private final String campo;

    public SoapFault(String codigo, String campo) {
        super(MENSAJES.getOrDefault(codigo,
              "Ocurrio un problema al contactar el servicio."));
        this.codigo = codigo;
        this.campo  = campo;
    }

    public String getCodigo()  { return codigo; }
    public String getCampo()   { return campo; }
    public boolean esEsperado(){ return ESPERADOS.contains(codigo); }
}

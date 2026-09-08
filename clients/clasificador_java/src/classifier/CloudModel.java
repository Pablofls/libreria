package classifier;

/**
 * Enum que representa los cuatro modelos de servicio Cloud reconocidos
 * por la aplicación, más un estado UNKNOWN para entradas no clasificables.
 *
 * Centralizar etiquetas y descripciones aquí evita duplicarlas en la GUI
 * y en el clasificador.
 */
public enum CloudModel {

    IAAS("IaaS",
         "Infraestructura como Servicio: servidores virtuales, redes y " +
         "almacenamiento gestionados en la nube."),

    PAAS("PaaS",
         "Plataforma como Servicio: entornos de desarrollo, despliegue y " +
         "bases de datos gestionadas sin administrar infraestructura."),

    SAAS("SaaS",
         "Software como Servicio: aplicaciones listas para usar accesibles " +
         "desde el navegador mediante suscripción."),

    FAAS("FaaS",
         "Función como Servicio (Serverless): funciones ejecutadas por eventos, " +
         "con pago por uso y sin gestión de servidores."),

    UNKNOWN("Desconocido",
            "No se identificó un modelo predominante. " +
            "Intenta describir el servicio con más detalle.");

    private final String label;
    private final String description;

    CloudModel(String label, String description) {
        this.label       = label;
        this.description = description;
    }

    public String getLabel()       { return label; }
    public String getDescription() { return description; }
}

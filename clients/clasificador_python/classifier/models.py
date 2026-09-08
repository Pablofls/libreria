from enum import Enum


class CloudModel(Enum):
    """
    Modelos de servicio Cloud reconocidos por el clasificador.
    Cada variante lleva su etiqueta de presentación y una descripción corta.
    """
    IAAS    = ("IaaS",
               "Infraestructura como Servicio: servidores virtuales, redes y "
               "almacenamiento gestionados en la nube.")
    PAAS    = ("PaaS",
               "Plataforma como Servicio: entornos de desarrollo, despliegue y "
               "bases de datos gestionadas sin administrar infraestructura.")
    SAAS    = ("SaaS",
               "Software como Servicio: aplicaciones listas para usar accesibles "
               "desde el navegador mediante suscripción.")
    FAAS    = ("FaaS",
               "Función como Servicio (Serverless): funciones ejecutadas por eventos, "
               "pago por uso y sin gestión de servidores.")
    UNKNOWN = ("Desconocido",
               "No se identificó un modelo predominante. "
               "Intenta describir el servicio con más detalle.")

    def __init__(self, label: str, description: str) -> None:
        self.label = label
        self.description = description

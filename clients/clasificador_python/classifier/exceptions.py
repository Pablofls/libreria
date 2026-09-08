class ClassificationException(Exception):
    """
    Se lanza cuando el texto de entrada no cumple las condiciones mínimas
    para ser clasificado (vacío, muy corto, solo símbolos, etc.).

    Al ser una excepción específica, permite que la GUI y la CLI la capturen
    de forma diferenciada respecto a errores inesperados del sistema.
    """

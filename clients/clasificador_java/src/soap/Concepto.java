package soap;

/**
 * Un concepto pendiente de clasificar, tal como lo devuelve el contrato.
 *
 * Lleva el ISBN y no el id interno del libro: el contrato identifica libros por
 * su clave candidata natural y el id del monolito nunca sale del servidor.
 */
public record Concepto(String id, String termino, String definicion,
                       String isbn, String libro, String categoria) {

    /** Texto que se le entrega al clasificador NLP del EG1 para que sugiera. */
    public String paraClasificar() {
        return termino + ". " + definicion;
    }

    @Override
    public String toString() {
        return termino + "  ·  " + libro + "  ·  " + categoria;
    }
}

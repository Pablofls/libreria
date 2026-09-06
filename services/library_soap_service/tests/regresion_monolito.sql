-- =============================================================================
-- regresion_monolito.sql
-- Comprueba que el modulo SOAP no le rompio nada al monolito.
--
--     sudo -u postgres psql -d libreria_db \
--         -f services/library_soap_service/tests/regresion_monolito.sql
--
-- POR QUE EXISTE ESTE ARCHIVO
--   Las 18 pruebas de tests/pruebas_soap.py ejercitan el modulo. Ninguna
--   ejercita al vecino. Por eso pasaron todas mientras el modulo le impedia al
--   monolito borrar un libro: la primera version de fk_cc_libro_concepto era
--   ON DELETE RESTRICT y bloqueaba una operacion del sistema existente.
--
--   Un modulo que se integra con un sistema que ya funcionaba necesita pruebas
--   de ese sistema, no solo de si mismo.
--
-- ES SEGURO EJECUTARLO EN LA VM
--   Todo ocurre dentro de una transaccion que termina en ROLLBACK. Crea datos
--   de prueba, borra libros de verdad para comprobar que se puede, y al final
--   no queda absolutamente nada: ni las filas creadas ni las borradas.
-- =============================================================================

BEGIN;

DO $$
DECLARE
    v_libro       INTEGER;
    v_concepto    INTEGER;
    v_otro_conc   INTEGER;
    v_clasif      INTEGER;
    v_fallos      INTEGER := 0;
    v_mensaje     TEXT;
BEGIN
    -- Un libro que tenga al menos dos conceptos definidos.
    SELECT lc.libro_id INTO v_libro
    FROM libros_conceptos lc GROUP BY lc.libro_id HAVING count(*) >= 2 LIMIT 1;

    IF v_libro IS NULL THEN
        RAISE EXCEPTION 'No hay ningun libro con dos conceptos definidos: '
                        'la base no tiene datos suficientes para esta prueba.';
    END IF;

    SELECT concepto_id INTO v_concepto
    FROM libros_conceptos WHERE libro_id = v_libro ORDER BY concepto_id LIMIT 1;
    SELECT concepto_id INTO v_otro_conc
    FROM libros_conceptos WHERE libro_id = v_libro AND concepto_id <> v_concepto
    ORDER BY concepto_id LIMIT 1;

    INSERT INTO clasificadores (nombre, apellidos, correo)
    VALUES ('Regresion', 'Automatizada', 'regresion.monolito@libreria.udem.mx')
    ON CONFLICT (correo) DO UPDATE SET nombre = EXCLUDED.nombre
    RETURNING id INTO v_clasif;

    INSERT INTO clasificaciones_cloud (clasificador_id, libro_id, concepto_id, modelo)
    VALUES (v_clasif, v_libro, v_concepto, 'IaaS');

    RAISE NOTICE 'Libro % con el concepto % clasificado. Empiezan las pruebas.',
                 v_libro, v_concepto;
    RAISE NOTICE '---------------------------------------------------------------';

    -- R01: quitarle al libro el concepto que fue clasificado.
    BEGIN
        DELETE FROM libros_conceptos
        WHERE libro_id = v_libro AND concepto_id = v_concepto;
        RAISE NOTICE '  OK    R01  Quitar un concepto clasificado a un libro';
    EXCEPTION WHEN foreign_key_violation THEN
        v_fallos := v_fallos + 1;
        RAISE NOTICE ' FALLA  R01  Quitar un concepto clasificado a un libro';
        RAISE NOTICE '             El modulo esta bloqueando al monolito.';
    END;

    -- R02: borrar el libro entero (arrastra sus conceptos, autores e imagenes).
    BEGIN
        INSERT INTO clasificaciones_cloud (clasificador_id, libro_id, concepto_id, modelo)
        VALUES (v_clasif, v_libro, v_otro_conc, 'PaaS');
        DELETE FROM libros WHERE id = v_libro;
        RAISE NOTICE '  OK    R02  Borrar un libro con conceptos clasificados';
    EXCEPTION WHEN foreign_key_violation THEN
        v_fallos := v_fallos + 1;
        RAISE NOTICE ' FALLA  R02  Borrar un libro con conceptos clasificados';
        RAISE NOTICE '             El modulo esta bloqueando al monolito.';
    END;

    -- R03: la mitad valiosa de la restriccion sigue en pie. Clasificar un
    -- concepto que NO esta definido en ese libro debe seguir siendo imposible.
    BEGIN
        SELECT lc.libro_id INTO v_libro
        FROM libros_conceptos lc LIMIT 1;
        SELECT c.id INTO v_concepto FROM conceptos c
        WHERE NOT EXISTS (SELECT 1 FROM libros_conceptos lc2
                          WHERE lc2.libro_id = v_libro AND lc2.concepto_id = c.id)
        LIMIT 1;

        INSERT INTO clasificaciones_cloud (clasificador_id, libro_id, concepto_id, modelo)
        VALUES (v_clasif, v_libro, v_concepto, 'SaaS');

        v_fallos := v_fallos + 1;
        RAISE NOTICE ' FALLA  R03  La base acepto un concepto no definido en el libro';
    EXCEPTION WHEN foreign_key_violation THEN
        RAISE NOTICE '  OK    R03  Sigue prohibido clasificar un concepto que no';
        RAISE NOTICE '             esta definido en ese libro';
    END;

    -- R04: el monolito puede seguir agregando conceptos a un libro.
    BEGIN
        PERFORM sp_guardar_concepto_libro(
            (SELECT id FROM libros ORDER BY id LIMIT 1),
            'Concepto de regresion', 'Definicion de prueba', 'Cap 0', 1);
        RAISE NOTICE '  OK    R04  El monolito sigue pudiendo agregar conceptos';
    EXCEPTION WHEN OTHERS THEN
        GET STACKED DIAGNOSTICS v_mensaje = MESSAGE_TEXT;
        v_fallos := v_fallos + 1;
        RAISE NOTICE ' FALLA  R04  sp_guardar_concepto_libro: %', v_mensaje;
    END;

    -- R05: el rol del modulo no puede leer usuarios ni por accidente.
    BEGIN
        IF has_table_privilege('libreria_soap', 'usuarios', 'SELECT') THEN
            v_fallos := v_fallos + 1;
            RAISE NOTICE ' FALLA  R05  libreria_soap puede leer usuarios';
        ELSE
            RAISE NOTICE '  OK    R05  libreria_soap no tiene acceso a usuarios';
        END IF;
        IF has_table_privilege('libreria_soap', 'libros', 'DELETE') THEN
            v_fallos := v_fallos + 1;
            RAISE NOTICE ' FALLA  R05b libreria_soap puede borrar libros';
        ELSE
            RAISE NOTICE '  OK    R05b libreria_soap no puede borrar libros';
        END IF;
    EXCEPTION WHEN undefined_object THEN
        RAISE NOTICE '  --    R05  El rol libreria_soap no existe en esta base';
    END;

    RAISE NOTICE '---------------------------------------------------------------';
    IF v_fallos = 0 THEN
        RAISE NOTICE 'Sin regresiones: el monolito sigue funcionando igual.';
    ELSE
        RAISE NOTICE '% prueba(s) fallida(s). El modulo esta afectando al monolito.',
                     v_fallos;
    END IF;
END $$;

-- Nada de lo anterior se conserva.
ROLLBACK;

SELECT 'Transaccion revertida: la base quedo exactamente como estaba.' AS estado;

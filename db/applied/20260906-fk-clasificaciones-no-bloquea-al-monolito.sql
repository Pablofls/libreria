-- =============================================================================
-- 20260906-fk-clasificaciones-no-bloquea-al-monolito.sql
--
-- QUE HACE
--   Cambia fk_cc_libro_concepto de ON DELETE RESTRICT a ON DELETE CASCADE.
--
-- POR QUE
--   Con RESTRICT, el modulo SOAP le impedia al monolito borrar un libro o
--   quitarle un concepto en cuanto alguien lo hubiera clasificado:
--
--     ERROR: update or delete on table "libros_conceptos" violates foreign key
--            constraint "fk_cc_libro_concepto" on table "clasificaciones_cloud"
--
--   Es decir, un componente nuevo bloqueando una operacion del sistema
--   existente. El criterio de finalizacion del ejercicio dice que el monolito
--   debe seguir funcionando sin cambios, y con RESTRICT no lo hacia.
--
--   La justificacion original era proteger el registro de auditoria. Se cambia
--   de opinion a proposito: el modulo no es el sistema de registro del catalogo.
--   Si el bibliotecario borra el libro, la clasificacion deja de referirse a
--   algo real, y perderla es preferible a secuestrarle una operacion a su dueno.
--
--   Lo que SI se conserva: la clave foranea compuesta sigue obligando a que el
--   concepto este DEFINIDO en ese libro al registrar la clasificacion. Esa era
--   la mitad valiosa de la restriccion y no se toca.
--
-- ALCANCE
--   Solo instalaciones donde ya se ejecuto soap_module.sql con la definicion
--   anterior. Una instalacion nueva ya crea la clave con CASCADE y no necesita
--   este archivo.
--
--   No borra ninguna fila: solo redefine la accion de la clave foranea.
-- =============================================================================

BEGIN;

ALTER TABLE clasificaciones_cloud
    DROP CONSTRAINT IF EXISTS fk_cc_libro_concepto;

ALTER TABLE clasificaciones_cloud
    ADD CONSTRAINT fk_cc_libro_concepto
        FOREIGN KEY (libro_id, concepto_id)
        REFERENCES libros_conceptos (libro_id, concepto_id)
        ON UPDATE CASCADE ON DELETE CASCADE;

COMMIT;

-- Control: debe decir 'c' (CASCADE) en confdeltype.
SELECT conname,
       confdeltype AS accion_al_borrar,
       CASE confdeltype WHEN 'c' THEN 'CASCADE' WHEN 'r' THEN 'RESTRICT'
                        WHEN 'a' THEN 'NO ACTION' ELSE confdeltype::text END AS lectura
FROM pg_constraint
WHERE conname = 'fk_cc_libro_concepto';

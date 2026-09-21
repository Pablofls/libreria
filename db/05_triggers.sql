-- =============================================================================
-- 05_triggers.sql
-- Disparadores. Cada uno protege una regla que la aplicacion podria olvidar.
--
--     psql -U libreria_owner -d libreria_db -f db/05_triggers.sql
--
-- Un trigger no sustituye a una restriccion declarativa: donde un UNIQUE o un
-- CHECK bastan, se usa la restriccion (es mas barata y no se puede evadir).
-- Los triggers de aqui existen para lo que una restriccion no puede expresar:
-- modificar OTRAS filas, o dar un mensaje de error legible.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Un solo administrador  (RF-11, defensa en base de datos)
-- La defensa dura es el indice unico parcial ux_usuarios_admin_unico de
-- 01_schema.sql. Este trigger corre ANTES y solo mejora el mensaje: sin el, el
-- usuario veria "duplicate key value violates unique constraint".
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_un_solo_admin() RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.rol = 'admin' THEN
        IF EXISTS (SELECT 1 FROM usuarios
                   WHERE rol = 'admin' AND id IS DISTINCT FROM NEW.id) THEN
            RAISE EXCEPTION
                'Ya existe un Administrador. El sistema admite como maximo uno.'
                USING ERRCODE = 'unique_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_un_solo_admin ON usuarios;
CREATE TRIGGER trg_un_solo_admin
    BEFORE INSERT OR UPDATE OF rol ON usuarios
    FOR EACH ROW EXECUTE FUNCTION fn_un_solo_admin();

-- -----------------------------------------------------------------------------
-- 2. Nunca quedarse sin administrador
-- Simetrico al anterior: impide borrar o degradar al unico admin, que dejaria
-- el sistema sin nadie capaz de administrarlo. Esto NO se puede expresar con
-- una restriccion declarativa: depende del resto de la tabla.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_conservar_admin() RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.rol = 'admin' AND (TG_OP = 'DELETE' OR NEW.rol <> 'admin') THEN
        IF NOT EXISTS (SELECT 1 FROM usuarios
                       WHERE rol = 'admin' AND id <> OLD.id) THEN
            RAISE EXCEPTION
                'No se puede dejar el sistema sin Administrador.'
                USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;
    RETURN CASE TG_OP WHEN 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

DROP TRIGGER IF EXISTS trg_conservar_admin ON usuarios;
CREATE TRIGGER trg_conservar_admin
    BEFORE DELETE OR UPDATE OF rol ON usuarios
    FOR EACH ROW EXECUTE FUNCTION fn_conservar_admin();

-- -----------------------------------------------------------------------------
-- 3. Una sola portada por libro  (RF-09)
-- ux_imagenes_portada_unica impide que haya dos, pero por si solo hace fallar
-- el UPDATE. Este trigger apaga la portada anterior antes de encender la nueva:
-- convierte un error en el comportamiento esperado. Toca OTRAS filas, cosa que
-- una restriccion no puede hacer.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_portada_unica() RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.es_portada THEN
        UPDATE imagenes_libros
        SET es_portada = FALSE
        WHERE libro_id = NEW.libro_id
          AND id IS DISTINCT FROM NEW.id
          AND es_portada;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_portada_unica ON imagenes_libros;
CREATE TRIGGER trg_portada_unica
    BEFORE INSERT OR UPDATE OF es_portada ON imagenes_libros
    FOR EACH ROW EXECUTE FUNCTION fn_portada_unica();

-- -----------------------------------------------------------------------------
-- 4. Promover portada al borrar la actual
-- Si se elimina la imagen que era portada y quedan otras, una de ellas pasa a
-- serlo. Evita que el catalogo muestre el marcador de "sin portada" teniendo
-- imagenes disponibles.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_promover_portada() RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.es_portada THEN
        UPDATE imagenes_libros
        SET es_portada = TRUE
        WHERE id = (SELECT id FROM imagenes_libros
                    WHERE libro_id = OLD.libro_id AND id <> OLD.id
                    ORDER BY id LIMIT 1);
    END IF;
    RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS trg_promover_portada ON imagenes_libros;
CREATE TRIGGER trg_promover_portada
    AFTER DELETE ON imagenes_libros
    FOR EACH ROW EXECUTE FUNCTION fn_promover_portada();

-- -----------------------------------------------------------------------------
-- 5. Sello de modificacion en libros
-- actualizado_en debe reflejar el ultimo cambio real, venga de la aplicacion,
-- de un procedimiento o de psql. Dejarlo a cargo del codigo garantiza que
-- alguna ruta se olvide de ponerlo.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_sello_actualizacion() RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.actualizado_en := NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_libros_actualizado ON libros;
CREATE TRIGGER trg_libros_actualizado
    BEFORE UPDATE ON libros
    FOR EACH ROW EXECUTE FUNCTION fn_sello_actualizacion();

-- -----------------------------------------------------------------------------
-- 6. Normalizar el correo de los usuarios
-- Guarda el correo en minusculas y sin espacios. Sin esto, uq_usuarios_email
-- dejaria pasar 'Admin@x.com' y 'admin@x.com' como dos cuentas distintas.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_normalizar_email() RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.email  := lower(btrim(NEW.email));
    NEW.nombre := btrim(NEW.nombre);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_normalizar_email ON usuarios;
CREATE TRIGGER trg_normalizar_email
    BEFORE INSERT OR UPDATE OF email, nombre ON usuarios
    FOR EACH ROW EXECUTE FUNCTION fn_normalizar_email();

-- -----------------------------------------------------------------------------
-- 7. Sincronizar personas <-> usuarios.nombre
--
-- El nombre real vive en `personas`, partido en nombre y dos apellidos.
-- `usuarios.nombre` se conserva como copia derivada porque el monolito Node lo
-- lee y lo escribe, y el monolito no se toca. No puede ser una columna
-- GENERATED: esas son de solo lectura y el monolito hace INSERT y UPDATE sobre
-- ella. Asi que la coherencia la sostienen estos disparadores, en los dos
-- sentidos.
--
-- Las dos funciones auxiliares viven aqui y no en 04_stored_procedures.sql
-- porque existen solo para estos triggers: separarlas de su unico consumidor
-- no ganaria nada y obligaria a leer dos archivos para entender uno.
--
-- La recursion se corta sola: cada lado compara con IS DISTINCT FROM antes de
-- escribir, y un UPDATE que no cambia nada no dispara nada.
-- -----------------------------------------------------------------------------

-- Compone el nombre completo. concat_ws se salta los NULL, así que "Ana" con
-- los dos apellidos vacíos sale "Ana" y no "Ana  ".
CREATE OR REPLACE FUNCTION fn_nombre_completo(
    p_nombre TEXT, p_paterno TEXT, p_materno TEXT
) RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $$
    SELECT btrim(regexp_replace(
        concat_ws(' ', btrim(p_nombre), btrim(p_paterno), btrim(p_materno)),
        '\s+', ' ', 'g'));
$$;

-- Reparte un nombre suelto. Regla: el último token es el apellido materno, el
-- penúltimo el paterno, y todo lo anterior es el nombre de pila. Acierta con
-- "Ana Ruiz", "Ana Ruiz López" y "Ana María Ruiz López"; falla con apellidos
-- compuestos ("de la Cruz"). Ver el punto ciego de la cabecera.
CREATE OR REPLACE FUNCTION fn_partir_nombre(p_completo TEXT)
RETURNS TABLE (nombre TEXT, apellido_paterno TEXT, apellido_materno TEXT)
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    t TEXT[];
    n INTEGER;
BEGIN
    t := regexp_split_to_array(
             btrim(regexp_replace(coalesce(p_completo, ''), '\s+', ' ', 'g')), ' ');
    n := array_length(t, 1);

    IF n IS NULL OR t[1] = '' THEN
        RETURN;                                            -- nada que repartir
    ELSIF n = 1 THEN
        RETURN QUERY SELECT t[1], NULL::TEXT, NULL::TEXT;
    ELSIF n = 2 THEN
        RETURN QUERY SELECT t[1], t[2], NULL::TEXT;
    ELSIF n = 3 THEN
        RETURN QUERY SELECT t[1], t[2], t[3];
    ELSE
        RETURN QUERY SELECT array_to_string(t[1:n-2], ' '), t[n-1], t[n];
    END IF;
END;
$$;

-- -----------------------------------------------------------------------------
-- Los disparadores
-- -----------------------------------------------------------------------------

-- a) Alta de usuario.
-- Dos caminos:
--   · Llega sin persona_id (monolito): se reparte el nombre y se crea la persona.
--   · Llega con persona_id (microservicio): el nombre plano se DERIVA de la
--     persona. No se confía en el `nombre` que venga en el INSERT — si se
--     confiara, un cliente podría dejar las dos representaciones en desacuerdo
--     desde el minuto cero. Por eso el microservicio puede omitir `nombre`
--     por completo: el NOT NULL se comprueba después de los BEFORE triggers.
CREATE OR REPLACE FUNCTION fn_usuario_sincroniza_alta() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
DECLARE p RECORD;
BEGIN
    IF NEW.persona_id IS NULL THEN
        SELECT * INTO p FROM fn_partir_nombre(NEW.nombre);
        IF p.nombre IS NULL THEN
            RAISE EXCEPTION 'No se puede crear la cuenta sin nombre'
                USING ERRCODE = 'check_violation';
        END IF;
        INSERT INTO personas (nombre, apellido_paterno, apellido_materno)
        VALUES (p.nombre, p.apellido_paterno, p.apellido_materno)
        RETURNING id INTO NEW.persona_id;
    END IF;

    SELECT fn_nombre_completo(nombre, apellido_paterno, apellido_materno)
      INTO NEW.nombre
      FROM personas WHERE id = NEW.persona_id;

    RETURN NEW;
END;
$$;

-- El nombre del trigger importa: PostgreSQL los dispara en orden alfabético y
-- 'trg_usuario_…' va después de 'trg_normalizar_email', que es quien recorta
-- los espacios. Así se reparte un nombre ya normalizado.
DROP TRIGGER IF EXISTS trg_usuario_sincroniza_alta ON usuarios;
CREATE TRIGGER trg_usuario_sincroniza_alta
    BEFORE INSERT ON usuarios
    FOR EACH ROW EXECUTE FUNCTION fn_usuario_sincroniza_alta();

-- b) El monolito editó usuarios.nombre → repartirlo.
-- La comparación contra el nombre compuesto actual distingue una edición real
-- del eco del trigger (c). Sin ella, cada escritura del microservicio volvería a
-- pasar por la heurística de reparto y podría estropear un dato que ya venía
-- bien separado.
CREATE OR REPLACE FUNCTION fn_usuario_nombre_a_persona() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
DECLARE
    v_actual TEXT;
    p        RECORD;
BEGIN
    SELECT fn_nombre_completo(nombre, apellido_paterno, apellido_materno)
      INTO v_actual
      FROM personas WHERE id = NEW.persona_id;

    IF NEW.nombre IS DISTINCT FROM v_actual THEN
        SELECT * INTO p FROM fn_partir_nombre(NEW.nombre);
        UPDATE personas
           SET nombre           = p.nombre,
               apellido_paterno = p.apellido_paterno,
               apellido_materno = p.apellido_materno
         WHERE id = NEW.persona_id;
    END IF;
    RETURN NULL;                                  -- AFTER: el valor ya no se usa
END;
$$;

DROP TRIGGER IF EXISTS trg_usuario_nombre_a_persona ON usuarios;
CREATE TRIGGER trg_usuario_nombre_a_persona
    AFTER UPDATE OF nombre ON usuarios
    FOR EACH ROW WHEN (NEW.nombre IS DISTINCT FROM OLD.nombre)
    EXECUTE FUNCTION fn_usuario_nombre_a_persona();

-- c) El microservicio editó la persona → recomponer usuarios.nombre.
-- El `IS DISTINCT FROM` del WHERE es el que corta la recursión: cuando este
-- UPDATE dispara (b), el nombre ya coincide y (b) no escribe nada.
CREATE OR REPLACE FUNCTION fn_persona_a_usuario_nombre() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
DECLARE v_completo TEXT;
BEGIN
    v_completo := fn_nombre_completo(NEW.nombre, NEW.apellido_paterno, NEW.apellido_materno);
    UPDATE usuarios
       SET nombre = v_completo
     WHERE persona_id = NEW.id
       AND nombre IS DISTINCT FROM v_completo;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_persona_a_usuario_nombre ON personas;
CREATE TRIGGER trg_persona_a_usuario_nombre
    AFTER UPDATE ON personas
    FOR EACH ROW EXECUTE FUNCTION fn_persona_a_usuario_nombre();

-- d) Se borró la cuenta → se va su persona.
-- La FK apunta de usuarios a personas, así que ON DELETE CASCADE no sirve aquí:
-- limpiaría en el sentido contrario al que hace falta. El monolito hace
-- `DELETE FROM usuarios` y no sabe que personas existe; sin este trigger, cada
-- baja dejaría una fila huérfana.
CREATE OR REPLACE FUNCTION fn_usuario_baja_persona() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM personas WHERE id = OLD.persona_id;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_usuario_baja_persona ON usuarios;
CREATE TRIGGER trg_usuario_baja_persona
    AFTER DELETE ON usuarios
    FOR EACH ROW EXECUTE FUNCTION fn_usuario_baja_persona();

-- Inventario de disparadores creados.
SELECT c.relname AS tabla, t.tgname AS disparador
FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
WHERE NOT t.tgisinternal AND c.relnamespace = 'public'::regnamespace
ORDER BY 1, 2;

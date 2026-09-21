-- =============================================================================
-- 20260921-separa-nombre-en-personas.sql
--
-- QUÉ HACE
-- Saca el nombre de la tabla `usuarios` a una tabla propia, `personas`, con el
-- nombre y los dos apellidos en columnas separadas, y relaciona `usuarios` con
-- ella mediante `usuarios.persona_id` (FK 1:1).
--
-- POR QUÉ
-- El microservicio de autenticación (apps/services/login) pide nombre, apellido
-- paterno y apellido materno por separado. Hoy todo eso vive apelmazado en una
-- sola columna `usuarios.nombre`, que es un grupo de datos compuesto: no se
-- puede ordenar por apellido, ni buscar por apellido materno, ni saber dónde
-- termina el nombre de pila. Separarlo es 1FN aplicada a un atributo que en
-- realidad son tres.
--
-- LA RESTRICCIÓN QUE MANDA SOBRE TODO LO DEMÁS
-- El monolito Node no se toca. Hace `SELECT nombre`, `INSERT (nombre, …)` y
-- `UPDATE SET nombre = $1` sobre `usuarios` (src/modules/usuarios/usuarios.model.js
-- y src/modules/auth/auth.model.js) y tiene que seguir funcionando sin que se
-- edite un solo archivo JS ni EJS.
--
-- Por eso `usuarios.nombre` SE CONSERVA. No se borra y no se convierte en
-- GENERATED: una columna generada es de sólo lectura y el monolito la escribe,
-- así que el primer alta de usuario desde el panel fallaría. La columna queda
-- como una vista materializada a mano del nombre completo, sincronizada en los
-- dos sentidos por disparadores:
--
--   · El monolito escribe `nombre`      → un trigger lo reparte en `personas`.
--   · El microservicio escribe personas → un trigger recompone `nombre`.
--
-- Ambos lados comparan antes de escribir (IS DISTINCT FROM), así que el eco de
-- un trigger en el otro no escribe nada y la recursión se corta sola.
--
-- EL PUNTO CIEGO, DICHO EN VOZ ALTA
-- Repartir un nombre suelto en tres campos es una heurística, no una función
-- reversible. "Ana Ruiz" se parte bien; "María de la Cruz" queda como
-- nombre='María', paterno='de', materno='la Cruz', que es incorrecto. El
-- reparto sólo se dispara cuando el nombre cambia desde el monolito, que es la
-- única fuente que no distingue las partes; cuando el dato entra por el
-- microservicio, las tres columnas son la verdad y no se adivina nada.
-- El backfill de abajo deja una consulta que lista las filas ambiguas para
-- revisarlas a mano.
--
-- CUÁNDO EJECUTARLO
-- Después de 20260830-rediseno-4fn.sql y 20260831-crea-usuario-app-privilegios-minimos.sql.
--
-- CÓMO EJECUTARLO
--     cd /opt/udem/libreria
--     psql -U libreria_user -d libreria_db -h 127.0.0.1 \
--          -f db/pending/20260921-separa-nombre-en-personas.sql
--
-- Como libreria_user, que es quien es DUEÑO de las tablas en la VM y por tanto
-- el único que puede hacer DDL sobre ellas. Ojo: las cabeceras de los scripts
-- canónicos db/00…06 dicen `libreria_owner`, un rol que en la VM no existe.
-- La discrepancia viene de antes de este cambio y se arregla aparte; aquí se
-- documenta el rol real para que el comando funcione tal cual está escrito.
--
-- Es idempotente: se puede volver a ejecutar sin duplicar personas ni
-- restricciones. Va entero dentro de una transacción; si algo falla, no queda
-- nada a medias.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. La tabla nueva
--
-- Los apellidos admiten NULL a propósito, y no es una concesión perezosa:
--   · Los usuarios que ya existen traen nombres de una o dos palabras; no se
--     puede inventar un apellido materno para "Administrador".
--   · No todo el mundo tiene dos apellidos. Un NOT NULL aquí obligaría a
--     guardar basura ('', '-', 'N/A') para representar "no tiene", que es
--     justamente lo que un NULL significa.
-- Que el registro del microservicio EXIJA los tres campos es una política de
-- ese endpoint, no una verdad sobre las personas. La regla de negocio va en el
-- servicio; la base de datos modela lo que puede existir.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS personas (
    id               SERIAL       PRIMARY KEY,
    nombre           VARCHAR(100) NOT NULL,
    apellido_paterno VARCHAR(100),
    apellido_materno VARCHAR(100),

    CONSTRAINT ck_personas_nombre   CHECK (btrim(nombre) <> ''),
    CONSTRAINT ck_personas_paterno  CHECK (apellido_paterno IS NULL OR btrim(apellido_paterno) <> ''),
    CONSTRAINT ck_personas_materno  CHECK (apellido_materno IS NULL OR btrim(apellido_materno) <> ''),

    -- El nombre completo se copia a usuarios.nombre, que es VARCHAR(100). Sin
    -- este CHECK, tres campos de 100 caracteres podrían componer 302 y el
    -- trigger reventaría con un 22001 en mitad de una alta. Se frena aquí, con
    -- un error que apunta al campo de verdad culpable.
    CONSTRAINT ck_personas_largo_compuesto CHECK (
        length(btrim(concat_ws(' ', nombre, apellido_paterno, apellido_materno))) <= 100
    )
);

COMMENT ON TABLE personas IS
    'Nombre y apellidos de la persona detrás de una cuenta. Separado de usuarios '
    'para que el nombre deje de ser un campo compuesto.';

-- -----------------------------------------------------------------------------
-- 2. La relación, en tres pasos: columna → backfill → restricciones
--
-- No se puede crear la columna NOT NULL de un golpe: las filas que ya existen
-- no tendrían valor y el ALTER fallaría. Primero se admite NULL, se rellena, y
-- sólo entonces se exige.
-- -----------------------------------------------------------------------------
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS persona_id INTEGER;

-- -----------------------------------------------------------------------------
-- 3. Las dos funciones que traducen entre los dos mundos
-- Se crean antes del backfill porque el backfill ya las usa.
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
-- 4. Backfill: una persona por cada usuario que aún no la tenga
--
-- Fila a fila y no con un INSERT … SELECT masivo porque hace falta el id que
-- devuelve cada INSERT para escribirlo en su usuario. Son decenas de filas: el
-- bucle es irrelevante en tiempo y mucho más legible que un CTE encadenado.
-- Se ejecuta ANTES de crear los disparadores, para que el UPDATE de persona_id
-- no dispare la sincronización sobre datos a medio migrar.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    r        RECORD;
    v_id     INTEGER;
    v_total  INTEGER := 0;
BEGIN
    FOR r IN
        SELECT u.id AS usuario_id, p.nombre, p.apellido_paterno, p.apellido_materno
        FROM usuarios u
        CROSS JOIN LATERAL fn_partir_nombre(u.nombre) p
        WHERE u.persona_id IS NULL
        ORDER BY u.id
    LOOP
        INSERT INTO personas (nombre, apellido_paterno, apellido_materno)
        VALUES (r.nombre, r.apellido_paterno, r.apellido_materno)
        RETURNING id INTO v_id;

        UPDATE usuarios SET persona_id = v_id WHERE id = r.usuario_id;
        v_total := v_total + 1;
    END LOOP;

    RAISE NOTICE 'Personas creadas por el backfill: %', v_total;
END $$;

-- -----------------------------------------------------------------------------
-- 5. Ahora sí, las restricciones
-- UNIQUE es lo que convierte la FK en un 1:1: sin él, dos cuentas podrían
-- compartir la misma persona y editar el nombre de una cambiaría el de la otra.
-- -----------------------------------------------------------------------------
ALTER TABLE usuarios ALTER COLUMN persona_id SET NOT NULL;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_usuarios_persona') THEN
        ALTER TABLE usuarios ADD CONSTRAINT uq_usuarios_persona UNIQUE (persona_id);
    END IF;
END $$;

-- Sin ON DELETE: borrar una persona con cuenta viva se bloquea. La limpieza va
-- al revés (borras la cuenta y el trigger se lleva la persona), que es el orden
-- que respeta la FK.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_usuarios_persona') THEN
        ALTER TABLE usuarios ADD CONSTRAINT fk_usuarios_persona
            FOREIGN KEY (persona_id) REFERENCES personas(id);
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 6. Los disparadores de sincronización
-- -----------------------------------------------------------------------------

-- 6a. Alta de usuario.
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

-- 6b. El monolito editó usuarios.nombre → repartirlo.
-- La comparación contra el nombre compuesto actual distingue una edición real
-- del eco del trigger 6c. Sin ella, cada escritura del microservicio volvería a
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

-- 6c. El microservicio editó la persona → recomponer usuarios.nombre.
-- El `IS DISTINCT FROM` del WHERE es el que corta la recursión: cuando este
-- UPDATE dispara 6b, el nombre ya coincide y 6b no escribe nada.
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

-- 6d. Se borró la cuenta → se va su persona.
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

-- -----------------------------------------------------------------------------
-- 7. Permisos
-- Los ALTER DEFAULT PRIVILEGES de 20260831 sí se declararon FOR ROLE
-- libreria_user, que es el dueño real, así que la tabla nueva debería heredar
-- los permisos. Se otorgan igual y explícitamente: un GRANT redundante no
-- cuesta nada, y depender de un default invisible es la clase de suposición
-- que se descubre cuando el microservicio contesta 500 en producción.
-- -----------------------------------------------------------------------------
GRANT SELECT, INSERT, UPDATE, DELETE ON personas              TO libreria_app;
GRANT USAGE, SELECT                  ON SEQUENCE personas_id_seq TO libreria_app;

COMMIT;

-- =============================================================================
-- VERIFICACIÓN  (se ejecuta fuera de la transacción; sólo lee)
-- =============================================================================

-- 1) Ningún usuario sin persona, ninguna persona sin usuario.
SELECT (SELECT count(*) FROM usuarios WHERE persona_id IS NULL) AS usuarios_sin_persona,
       (SELECT count(*) FROM personas p
         WHERE NOT EXISTS (SELECT 1 FROM usuarios u WHERE u.persona_id = p.id)) AS personas_huerfanas;

-- 2) Las dos representaciones coinciden en todas las filas. Debe dar 0.
SELECT count(*) AS filas_descuadradas
FROM usuarios u JOIN personas p ON p.id = u.persona_id
WHERE u.nombre IS DISTINCT FROM fn_nombre_completo(p.nombre, p.apellido_paterno, p.apellido_materno);

-- 3) Filas que la heurística pudo haber repartido mal: apellidos en minúscula
--    (de, del, la, los, van, di…) o nombres de más de tres palabras. REVÍSALAS
--    A MANO y corrígelas con un UPDATE sobre personas (el trigger 6c actualiza
--    usuarios.nombre solo).
SELECT u.id, u.email, u.nombre AS nombre_original,
       p.nombre, p.apellido_paterno, p.apellido_materno
FROM usuarios u JOIN personas p ON p.id = u.persona_id
WHERE p.apellido_paterno ~ '^[a-záéíóúñ]'
   OR p.apellido_materno ~ '^[a-záéíóúñ]'
   OR array_length(regexp_split_to_array(btrim(u.nombre), '\s+'), 1) > 3
ORDER BY u.id;

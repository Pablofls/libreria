-- =============================================================================
-- 20260905-modulo-soap-tablas-propias.sql   [APLICADO en la VM el 2026-09-05]
--
-- Copia literal de services/library_soap_service/sql/soap_module.sql tal como
-- se ejecuto en la VM (commit 80b6daf). Es una instantanea historica: no se
-- edita. El script vivo del modulo sigue evolucionando en services/, y toda
-- correccion posterior entra como archivo nuevo en db/pending/.
--
-- Antes vivia aqui un enlace simbolico al script del modulo. Fue un error: un
-- enlace hace que el historial de lo aplicado cambie cada vez que se edita el
-- original, que es exactamente lo que db/applied/ debe impedir.
-- =============================================================================

-- =============================================================================
-- soap_module.sql
-- Persistencia propia del modulo SOAP de clasificacion Cloud (Ejercicio 03).
--
--     sudo -u postgres psql -d libreria_db \
--         -f services/library_soap_service/sql/soap_module.sql
--
-- Se ejecuta como SUPERUSUARIO, porque crea un rol y otorga permisos sobre
-- tablas que no le pertenecen. Al final reasigna sus objetos al mismo dueno que
-- tienen las tablas del monolito, sea cual sea el nombre de ese rol en esta
-- instalacion: no se supone que se llame de una forma concreta.
--
-- QUE HACE
--   Crea las tres tablas propias del modulo (clasificadores,
--   clasificaciones_cloud, clientes_servidos), las vistas y el procedimiento
--   que usa el servicio, y el rol de minimo privilegio libreria_soap.
--
-- POR QUE
--   El modulo SOAP comparte la base con el monolito Node pero NO le pertenece.
--   No toca ni una sola definicion existente: solo agrega objetos nuevos y
--   referencia por clave foranea a libros, conceptos y libros_conceptos.
--   La tabla usuarios del monolito NO se reutiliza para los clasificadores:
--   son identidades de otro sistema, con otro ciclo de vida y otra autoridad.
--
-- CORRESPONDENCIA CON EL ENUNCIADO
--   El enunciado nombra las tablas del monolito en ingles. En esta base se
--   llaman en espanol, que es la convencion del proyecto:
--       books  -> libros        concepts      -> conceptos
--       categories -> categorias    book_concepts -> libros_conceptos
--
-- Es idempotente: se puede volver a ejecutar sin romper nada.
-- Ninguna credencial aparece en este archivo. La contrasena del rol se asigna
-- fuera del repositorio (ver el bloque final).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- clasificadores
-- Identidad de quien clasifica desde el cliente de escritorio. La GUI captura
-- nombre, apellidos y correo, y eso es TODO lo que el modulo necesita saber.
--
-- PK sustituta + UNIQUE(correo): el correo es la clave natural con la que el
--   cliente se identifica entre sesiones, pero es un dato editable, mala PK.
-- No hay password_hash: la autenticacion de las operaciones sensibles es
--   WS-Security a nivel de servicio, no de fila. Guardar aqui una credencial
--   duplicaria la autoridad de usuarios y no aportaria nada.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clasificadores (
    id         SERIAL       PRIMARY KEY,
    nombre     VARCHAR(80)  NOT NULL,
    apellidos  VARCHAR(120) NOT NULL,
    correo     VARCHAR(150) NOT NULL,
    creado_en  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_clasificadores_correo UNIQUE (correo),
    CONSTRAINT ck_clasificadores_correo
        CHECK (correo ~* '^[^@[:space:]]+@[^@[:space:]]+\.[a-z]{2,}$'),
    CONSTRAINT ck_clasificadores_nombre
        CHECK (btrim(nombre) <> '' AND btrim(apellidos) <> '')
);

CREATE INDEX IF NOT EXISTS ix_clasificadores_correo
    ON clasificadores (lower(correo));

-- -----------------------------------------------------------------------------
-- clientes_servidos
-- Que tipo de cliente de escritorio consume el servicio y cuantas peticiones se
-- le han atendido. Es telemetria del modulo, no del negocio.
--
-- UNIQUE(tipo_cliente, identificador): un mismo binario instalado en dos
--   maquinas son dos clientes; el par identifica la instalacion.
-- El contador se incrementa dentro de la MISMA transaccion que registra la
--   clasificacion: si el registro falla, el contador no miente.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clientes_servidos (
    id                   SERIAL       PRIMARY KEY,
    tipo_cliente         VARCHAR(40)  NOT NULL,
    identificador        VARCHAR(120) NOT NULL,
    peticiones_atendidas INTEGER      NOT NULL DEFAULT 0,
    primera_peticion     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    ultima_peticion      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_clientes_servidos UNIQUE (tipo_cliente, identificador),
    CONSTRAINT ck_clientes_tipo        CHECK (btrim(tipo_cliente) <> ''),
    CONSTRAINT ck_clientes_identificador CHECK (btrim(identificador) <> ''),
    CONSTRAINT ck_clientes_peticiones  CHECK (peticiones_atendidas >= 0)
);

-- -----------------------------------------------------------------------------
-- clasificaciones_cloud
-- El hecho central del modulo: un clasificador dijo que tal concepto, definido
-- en tal libro, corresponde a tal modelo de servicio Cloud.
--
-- FK COMPUESTA (libro_id, concepto_id) -> libros_conceptos: no basta con que el
--   libro y el concepto existan por separado; el concepto tiene que estar
--   DEFINIDO en ese libro. libros_conceptos tiene justamente esa PK compuesta,
--   asi que la base garantiza la combinacion y el servicio no tiene que
--   comprobarla a mano. Es la restriccion mas valiosa de todo el script.
-- ON DELETE RESTRICT hacia libros_conceptos y clasificadores: un registro de
--   auditoria no debe desaparecer en silencio porque alguien edito el catalogo.
-- ON DELETE SET NULL hacia clientes_servidos: si se depura la telemetria, la
--   clasificacion sobrevive; el cliente era contexto, no sujeto.
-- UNIQUE(clasificador_id, concepto_id): la restriccion que pide el enunciado.
--   El mismo clasificador no registra dos veces el mismo concepto, aunque lo
--   intente desde otro libro. Es la que produce el SOAP Fault de conflicto 409.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clasificaciones_cloud (
    id                 SERIAL      PRIMARY KEY,
    clasificador_id    INTEGER     NOT NULL,
    libro_id           INTEGER     NOT NULL,
    concepto_id        INTEGER     NOT NULL,
    modelo             VARCHAR(10) NOT NULL,
    cliente_servido_id INTEGER,
    clasificado_en     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_clasificaciones_modelo
        CHECK (modelo IN ('IaaS', 'PaaS', 'SaaS', 'FaaS')),
    CONSTRAINT uq_clasificacion_no_repetida
        UNIQUE (clasificador_id, concepto_id),

    CONSTRAINT fk_cc_clasificador FOREIGN KEY (clasificador_id)
        REFERENCES clasificadores (id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_cc_libro_concepto FOREIGN KEY (libro_id, concepto_id)
        REFERENCES libros_conceptos (libro_id, concepto_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_cc_cliente FOREIGN KEY (cliente_servido_id)
        REFERENCES clientes_servidos (id) ON UPDATE CASCADE ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_cc_clasificador ON clasificaciones_cloud (clasificador_id);
CREATE INDEX IF NOT EXISTS ix_cc_concepto     ON clasificaciones_cloud (concepto_id);
CREATE INDEX IF NOT EXISTS ix_cc_modelo       ON clasificaciones_cloud (modelo);

-- =============================================================================
-- Vistas. El servicio lee de aqui en vez de repetir los JOIN en Python: la
-- consulta queda definida una vez y el rol del modulo puede tener permiso sobre
-- la vista sin tener permiso amplio sobre las tablas del monolito.
-- =============================================================================

-- Todo concepto DEFINIDO en un libro, con lo que el cliente necesita para
-- decidir: termino, definicion, libro, ISBN y categoria comercial.
CREATE OR REPLACE VIEW v_conceptos_clasificables AS
SELECT lc.libro_id,
       lc.concepto_id,
       co.termino,
       lc.definicion,
       lc.capitulo,
       lc.pagina,
       l.isbn,
       l.titulo        AS libro,
       cat.nombre      AS categoria
FROM libros_conceptos lc
JOIN conceptos  co  ON co.id  = lc.concepto_id
JOIN libros     l   ON l.id   = lc.libro_id
JOIN categorias cat ON cat.id = l.categoria_id;

COMMENT ON VIEW v_conceptos_clasificables IS
    'Conceptos definidos por libro, con ISBN y categoria. Base de ObtenerConceptosPendientes.';

-- Pendientes GLOBALES: los que nadie ha clasificado todavia.
CREATE OR REPLACE VIEW v_conceptos_pendientes AS
SELECT v.*
FROM v_conceptos_clasificables v
WHERE NOT EXISTS (
    SELECT 1 FROM clasificaciones_cloud cc
    WHERE cc.libro_id = v.libro_id AND cc.concepto_id = v.concepto_id
);

COMMENT ON VIEW v_conceptos_pendientes IS
    'Conceptos que ningun clasificador ha registrado aun.';

-- Progreso por clasificador. Los pendientes se calculan contra el universo de
-- conceptos DISTINTOS, porque la restriccion de no repetir es por concepto.
CREATE OR REPLACE VIEW v_progreso_clasificadores AS
SELECT c.id            AS clasificador_id,
       c.correo,
       c.nombre,
       c.apellidos,
       count(cc.id)::int AS total_clasificados,
       ((SELECT count(DISTINCT concepto_id)::int FROM libros_conceptos)
        - count(DISTINCT cc.concepto_id)::int) AS total_pendientes
FROM clasificadores c
LEFT JOIN clasificaciones_cloud cc ON cc.clasificador_id = c.id
GROUP BY c.id, c.correo, c.nombre, c.apellidos;

COMMENT ON VIEW v_progreso_clasificadores IS
    'Totales clasificados y pendientes por clasificador. Base de ObtenerProgresoUsuario.';

-- Conteo por modelo. Los cuatro modelos aparecen siempre, aunque tengan cero:
-- un cliente que grafica no deberia tener que inventar las categorias faltantes.
CREATE OR REPLACE VIEW v_estadisticas_modelo AS
SELECT m.modelo,
       count(cc.id)::int AS total,
       count(DISTINCT cc.clasificador_id)::int AS clasificadores
FROM (VALUES ('IaaS'), ('PaaS'), ('SaaS'), ('FaaS')) AS m(modelo)
LEFT JOIN clasificaciones_cloud cc ON cc.modelo = m.modelo
GROUP BY m.modelo;

COMMENT ON VIEW v_estadisticas_modelo IS
    'Conteo por modelo Cloud. Base de ObtenerEstadisticasPorModelo (WS-Security).';

-- =============================================================================
-- Procedimiento de registro.
-- RegistrarClasificacion toca TRES tablas (clasificadores, clientes_servidos,
-- clasificaciones_cloud). Hacerlo desde Python en tres viajes deja ventanas en
-- las que el contador ya subio pero la clasificacion fallo. Aqui es una sola
-- transaccion y un solo viaje.
--
-- Los errores se levantan con ERRCODE especifico para que la capa SOAP los
-- traduzca a un Fault distinto sin tener que interpretar textos.
-- =============================================================================
CREATE OR REPLACE FUNCTION fn_registrar_clasificacion(
    p_nombre        VARCHAR,
    p_apellidos     VARCHAR,
    p_correo        VARCHAR,
    p_concepto_id   INTEGER,
    p_isbn          VARCHAR,
    p_modelo        VARCHAR,
    p_tipo_cliente  VARCHAR DEFAULT NULL,
    p_id_cliente    VARCHAR DEFAULT NULL
)
RETURNS TABLE (
    clasificacion_id     INTEGER,
    clasificador_id      INTEGER,
    libro_id             INTEGER,
    termino              VARCHAR,
    libro                VARCHAR,
    clasificado_en       TIMESTAMPTZ,
    peticiones_atendidas INTEGER
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_clasificador INTEGER;
    v_libro        INTEGER;
    v_cliente      INTEGER := NULL;
    v_peticiones   INTEGER := 0;
    v_nuevo        INTEGER;
BEGIN
    IF p_modelo NOT IN ('IaaS', 'PaaS', 'SaaS', 'FaaS') THEN
        RAISE EXCEPTION 'MODELO_INVALIDO: %', p_modelo
            USING ERRCODE = 'check_violation';
    END IF;

    -- El libro se identifica por ISBN, que es lo que expone el contrato. El id
    -- interno nunca sale del servidor.
    SELECT l.id INTO v_libro FROM libros l WHERE l.isbn = p_isbn;
    IF v_libro IS NULL THEN
        RAISE EXCEPTION 'LIBRO_INEXISTENTE: %', p_isbn
            USING ERRCODE = 'no_data_found';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM libros_conceptos lc
                   WHERE lc.libro_id = v_libro AND lc.concepto_id = p_concepto_id) THEN
        RAISE EXCEPTION 'CONCEPTO_INEXISTENTE: % en %', p_concepto_id, p_isbn
            USING ERRCODE = 'no_data_found';
    END IF;

    -- Alta implicita del clasificador: la GUI captura sus datos en cada envio y
    -- el correo es la clave natural. Si ya existe, se refrescan nombre y
    -- apellidos por si los corrigio.
    INSERT INTO clasificadores (nombre, apellidos, correo)
    VALUES (btrim(p_nombre), btrim(p_apellidos), lower(btrim(p_correo)))
    ON CONFLICT (correo) DO UPDATE
        SET nombre = EXCLUDED.nombre, apellidos = EXCLUDED.apellidos
    RETURNING id INTO v_clasificador;

    IF p_tipo_cliente IS NOT NULL AND p_id_cliente IS NOT NULL THEN
        INSERT INTO clientes_servidos (tipo_cliente, identificador, peticiones_atendidas)
        VALUES (p_tipo_cliente, p_id_cliente, 1)
        ON CONFLICT (tipo_cliente, identificador) DO UPDATE
            SET peticiones_atendidas = clientes_servidos.peticiones_atendidas + 1,
                ultima_peticion      = NOW()
        RETURNING id, clientes_servidos.peticiones_atendidas
            INTO v_cliente, v_peticiones;
    END IF;

    -- La duplicidad la detecta uq_clasificacion_no_repetida, no un SELECT
    -- previo: entre el SELECT y el INSERT cabe otra peticion concurrente.
    BEGIN
        INSERT INTO clasificaciones_cloud
               (clasificador_id, libro_id, concepto_id, modelo, cliente_servido_id)
        VALUES (v_clasificador, v_libro, p_concepto_id, p_modelo, v_cliente)
        RETURNING id INTO v_nuevo;
    EXCEPTION WHEN unique_violation THEN
        RAISE EXCEPTION 'CLASIFICACION_DUPLICADA: concepto % por %',
              p_concepto_id, p_correo
            USING ERRCODE = 'unique_violation';
    END;

    RETURN QUERY
    SELECT v_nuevo, v_clasificador, v_libro, co.termino, l.titulo,
           cc.clasificado_en, v_peticiones
    FROM clasificaciones_cloud cc
    JOIN conceptos co ON co.id = cc.concepto_id
    JOIN libros    l  ON l.id  = cc.libro_id
    WHERE cc.id = v_nuevo;
END;
$$;

COMMENT ON FUNCTION fn_registrar_clasificacion IS
    'Registra una clasificacion Cloud en una sola transaccion: alta del clasificador, contador del cliente y el hecho.';

COMMIT;

-- =============================================================================
-- Minimo privilegio (Parte 8 del enunciado).
--
-- El modulo SOAP NO usa postgres ni libreria_app. Usa libreria_soap, que:
--   * LEE solo las columnas del monolito que el contrato necesita.
--   * ESCRIBE unicamente en sus tres tablas propias.
--   * No puede borrar nada, ni en sus tablas ni en las del monolito.
--   * No tiene ningun permiso sobre usuarios: ni SELECT.
--
-- Los GRANT de columna son deliberados: aunque alguien lograra inyectar SQL,
-- no podria leer password_hash porque el rol no tiene permiso sobre esa tabla.
-- =============================================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'libreria_soap') THEN
        -- Sin contrasena aqui: se asigna fuera del repositorio (ver abajo).
        CREATE ROLE libreria_soap WITH LOGIN
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION;
        RAISE NOTICE 'Rol libreria_soap creado. Asignale contrasena antes de usarlo.';
    ELSE
        RAISE NOTICE 'El rol libreria_soap ya existia.';
    END IF;
END $$;

-- El nombre de la base se toma de la conexion actual, no se escribe a mano: asi
-- el script sirve igual en una instalacion que la llame distinto.
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO libreria_soap',
                   current_database());
END $$;
GRANT USAGE   ON SCHEMA public        TO libreria_soap;

-- Lectura del monolito: solo las columnas que el contrato expone.
GRANT SELECT (id, isbn, titulo, categoria_id)      ON libros           TO libreria_soap;
GRANT SELECT (id, termino)                         ON conceptos        TO libreria_soap;
GRANT SELECT (libro_id, concepto_id, definicion, capitulo, pagina)
                                                   ON libros_conceptos TO libreria_soap;
GRANT SELECT (id, nombre)                          ON categorias       TO libreria_soap;

-- Ni SELECT sobre usuarios. Explicito, para que se lea en la auditoria.
REVOKE ALL ON usuarios FROM libreria_soap;

-- Vistas de lectura del modulo.
GRANT SELECT ON v_conceptos_clasificables, v_conceptos_pendientes,
                v_progreso_clasificadores, v_estadisticas_modelo
    TO libreria_soap;

-- Tablas propias: leer, insertar y actualizar. DELETE deliberadamente ausente:
-- una clasificacion es un registro de auditoria; se corrige con otra fila, no
-- borrando la anterior.
GRANT SELECT, INSERT, UPDATE ON clasificadores, clasificaciones_cloud,
                                clientes_servidos TO libreria_soap;
GRANT USAGE, SELECT ON SEQUENCE clasificadores_id_seq,
                                clasificaciones_cloud_id_seq,
                                clientes_servidos_id_seq TO libreria_soap;

GRANT EXECUTE ON FUNCTION fn_registrar_clasificacion(
    VARCHAR, VARCHAR, VARCHAR, INTEGER, VARCHAR, VARCHAR, VARCHAR, VARCHAR)
    TO libreria_soap;

-- -----------------------------------------------------------------------------
-- La contrasena del rol NO va en este archivo ni en ningun otro versionado.
-- Asignala en la VM, en una sesion de psql, y ponla en el .env del modulo:
--
--     \password libreria_soap
--
-- \password la pide de forma interactiva y no la deja en ~/.psql_history.
-- -----------------------------------------------------------------------------

-- -----------------------------------------------------------------------------
-- Alinear el dueno de los objetos del modulo con el del monolito.
--
-- Este script corre como superusuario, asi que por omision todo lo que crea
-- queda a nombre de postgres, mientras que las tablas del monolito pertenecen a
-- otro rol. Esa mezcla obliga a ser superusuario para cualquier ALTER futuro y
-- es la clase de detalle que nadie recuerda seis meses despues.
--
-- El dueno NO se escribe a mano: se deduce del dueno real de la tabla libros. La
-- documentacion del repositorio hablaba de libreria_owner y la instalacion usa
-- libreria_user; preguntarle a la base evita volver a equivocarse.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_dueno text;
    v_objeto text;
BEGIN
    SELECT tableowner INTO v_dueno
    FROM pg_tables WHERE schemaname = 'public' AND tablename = 'libros';

    IF v_dueno IS NULL THEN
        RAISE NOTICE 'No se encontro la tabla libros: se omite el ajuste de dueno.';
        RETURN;
    END IF;
    IF v_dueno = current_user THEN
        RAISE NOTICE 'Los objetos ya pertenecen a %: no hay nada que ajustar.', v_dueno;
        RETURN;
    END IF;

    FOREACH v_objeto IN ARRAY ARRAY['clasificadores', 'clasificaciones_cloud',
                                    'clientes_servidos'] LOOP
        EXECUTE format('ALTER TABLE %I OWNER TO %I', v_objeto, v_dueno);
    END LOOP;

    FOREACH v_objeto IN ARRAY ARRAY['v_conceptos_clasificables',
                                    'v_conceptos_pendientes',
                                    'v_progreso_clasificadores',
                                    'v_estadisticas_modelo'] LOOP
        EXECUTE format('ALTER VIEW %I OWNER TO %I', v_objeto, v_dueno);
    END LOOP;

    -- Las secuencias de las columnas SERIAL siguen a su tabla.
    EXECUTE format('ALTER FUNCTION fn_registrar_clasificacion(
        VARCHAR, VARCHAR, VARCHAR, INTEGER, VARCHAR, VARCHAR, VARCHAR, VARCHAR)
        OWNER TO %I', v_dueno);

    RAISE NOTICE 'Objetos del modulo reasignados a %.', v_dueno;
END $$;

-- Inventario de control.
SELECT relname AS objeto, relkind AS tipo
FROM pg_class
WHERE relname IN ('clasificadores', 'clasificaciones_cloud', 'clientes_servidos',
                  'v_conceptos_clasificables', 'v_conceptos_pendientes',
                  'v_progreso_clasificadores', 'v_estadisticas_modelo')
ORDER BY 1;

SELECT (SELECT count(*) FROM v_conceptos_clasificables) AS conceptos_clasificables,
       (SELECT count(*) FROM v_conceptos_pendientes)    AS pendientes,
       (SELECT count(*) FROM clasificaciones_cloud)     AS clasificaciones;

-- =============================================================================
-- 20261004-pedidos-pagos.sql   [APLICADO en la VM el 2026-10-04]
--
-- QUE HACE
--   Crea el soporte de datos de los microservicios Pedidos y Pagos: tres
--   catalogos (estados_pedido, estados_pago, metodos_pago), las tablas pedidos,
--   pedidos_lineas, pedidos_estados_historial y pagos, la vista v_pedidos_total
--   y el trigger que mantiene el historial de estados.
--
-- POR QUE
--   Hasta ahora la base no tenia nada de pedidos ni de pagos. Los servicios
--   apps/services/pedidos y apps/services/pagos escriben aqui con el rol
--   libreria_app. El stock NO se toca en este archivo: vive en libros.stock y
--   los servicios lo ajustan con sp_ajustar_stock en la misma transaccion que
--   crea o cancela el pedido.
--
-- Se ejecuta como el DUENO del esquema (el mismo que creo libros y usuarios),
-- no como libreria_app. No toca ninguna tabla existente.
--
-- NORMALIZACION HASTA 4FN (tabla por tabla)
--   Criterios: valores de dominio en catalogos con FK (no texto repetido);
--   ningun dato derivado almacenado; cada hecho multivaluado independiente en
--   su propia tabla; claves candidatas declaradas.
--
--   estados_pedido, estados_pago, metodos_pago
--       Clave: id (y nombre, UNIQUE). Un solo atributo dependiente. 4FN.
--   pedidos
--       Clave: id. Dependen de ella usuario_id, estado_id, creado_en, y nada
--       mas. No hay `total`: es derivado de las lineas y se calcula en
--       v_pedidos_total. No hay historial de estados dentro: ver abajo.
--   pedidos_lineas
--       Clave: (pedido_id, libro_id). cantidad y precio_unitario dependen de la
--       clave completa. precio_unitario es el precio pactado al comprar (hecho
--       historico, no una copia derivable de libros.precio, que cambia). Sin
--       subtotal almacenado.
--   pedidos_estados_historial
--       Clave: (pedido_id, cambiado_en). Las transiciones de estado son un
--       hecho multivaluado independiente de las lineas del pedido (un pedido
--       tiene N lineas y, aparte, M cambios de estado, sin relacion entre
--       ambos conjuntos). Mezclarlos en una tabla violaria la 4FN, por eso son
--       tablas distintas.
--   pagos
--       Clave: id. monto, metodo, estado y referencia son hechos del pago; un
--       pedido puede tener varios pagos (reintentos o parciales), de ahi la
--       tabla aparte con FK a pedidos.
--   Ninguna tabla tiene dependencias multivaluadas no triviales ni
--   dependencias transitivas entre atributos no clave.
--
-- CREDENCIALES
--   Ninguna. Solo se otorgan permisos al rol libreria_app, sin contrasenas.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Catalogos
-- ---------------------------------------------------------------------------
CREATE TABLE estados_pedido (
    id      SMALLSERIAL PRIMARY KEY,
    nombre  VARCHAR(20) NOT NULL,
    CONSTRAINT ux_estados_pedido_nombre UNIQUE (nombre),
    CONSTRAINT ck_estados_pedido_nombre CHECK (btrim(nombre) <> '')
);

CREATE TABLE estados_pago (
    id      SMALLSERIAL PRIMARY KEY,
    nombre  VARCHAR(20) NOT NULL,
    CONSTRAINT ux_estados_pago_nombre UNIQUE (nombre),
    CONSTRAINT ck_estados_pago_nombre CHECK (btrim(nombre) <> '')
);

CREATE TABLE metodos_pago (
    id      SMALLSERIAL PRIMARY KEY,
    nombre  VARCHAR(30) NOT NULL,
    CONSTRAINT ux_metodos_pago_nombre UNIQUE (nombre),
    CONSTRAINT ck_metodos_pago_nombre CHECK (btrim(nombre) <> '')
);

INSERT INTO estados_pedido (nombre) VALUES
    ('pendiente'), ('pagado'), ('enviado'), ('cancelado');
INSERT INTO estados_pago (nombre) VALUES
    ('pendiente'), ('aprobado'), ('rechazado'), ('reembolsado');
INSERT INTO metodos_pago (nombre) VALUES
    ('tarjeta'), ('transferencia'), ('efectivo');

-- ---------------------------------------------------------------------------
-- Pedidos
-- ---------------------------------------------------------------------------
-- usuario_id es RESTRICT: un usuario con pedidos no se borra, se desactiva
-- (usuarios.activo = false). El servicio Users lo hace asi.
CREATE TABLE pedidos (
    id          SERIAL PRIMARY KEY,
    usuario_id  INTEGER     NOT NULL,
    estado_id   SMALLINT    NOT NULL,
    creado_en   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_pedidos_usuario FOREIGN KEY (usuario_id)
        REFERENCES usuarios (id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_pedidos_estado FOREIGN KEY (estado_id)
        REFERENCES estados_pedido (id) ON UPDATE CASCADE ON DELETE RESTRICT
);
CREATE INDEX ix_pedidos_usuario ON pedidos (usuario_id);
CREATE INDEX ix_pedidos_estado  ON pedidos (estado_id);

CREATE TABLE pedidos_lineas (
    pedido_id        INTEGER       NOT NULL,
    libro_id         INTEGER       NOT NULL,
    cantidad         INTEGER       NOT NULL,
    precio_unitario  NUMERIC(10,2) NOT NULL,
    CONSTRAINT pk_pedidos_lineas PRIMARY KEY (pedido_id, libro_id),
    CONSTRAINT ck_lineas_cantidad CHECK (cantidad > 0),
    CONSTRAINT ck_lineas_precio   CHECK (precio_unitario >= 0),
    CONSTRAINT fk_lineas_pedido FOREIGN KEY (pedido_id)
        REFERENCES pedidos (id) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_lineas_libro FOREIGN KEY (libro_id)
        REFERENCES libros (id) ON UPDATE CASCADE ON DELETE RESTRICT
);
CREATE INDEX ix_lineas_libro ON pedidos_lineas (libro_id);

CREATE TABLE pedidos_estados_historial (
    pedido_id    INTEGER     NOT NULL,
    cambiado_en  TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    estado_id    SMALLINT    NOT NULL,
    cambiado_por INTEGER,
    CONSTRAINT pk_pedidos_estados_historial PRIMARY KEY (pedido_id, cambiado_en),
    CONSTRAINT fk_hist_pedido FOREIGN KEY (pedido_id)
        REFERENCES pedidos (id) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_hist_estado FOREIGN KEY (estado_id)
        REFERENCES estados_pedido (id) ON UPDATE CASCADE ON DELETE RESTRICT,
    -- SET NULL: borrar a quien hizo el cambio no debe borrar la historia.
    CONSTRAINT fk_hist_usuario FOREIGN KEY (cambiado_por)
        REFERENCES usuarios (id) ON UPDATE CASCADE ON DELETE SET NULL
);

-- El estado actual vive en pedidos.estado_id; cada alta o cambio deja una fila
-- en el historial. El servicio puede indicar quien cambia con
--     SET LOCAL app.usuario_id = '<id>';
-- dentro de la transaccion. Sin eso, cambiado_por queda NULL.
CREATE OR REPLACE FUNCTION fn_pedido_historial()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' OR NEW.estado_id IS DISTINCT FROM OLD.estado_id THEN
        INSERT INTO pedidos_estados_historial (pedido_id, estado_id, cambiado_por)
        VALUES (NEW.id, NEW.estado_id,
                NULLIF(current_setting('app.usuario_id', true), '')::INTEGER);
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_pedido_historial ON pedidos;
CREATE TRIGGER trg_pedido_historial
    AFTER INSERT OR UPDATE OF estado_id ON pedidos
    FOR EACH ROW EXECUTE FUNCTION fn_pedido_historial();

-- ---------------------------------------------------------------------------
-- Pagos
-- ---------------------------------------------------------------------------
CREATE TABLE pagos (
    id              SERIAL PRIMARY KEY,
    pedido_id       INTEGER       NOT NULL,
    metodo_pago_id  SMALLINT      NOT NULL,
    estado_pago_id  SMALLINT      NOT NULL,
    monto           NUMERIC(10,2) NOT NULL,
    referencia      VARCHAR(60),
    creado_en       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_pagos_monto CHECK (monto > 0),
    CONSTRAINT ux_pagos_referencia UNIQUE (referencia),
    CONSTRAINT fk_pagos_pedido FOREIGN KEY (pedido_id)
        REFERENCES pedidos (id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_pagos_metodo FOREIGN KEY (metodo_pago_id)
        REFERENCES metodos_pago (id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_pagos_estado FOREIGN KEY (estado_pago_id)
        REFERENCES estados_pago (id) ON UPDATE CASCADE ON DELETE RESTRICT
);
CREATE INDEX ix_pagos_pedido ON pagos (pedido_id);

-- ---------------------------------------------------------------------------
-- Vista: total y pagado de cada pedido (derivados, nunca almacenados)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_pedidos_total AS
SELECT p.id,
       p.usuario_id,
       ep.nombre AS estado,
       p.creado_en,
       COALESCE(l.total, 0)  AS total,
       COALESCE(g.pagado, 0) AS pagado
FROM pedidos p
JOIN estados_pedido ep ON ep.id = p.estado_id
LEFT JOIN (SELECT pedido_id, SUM(cantidad * precio_unitario) AS total
           FROM pedidos_lineas GROUP BY pedido_id) l ON l.pedido_id = p.id
LEFT JOIN (SELECT pg.pedido_id, SUM(pg.monto) AS pagado
           FROM pagos pg
           JOIN estados_pago es ON es.id = pg.estado_pago_id
           WHERE es.nombre = 'aprobado'
           GROUP BY pg.pedido_id) g ON g.pedido_id = p.id;

-- ---------------------------------------------------------------------------
-- Permisos: libreria_app lee y escribe filas, nada de DDL. Los catalogos son
-- de solo lectura para el servicio.
-- ---------------------------------------------------------------------------
GRANT SELECT ON estados_pedido, estados_pago, metodos_pago TO libreria_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON
    pedidos, pedidos_lineas, pedidos_estados_historial, pagos TO libreria_app;
GRANT SELECT ON v_pedidos_total TO libreria_app;
GRANT USAGE, SELECT ON SEQUENCE pedidos_id_seq, pagos_id_seq TO libreria_app;

COMMIT;

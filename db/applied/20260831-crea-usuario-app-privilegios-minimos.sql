-- =============================================================================
-- 20260831-crea-usuario-app-privilegios-minimos.sql
--
-- QUÉ HACE
-- Crea el rol `libreria_app`, que es con el que se conectará la aplicación, y
-- le otorga únicamente permiso para leer y escribir FILAS. No es dueño de
-- ninguna tabla, así que no puede ejecutar DROP ni ALTER.
--
-- `libreria_user` se conserva tal cual: sigue siendo el dueño del esquema y es
-- quien ejecuta los scripts de db/. Deja de usarse desde la aplicación.
--
-- POR QUÉ
-- Hoy la aplicación se conecta con el dueño de las tablas. Eso significa que un
-- fallo en la aplicación —una inyección que llegara a ejecutarse, o un error de
-- programación— podría destruir el esquema completo. Separando los dos roles, el
-- daño máximo posible pasa a ser sobre los datos, nunca sobre la estructura:
-- PostgreSQL rechaza el DROP aunque la sentencia llegue a ejecutarse.
--
-- Es el principio de mínimo privilegio que pide el ejercicio, y es lo que
-- documentan docs/ENGINEERING_DECISIONS.md (DEC-12) y docs/SECURITY_REVIEW.md.
--
-- CUÁNDO EJECUTARLO
-- DESPUÉS de 20260830-rediseno-4fn.sql. Los GRANT sobre "todas las tablas"
-- sólo alcanzan a las que existen en ese momento, así que el esquema tiene que
-- estar ya creado. Los ALTER DEFAULT PRIVILEGES del final cubren lo que se cree
-- de aquí en adelante, para no repetir esto en cada cambio de esquema.
--
-- CÓMO EJECUTARLO
-- Requiere un rol capaz de crear roles, así que va como superusuario:
--
--     cd /opt/udem/libreria
--     sudo -u postgres psql -d libreria_db \
--       -f db/pending/20260831-crea-usuario-app-privilegios-minimos.sql
--
-- Pedirá la contraseña del rol nuevo con \password, que NO la muestra al
-- escribirla y además la envía ya cifrada con SCRAM: el texto plano no viaja
-- por la conexión ni queda en los logs del servidor.
--
-- NO la escribas en ningún archivo: va únicamente en el .env de la VM, que no
-- se versiona. Genera una larga y aleatoria, por ejemplo con:
--     node -e "console.log(require('crypto').randomBytes(18).toString('base64url'))"
--
-- Se usa \password y no \prompt porque \prompt SÍ hace eco de lo que se
-- teclea: la contraseña quedaría escrita en la pantalla y en el scrollback de
-- la terminal, que es exactamente lo que este proyecto trata de evitar.
-- =============================================================================

-- Idempotente: si el rol ya existe, sólo se le fija la contraseña.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'libreria_app') THEN
        CREATE ROLE libreria_app WITH LOGIN
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION;
        RAISE NOTICE 'Rol libreria_app creado.';
    ELSE
        RAISE NOTICE 'El rol libreria_app ya existia; se actualiza su contrasena.';
    END IF;
END $$;

-- Entrada oculta, y la contraseña se transmite ya cifrada.
\password libreria_app

-- Puede conectarse a la base y usar el esquema, pero NO crear objetos en él.
-- Se usa current_database() en lugar del nombre escrito a mano, para que el
-- script funcione tal cual aunque la base se llame de otra forma.
DO $$ BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO libreria_app', current_database());
END $$;
GRANT USAGE ON SCHEMA public TO libreria_app;

-- En PostgreSQL 14 y anteriores, el esquema `public` concede CREATE al
-- pseudo-rol PUBLIC, es decir, a cualquier usuario que pueda conectarse.
-- Revocarlo sólo de libreria_app no serviría de nada: el permiso le seguiría
-- llegando por herencia de PUBLIC. Hay que quitárselo a PUBLIC y devolvérselo
-- explícitamente al dueño del esquema, que es quien sí debe poder crear tablas.
-- (PostgreSQL 15+ ya trae este comportamiento por omisión; ejecutarlo igual no
-- hace daño.)
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM libreria_app;
GRANT  CREATE ON SCHEMA public TO libreria_user;

-- Permisos sobre lo que YA existe.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA public TO libreria_app;
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA public TO libreria_app;
GRANT EXECUTE                        ON ALL FUNCTIONS IN SCHEMA public TO libreria_app;

-- Y sobre lo que libreria_user cree en el futuro. Sin esto, cada vez que se
-- recreara el esquema habría que volver a otorgar permisos a mano.
ALTER DEFAULT PRIVILEGES FOR ROLE libreria_user IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO libreria_app;
ALTER DEFAULT PRIVILEGES FOR ROLE libreria_user IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO libreria_app;
ALTER DEFAULT PRIVILEGES FOR ROLE libreria_user IN SCHEMA public
    GRANT EXECUTE ON FUNCTIONS TO libreria_app;

-- Comprobación de que los permisos quedaron realmente aplicados: debe listar
-- las 11 tablas con los cuatro privilegios de fila.
SELECT count(*) AS objetos_con_permiso_de_lectura
FROM information_schema.role_table_grants
WHERE grantee = 'libreria_app' AND privilege_type = 'SELECT'
  AND table_schema = 'public';

-- Debe devolver f: libreria_app no puede crear objetos en el esquema.
SELECT has_schema_privilege('libreria_app', 'public', 'CREATE') AS app_puede_crear_objetos,
       has_schema_privilege('libreria_user', 'public', 'CREATE') AS dueno_puede_crear_objetos;

-- =============================================================================
-- VERIFICACIÓN
-- libreria_app no debe tener ningún atributo de privilegio, y no debe ser
-- dueño de ninguna tabla.
-- =============================================================================

SELECT rolname, rolsuper AS superusuario, rolcreatedb, rolcreaterole, rolcanlogin
FROM pg_roles
WHERE rolname IN ('libreria_app', 'libreria_user')
ORDER BY rolname;

SELECT tableowner AS dueno_de_las_tablas, count(*) AS tablas
FROM pg_tables
WHERE schemaname = 'public'
GROUP BY tableowner;

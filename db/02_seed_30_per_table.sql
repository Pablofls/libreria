-- =============================================================================
-- 02_seed_30_per_table.sql
-- Datos sinteticos: 30 filas por tabla base, suficientes para ejercitar
-- busquedas, paginacion visual, relaciones N:M y las pruebas del plan.
--
--     psql -U libreria_owner -d libreria_db -f db/02_seed_30_per_table.sql
--
-- Las contrasenas NO aparecen en este archivo, ni en claro ni en comentarios.
-- Solo se almacena el hash bcrypt (cost 10, el mismo factor que usa
-- src/modules/auth/auth.model.js). Los valores se comunican fuera del
-- repositorio. El repositorio es publico: ver docs/SECURITY_REVIEW.md.
-- =============================================================================

BEGIN;

-- Idempotente: vacia las tablas y reinicia los SERIAL antes de sembrar.
TRUNCATE libros_conceptos, libros_generos, libros_autores, imagenes_libros,
         conceptos, libros, formatos, categorias, generos, autores, usuarios,
         personas
    RESTART IDENTITY CASCADE;

-- personas: la persona que hay detras de cada cuenta. Se siembra ANTES que
-- usuarios porque usuarios.persona_id la referencia.
--
-- Los ids van explicitos y no autogenerados: los disparadores que sincronizan
-- personas con usuarios.nombre se crean en 05_triggers.sql, que corre DESPUES
-- de este archivo, asi que aqui nadie rellena persona_id por nosotros. Es la
-- misma clase de detalle que las imagenes con es_portada de mas abajo: el orden
-- de los scripts canonicos manda, y este archivo se apana solo.
--
-- Casi todos los lectores van sin apellido materno, y es deliberado: es
-- exactamente lo que produce el backfill de
-- db/applied/20260921-separa-nombre-en-personas.sql sobre los nombres que ya
-- existen en la VM. Si aqui se inventaran apellidos maternos, una base recreada
-- desde cero y la base migrada dejarian de parecerse. Las primeras filas con
-- los tres campos llegan por POST /register del microservicio de login.
INSERT INTO personas (id, nombre, apellido_paterno, apellido_materno) VALUES
( 1, 'Administrador', NULL,         NULL),
( 2, 'Ana',          'Ruiz',       NULL),
( 3, 'Bruno',        'Salas',      NULL),
( 4, 'Carla',        'Mendoza',    NULL),
( 5, 'Diego',        'Fuentes',    NULL),
( 6, 'Elena',        'Ortiz',      NULL),
( 7, 'Fabian',       'Rojas',      NULL),
( 8, 'Gabriela',     'Nunez',      NULL),
( 9, 'Hector',       'Vidal',      NULL),
(10, 'Irene',        'Campos',     NULL),
(11, 'Javier',       'Pena',       NULL),
(12, 'Karla',        'Espino',     NULL),
(13, 'Luis',         'Trevino',    NULL),
(14, 'Marina',       'Cuevas',     NULL),
(15, 'Nestor',       'Aguilar',    NULL),
(16, 'Olivia',       'Bravo',      NULL),
(17, 'Pablo',        'Zamora',     NULL),
(18, 'Quetzalli',    'Rios',       NULL),
(19, 'Raul',         'Barrera',    NULL),
(20, 'Sofia',        'Lugo',       NULL),
(21, 'Tomas',        'Ibarra',     NULL),
(22, 'Ursula',       'Nava',       NULL),
(23, 'Victor',       'Palacios',   NULL),
(24, 'Wendy',        'Sandoval',   NULL),
(25, 'Ximena',       'Duarte',     NULL),
(26, 'Yahir',        'Montes',     NULL),
(27, 'Zoe',          'Carranza',   NULL),
(28, 'Adrian',       'Lozano',     NULL),
(29, 'Beatriz',      'Fierro',     NULL),
(30, 'Cesar',        'Villalobos', NULL);
SELECT setval(pg_get_serial_sequence('personas', 'id'), (SELECT max(id) FROM personas));

-- usuarios: 1 administrador (la BD impide un segundo) + 29 lectores.
-- `nombre` es la copia derivada del nombre completo de la persona; se escribe
-- a mano por lo mismo que persona_id: los triggers de 05 todavia no existen.
-- El administrador usa admin@libreria.com; los lectores, un dominio distinto.
-- No es un descuido: refleja el estado real de la instalacion. El correo del
-- administrador se cambio desde la interfaz y el seed se alineo con eso, en vez
-- de al reves, para que este archivo describa lo que de verdad hay en la VM.
INSERT INTO usuarios (persona_id, nombre, email, password_hash, rol) VALUES
( 1, 'Administrador', 'admin@libreria.com', '$2b$10$c/yES5ffi.7RI/BtxEDfhezl6Sc39xn9JnMyyuGYH3GTtIjXVi.vG', 'admin'),
( 2, 'Ana Ruiz', 'ana.ruiz@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
( 3, 'Bruno Salas', 'bruno.salas@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
( 4, 'Carla Mendoza', 'carla.mendoza@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
( 5, 'Diego Fuentes', 'diego.fuentes@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
( 6, 'Elena Ortiz', 'elena.ortiz@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
( 7, 'Fabian Rojas', 'fabian.rojas@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
( 8, 'Gabriela Nunez', 'gabriela.nunez@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
( 9, 'Hector Vidal', 'hector.vidal@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(10, 'Irene Campos', 'irene.campos@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(11, 'Javier Pena', 'javier.pena@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(12, 'Karla Espino', 'karla.espino@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(13, 'Luis Trevino', 'luis.trevino@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(14, 'Marina Cuevas', 'marina.cuevas@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(15, 'Nestor Aguilar', 'nestor.aguilar@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(16, 'Olivia Bravo', 'olivia.bravo@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(17, 'Pablo Zamora', 'pablo.zamora@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(18, 'Quetzalli Rios', 'quetzalli.rios@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(19, 'Raul Barrera', 'raul.barrera@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(20, 'Sofia Lugo', 'sofia.lugo@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(21, 'Tomas Ibarra', 'tomas.ibarra@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(22, 'Ursula Nava', 'ursula.nava@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(23, 'Victor Palacios', 'victor.palacios@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(24, 'Wendy Sandoval', 'wendy.sandoval@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(25, 'Ximena Duarte', 'ximena.duarte@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(26, 'Yahir Montes', 'yahir.montes@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(27, 'Zoe Carranza', 'zoe.carranza@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(28, 'Adrian Lozano', 'adrian.lozano@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(29, 'Beatriz Fierro', 'beatriz.fierro@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector'),
(30, 'Cesar Villalobos', 'cesar.villalobos@libreria.udem.mx', '$2b$10$9znBNGqfsAR.ZMwkoGPhlOGE5zkXDuDO/0wA9VRBEP5LcYY1Drr5q', 'lector');

-- autores: 30. UNIQUE(nombre, nacionalidad) impide capturar dos veces al mismo.
INSERT INTO autores (nombre, biografia, nacionalidad) VALUES
('Andrew S. Tanenbaum', 'Autor de referencia en sistemas operativos y redes de computadoras.', 'Neerlandesa'),
('Martin Fowler', 'Autor sobre refactorizacion y arquitectura de software empresarial.', 'Britanica'),
('Robert C. Martin', 'Divulgador de practicas de codigo limpio y diseno orientado a objetos.', 'Estadounidense'),
('Erich Gamma', 'Coautor del catalogo de patrones de diseno de la Banda de los Cuatro.', 'Suiza'),
('Richard Helm', 'Coautor del catalogo de patrones de diseno de la Banda de los Cuatro.', 'Australiana'),
('Ralph Johnson', 'Coautor del catalogo de patrones de diseno y academico en Illinois.', 'Estadounidense'),
('John Vlissides', 'Coautor del catalogo de patrones de diseno de la Banda de los Cuatro.', 'Estadounidense'),
('Thomas Erl', 'Autor sobre arquitectura orientada a servicios y computo en la nube.', 'Canadiense'),
('Ricardo Puttini', 'Coautor de obras sobre arquitectura de computo en la nube.', 'Brasilena'),
('Zaigham Mahmood', 'Coautor y editor de obras sobre computo en la nube.', 'Britanica'),
('Sam Newman', 'Autor sobre construccion y migracion de microservicios.', 'Britanica'),
('Gene Kim', 'Autor sobre cultura DevOps y flujo de entrega de software.', 'Estadounidense'),
('Nicole Forsgren', 'Investigadora sobre metricas de desempeno en entrega de software.', 'Estadounidense'),
('Jez Humble', 'Autor sobre entrega continua y automatizacion de despliegue.', 'Britanica'),
('Michael Stonebraker', 'Investigador en sistemas de bases de datos relacionales.', 'Estadounidense'),
('Edgar F. Codd', 'Formulo el modelo relacional y las primeras formas normales.', 'Britanica'),
('Chris J. Date', 'Divulgador del modelo relacional y la teoria de normalizacion.', 'Britanica'),
('Hector Garcia-Molina', 'Investigador en sistemas de bases de datos distribuidos.', 'Mexicana'),
('Jennifer Widom', 'Investigadora y docente en sistemas de bases de datos.', 'Estadounidense'),
('Jeffrey D. Ullman', 'Investigador en teoria de bases de datos y compiladores.', 'Estadounidense'),
('Bruce Schneier', 'Autor sobre criptografia aplicada y seguridad de sistemas.', 'Estadounidense'),
('Ross Anderson', 'Autor sobre ingenieria de seguridad de sistemas distribuidos.', 'Britanica'),
('Kevin Mitnick', 'Autor sobre ingenieria social y seguridad de la informacion.', 'Estadounidense'),
('Brian W. Kernighan', 'Coautor de obras fundacionales sobre el lenguaje C y Unix.', 'Canadiense'),
('Dennis M. Ritchie', 'Creador del lenguaje C y coautor del sistema Unix.', 'Estadounidense'),
('Donald E. Knuth', 'Autor de la obra de referencia sobre algoritmos y analisis.', 'Estadounidense'),
('Thomas H. Cormen', 'Coautor del texto de referencia sobre algoritmos.', 'Estadounidense'),
('Eric Evans', 'Autor sobre diseno guiado por el dominio.', 'Estadounidense'),
('Kent Beck', 'Autor sobre desarrollo guiado por pruebas y programacion extrema.', 'Estadounidense'),
('Grady Booch', 'Autor sobre analisis y diseno orientado a objetos y UML.', 'Estadounidense');

-- generos: 30. Un libro puede tener varios -> tabla puente libros_generos.
INSERT INTO generos (nombre, descripcion) VALUES
('Computo en la nube', 'Infraestructura, plataformas y servicios entregados bajo demanda.'),
('Arquitectura de software', 'Estructura de alto nivel de los sistemas y sus decisiones de diseno.'),
('Bases de datos', 'Modelado, almacenamiento y recuperacion estructurada de informacion.'),
('Redes de computadoras', 'Protocolos, topologias y comunicacion entre sistemas.'),
('Sistemas operativos', 'Gestion de procesos, memoria, archivos y dispositivos.'),
('Seguridad informatica', 'Proteccion de sistemas, datos y comunicaciones.'),
('Criptografia', 'Tecnicas matematicas para cifrar y autenticar informacion.'),
('Ingenieria de software', 'Procesos y practicas para construir software de forma disciplinada.'),
('Algoritmos', 'Metodos de resolucion y su analisis de complejidad.'),
('Estructuras de datos', 'Organizacion de datos en memoria para acceso eficiente.'),
('Programacion', 'Lenguajes, paradigmas y tecnicas de codificacion.'),
('DevOps', 'Integracion entre desarrollo y operaciones para entrega continua.'),
('Microservicios', 'Descomposicion de sistemas en servicios desplegables por separado.'),
('Patrones de diseno', 'Soluciones reutilizables a problemas recurrentes de diseno.'),
('Diseno orientado a objetos', 'Modelado mediante objetos, herencia y polimorfismo.'),
('Calidad de software', 'Pruebas, metricas y aseguramiento de la calidad.'),
('Pruebas de software', 'Estrategias de verificacion y validacion automatizada.'),
('Inteligencia artificial', 'Sistemas que aprenden, razonan o infieren.'),
('Aprendizaje automatico', 'Modelos que ajustan su comportamiento a partir de datos.'),
('Ciencia de datos', 'Extraccion de conocimiento a partir de conjuntos de datos.'),
('Big data', 'Procesamiento de volumenes de datos que exceden un solo equipo.'),
('Sistemas distribuidos', 'Coordinacion de nodos independientes como un solo sistema.'),
('Virtualizacion', 'Abstraccion de recursos fisicos en recursos logicos.'),
('Contenedores', 'Empaquetado de aplicaciones con sus dependencias aisladas.'),
('Desarrollo web', 'Construccion de aplicaciones accesibles mediante navegador.'),
('Interfaces de usuario', 'Diseno de la interaccion entre persona y sistema.'),
('Compiladores', 'Traduccion de lenguajes de alto nivel a codigo ejecutable.'),
('Teoria de la computacion', 'Modelos formales, computabilidad y complejidad.'),
('Etica y tecnologia', 'Implicaciones sociales y responsabilidad profesional.'),
('Divulgacion tecnica', 'Obras de difusion para publico no especializado.');

-- categorias: 30. Un libro tiene exactamente una -> FK simple en libros.
INSERT INTO categorias (nombre, descripcion) VALUES
('Universitario', 'Bibliografia de curso para licenciatura e ingenieria.'),
('Posgrado', 'Obras de profundizacion para maestria y doctorado.'),
('Referencia tecnica', 'Manuales y obras de consulta permanente.'),
('Certificacion', 'Material de preparacion para examenes de certificacion.'),
('Divulgacion', 'Obras para publico general interesado en tecnologia.'),
('Manual practico', 'Guias paso a paso orientadas a la ejecucion.'),
('Investigacion', 'Compilaciones de articulos y resultados de investigacion.'),
('Historia de la computacion', 'Obras sobre la evolucion de la disciplina.'),
('Biografia tecnica', 'Vidas de figuras relevantes de la computacion.'),
('Ensayo', 'Reflexion argumentada sobre temas tecnologicos.'),
('Compilacion', 'Colecciones de textos de varios autores.'),
('Cuaderno de ejercicios', 'Material con problemas resueltos y propuestos.'),
('Infantil', 'Introduccion a la tecnologia para lectores de primaria.'),
('Juvenil', 'Obras dirigidas a lectores adolescentes.'),
('Autoaprendizaje', 'Material disenado para estudio sin instructor.'),
('Casos de estudio', 'Analisis detallado de implantaciones reales.'),
('Normatividad', 'Estandares, marcos de referencia y cumplimiento.'),
('Gestion de proyectos', 'Planeacion y control de proyectos tecnologicos.'),
('Emprendimiento', 'Creacion de productos y negocios de base tecnologica.'),
('Carrera profesional', 'Desarrollo profesional en tecnologias de la informacion.'),
('Traduccion al espanol', 'Ediciones traducidas de obras originalmente en ingles.'),
('Edicion bilingue', 'Ediciones con texto en dos idiomas.'),
('Edicion conmemorativa', 'Reediciones especiales de obras clasicas.'),
('Libro de texto oficial', 'Titulos adoptados formalmente por un plan de estudios.'),
('Lectura complementaria', 'Material sugerido fuera de la bibliografia obligatoria.'),
('Coleccion UDEM', 'Titulos editados o recomendados por la universidad.'),
('Novedades', 'Titulos publicados en el ano en curso.'),
('Descatalogado', 'Titulos fuera de impresion, disponibles solo en existencia.'),
('Uso interno', 'Material de consulta restringida dentro de la biblioteca.'),
('Donacion', 'Ejemplares incorporados por donacion.');

-- formatos: 30. Catalogo independiente, igual que categorias.
INSERT INTO formatos (nombre, descripcion) VALUES
('Pasta dura', 'Encuadernacion rigida cosida.'),
('Pasta blanda', 'Encuadernacion flexible pegada.'),
('Rustica', 'Encuadernacion economica en rustica.'),
('Empastado en tela', 'Cubierta de tela sobre carton.'),
('Espiral', 'Encuadernacion con espiral metalico o plastico.'),
('Anillado', 'Carpeta de argollas intercambiables.'),
('Grapado', 'Cuadernillo unido con grapas.'),
('Bolsillo', 'Edicion reducida de bajo costo.'),
('Edicion de lujo', 'Papel y acabados de alta calidad.'),
('Gran formato', 'Ediciones de dimensiones superiores al estandar.'),
('EPUB', 'Libro electronico de maquetado reflowable.'),
('PDF', 'Documento electronico de maquetado fijo.'),
('MOBI', 'Formato electronico para lectores Kindle.'),
('AZW3', 'Formato electronico propietario de Amazon.'),
('HTML en linea', 'Version consultable directamente en navegador.'),
('Audiolibro MP3', 'Grabacion de audio comprimida.'),
('Audiolibro M4B', 'Grabacion de audio con capitulos.'),
('CD-ROM', 'Disco optico de datos adjunto o independiente.'),
('DVD-ROM', 'Disco optico de mayor capacidad.'),
('Microfilm', 'Reproduccion fotografica en pelicula.'),
('Facsimil', 'Reproduccion fiel de una edicion historica.'),
('Impresion bajo demanda', 'Ejemplar impreso al momento del pedido.'),
('Braille', 'Edicion en sistema de lectura tactil.'),
('Letra grande', 'Edicion con tipografia ampliada.'),
('Kit multimedia', 'Libro acompanado de material audiovisual.'),
('Fasciculo', 'Entrega parcial de una obra por partes.'),
('Separata', 'Extracto impreso de forma independiente.'),
('Manual de laboratorio', 'Cuaderno de practicas de uso consumible.'),
('Poster tecnico', 'Lamina de referencia rapida.'),
('Acceso web con licencia', 'Consulta en linea mediante suscripcion.');

-- conceptos: 30. Catalogo de terminos. La DEFINICION no vive aqui: cambia
-- segun el libro, asi que es un atributo de la relacion libros_conceptos.
INSERT INTO conceptos (termino) VALUES
('IaaS'),
('PaaS'),
('SaaS'),
('FaaS'),
('Bucket'),
('Public Cloud'),
('Private Cloud'),
('Hybrid Cloud'),
('Multicloud'),
('Serverless'),
('Elasticidad'),
('Autoescalado'),
('Region'),
('Zona de disponibilidad'),
('Tolerancia a fallos'),
('Alta disponibilidad'),
('Balanceador de carga'),
('Maquina virtual'),
('Contenedor'),
('Orquestacion'),
('Reverse proxy'),
('Idempotencia'),
('Latencia'),
('Throughput'),
('Cache'),
('Sharding'),
('Replicacion'),
('Transaccion ACID'),
('Teorema CAP'),
('Normalizacion 4FN');

-- libros: 30. Sin columnas autor_id ni genero_id: esas relaciones son N:M.
INSERT INTO libros (isbn, titulo, anio_publicacion, sinopsis, precio, stock, categoria_id, formato_id) VALUES
('978-0-13-609181-2', 'Cloud Computing: Concepts, Technology and Architecture', 2013, 'Modelo de referencia del computo en la nube: modelos de servicio, modelos de despliegue y los mecanismos que los sustentan.', 1249.00, 14, 1, 1),
('978-1-4919-5035-7', 'Building Microservices', 2015, 'Como descomponer un sistema monolitico en servicios desplegables por separado, y a que costo operativo.', 989.50, 9, 1, 2),
('978-0-321-12742-6', 'Patterns of Enterprise Application Architecture', 2002, 'Catalogo de patrones para la capa de datos, la logica de dominio y la presentacion en aplicaciones empresariales.', 1180.00, 7, 3, 1),
('978-0-201-63361-0', 'Design Patterns: Elements of Reusable Object-Oriented Software', 1994, 'Los veintitres patrones de diseno clasicos, con su intencion, estructura y consecuencias.', 1420.00, 11, 3, 1),
('978-0-13-235088-4', 'Clean Code: A Handbook of Agile Software Craftsmanship', 2008, 'Criterios concretos para escribir codigo que otra persona pueda leer y modificar sin miedo.', 860.00, 22, 1, 2),
('978-0-13-359162-0', 'Modern Operating Systems', 2014, 'Procesos, memoria virtual, sistemas de archivos y seguridad en sistemas operativos contemporaneos.', 1560.00, 6, 24, 1),
('978-0-13-212695-3', 'Computer Networks', 2010, 'Modelo por capas, protocolos de enlace, red, transporte y aplicacion.', 1490.00, 8, 24, 1),
('978-0-13-187325-4', 'Database Systems: The Complete Book', 2008, 'Modelo relacional, algebra, diseno, normalizacion y procesamiento de consultas.', 1720.00, 5, 24, 1),
('978-0-471-11709-4', 'Applied Cryptography', 1996, 'Protocolos, algoritmos y codigo fuente de criptografia aplicada.', 1310.00, 4, 3, 1),
('978-0-470-06852-6', 'Security Engineering', 2008, 'Como construir sistemas distribuidos que sigan siendo confiables bajo ataque.', 1650.00, 3, 2, 1),
('978-0-13-110362-7', 'The C Programming Language', 1988, 'La descripcion original y minima del lenguaje C por sus autores.', 640.00, 18, 3, 8),
('978-0-262-03384-8', 'Introduction to Algorithms', 2009, 'Analisis de complejidad, estructuras de datos, grafos y programacion dinamica.', 1890.00, 10, 24, 1),
('978-0-201-89683-1', 'The Art of Computer Programming, Volume 1', 1997, 'Algoritmos fundamentales y su analisis matematico riguroso.', 2150.00, 2, 2, 9),
('978-0-321-12521-7', 'Domain-Driven Design', 2003, 'Modelar el dominio del negocio como nucleo del diseno del software.', 1240.00, 6, 25, 1),
('978-0-321-14653-3', 'Test-Driven Development: By Example', 2002, 'Ciclo rojo-verde-refactor ilustrado con dos ejemplos completos.', 720.00, 13, 1, 2),
('978-0-321-33025-4', 'Object-Oriented Analysis and Design with Applications', 2007, 'Fundamentos del analisis orientado a objetos y notacion UML.', 1380.00, 5, 1, 1),
('978-1-942788-00-3', 'The Phoenix Project', 2013, 'Novela sobre una crisis de entrega de software y la adopcion de practicas DevOps.', 690.00, 16, 5, 2),
('978-1-942788-33-1', 'Accelerate', 2018, 'Evidencia empirica sobre que practicas de ingenieria predicen el desempeno de una organizacion.', 780.00, 12, 7, 2),
('978-0-321-60191-9', 'Continuous Delivery', 2010, 'Canalizacion de despliegue, automatizacion de pruebas y entrega frecuente y confiable.', 1150.00, 7, 1, 1),
('978-0-13-714476-0', 'Refactoring: Improving the Design of Existing Code', 2018, 'Catalogo de refactorizaciones y como aplicarlas sin romper el comportamiento.', 1290.00, 9, 3, 1),
('978-607-32-1234-5', 'Fundamentos de bases de datos relacionales', 2019, 'Introduccion al modelo relacional, algebra y normalizacion hasta cuarta forma normal.', 520.00, 25, 24, 2),
('978-607-32-2345-6', 'Normalizacion practica hasta 4FN', 2021, 'Recorrido demostrable de 1FN a 4FN con dependencias funcionales y multivaluadas.', 480.00, 20, 24, 2),
('978-607-32-3456-7', 'Despliegue de aplicaciones en la nube publica', 2022, 'Aprovisionamiento de instancias, redes, firewalls y balanceo en proveedores de nube publica.', 610.00, 17, 6, 2),
('978-607-32-4567-8', 'Introduccion a la virtualizacion y los contenedores', 2020, 'Del hipervisor al contenedor: aislamiento, imagenes y orquestacion basica.', 545.00, 15, 1, 2),
('978-607-32-5678-9', 'Seguridad en aplicaciones web', 2023, 'Inyeccion, autenticacion rota, control de acceso y validacion del lado del servidor.', 590.00, 19, 1, 2),
('978-607-32-6789-0', 'PostgreSQL para desarrolladores', 2022, 'Tipos, indices, restricciones, funciones, disparadores y vistas en PostgreSQL.', 575.00, 21, 6, 2),
('978-607-32-7890-1', 'Node.js del lado del servidor', 2023, 'Modelo de eventos, Express, renderizado en servidor y acceso a bases de datos.', 560.00, 23, 6, 2),
('978-607-32-8901-2', 'Arquitectura monolitica bien hecha', 2024, 'Cuando un monolito modular es la decision correcta y como evitar que se pudra.', 620.00, 11, 10, 2),
('978-607-32-9012-3', 'Computacion en la nube para estudiantes', 2024, 'Primer acercamiento a IaaS, PaaS y SaaS con practicas de laboratorio.', 430.00, 27, 13, 28),
('978-607-32-0123-4', 'Historia de la computacion en Mexico', 2021, 'Recorrido por los primeros centros de computo y sus protagonistas.', 395.00, 8, 8, 1);

-- libros_autores: relacion N:M. `orden` es la posicion en la portada y es un
-- atributo DE LA RELACION, no del libro ni del autor.
INSERT INTO libros_autores (libro_id, autor_id, orden) VALUES
(1, 8, 1),
(1, 9, 2),
(1, 10, 3),
(2, 11, 1),
(3, 2, 1),
(4, 4, 1),
(4, 5, 2),
(4, 6, 3),
(4, 7, 4),
(5, 3, 1),
(6, 1, 1),
(7, 1, 1),
(8, 18, 1),
(8, 19, 2),
(8, 20, 3),
(9, 21, 1),
(10, 22, 1),
(11, 24, 1),
(11, 25, 2),
(12, 27, 1),
(13, 26, 1),
(14, 28, 1),
(15, 29, 1),
(16, 30, 1),
(17, 12, 1),
(18, 13, 1),
(18, 12, 2),
(19, 14, 1),
(19, 12, 2),
(20, 2, 1),
(21, 17, 1),
(21, 16, 2),
(22, 16, 1),
(22, 17, 2),
(23, 8, 1),
(24, 8, 1),
(24, 11, 2),
(25, 23, 1),
(25, 22, 2),
(26, 15, 1),
(27, 3, 1),
(28, 2, 1),
(28, 11, 2),
(29, 8, 1),
(29, 10, 2),
(30, 18, 1);

-- libros_generos: segunda relacion N:M, independiente de los autores.
-- Guardar autores y generos en la misma tabla produciria su producto
-- cartesiano: esa es exactamente la violacion de 4FN que se evita aqui.
INSERT INTO libros_generos (libro_id, genero_id) VALUES
(1, 1),
(1, 2),
(1, 23),
(2, 13),
(2, 2),
(3, 2),
(3, 8),
(4, 14),
(4, 15),
(5, 8),
(5, 11),
(6, 5),
(7, 4),
(8, 3),
(9, 7),
(9, 6),
(10, 6),
(10, 22),
(11, 11),
(12, 9),
(12, 10),
(13, 9),
(14, 2),
(14, 8),
(15, 17),
(15, 16),
(16, 15),
(16, 8),
(17, 12),
(18, 12),
(18, 16),
(19, 12),
(19, 8),
(20, 8),
(20, 14),
(21, 3),
(22, 3),
(23, 1),
(23, 12),
(24, 23),
(24, 24),
(25, 6),
(25, 25),
(26, 3),
(27, 25),
(27, 11),
(28, 2),
(28, 13),
(29, 1),
(29, 30),
(30, 29);

-- libros_conceptos: N:M con atributo propio. La definicion pertenece al PAR
-- (libro, concepto): el mismo termino se define distinto en cada libro.
-- Los libros 1 y 29 llevan el glosario de Cloud Computing que pide el ejercicio.
INSERT INTO libros_conceptos (libro_id, concepto_id, definicion, capitulo, pagina) VALUES
(1, 1, 'Infraestructura como Servicio: el proveedor entrega computo, red y almacenamiento virtualizados; el cliente administra el sistema operativo hacia arriba.', 'Capitulo 4', 112),
(1, 2, 'Plataforma como Servicio: el proveedor administra tambien el entorno de ejecucion; el cliente solo aporta la aplicacion y sus datos.', 'Capitulo 4', 118),
(1, 3, 'Software como Servicio: la aplicacion completa se consume por red y el cliente no administra ninguna capa de infraestructura.', 'Capitulo 4', 124),
(1, 4, 'Funcion como Servicio: la unidad de despliegue es una funcion que el proveedor ejecuta y escala en respuesta a eventos.', 'Capitulo 5', 147),
(1, 5, 'Contenedor logico de almacenamiento de objetos, identificado por un nombre unico global y con politicas de acceso propias.', 'Capitulo 6', 178),
(1, 6, 'Nube publica: infraestructura compartida operada por un tercero y accesible por internet.', 'Capitulo 3', 78),
(1, 7, 'Nube privada: infraestructura de uso exclusivo de una organizacion, en sus instalaciones o alojada.', 'Capitulo 3', 83),
(1, 8, 'Nube hibrida: combinacion de nube publica y privada con portabilidad de datos y aplicaciones entre ambas.', 'Capitulo 3', 89),
(1, 9, 'Multinube: uso simultaneo de varios proveedores de nube publica para evitar dependencia de uno solo.', 'Capitulo 3', 95),
(1, 10, 'Sin servidor: modelo en el que el desarrollador no aprovisiona ni administra servidores; el proveedor asigna recursos por invocacion.', 'Capitulo 5', 152),
(1, 11, 'Capacidad del sistema para adquirir y liberar recursos automaticamente segun la demanda real.', 'Capitulo 2', 54),
(1, 12, 'Ajuste automatico del numero de instancias en funcion de metricas observadas.', 'Capitulo 7', 203),
(2, 13, 'Agrupacion geografica de centros de datos del proveedor, con latencia y jurisdiccion propias.', 'Capitulo 8', 210),
(2, 14, 'Ubicacion aislada dentro de una region, con energia y red independientes.', 'Capitulo 8', 214),
(2, 15, 'Propiedad del sistema de seguir operando aunque falle uno de sus componentes.', 'Capitulo 9', 241),
(2, 20, 'Coordinacion automatica del ciclo de vida de multiples contenedores en un conjunto de nodos.', 'Capitulo 6', 165),
(23, 1, 'Modelo en el que se renta la maquina virtual y el estudiante instala el sistema operativo y PostgreSQL a mano.', 'Capitulo 2', 31),
(23, 10, 'Modelo donde no se administra la instancia; util para comparar contra el despliegue en Compute Engine de este ejercicio.', 'Capitulo 7', 156),
(23, 21, 'Servidor intermedio que recibe la peticion del navegador y la reenvia a la aplicacion interna, que no se expone a internet.', 'Capitulo 5', 98),
(23, 16, 'Diseno que mantiene el servicio disponible pese a fallas, mediante redundancia y conmutacion.', 'Capitulo 6', 121),
(23, 17, 'Componente que reparte peticiones entre varias instancias segun un algoritmo de distribucion.', 'Capitulo 6', 127),
(24, 18, 'Emulacion completa de una computadora sobre un hipervisor, con su propio sistema operativo.', 'Capitulo 1', 18),
(24, 19, 'Empaquetado que comparte el nucleo del anfitrion y aisla procesos, red y sistema de archivos.', 'Capitulo 3', 62),
(24, 20, 'Programacion, escalado y recuperacion automatica de contenedores en un cluster.', 'Capitulo 5', 108),
(24, 23, 'Reparto de un recurso fisico entre varios entornos logicos aislados entre si.', 'Capitulo 1', 12),
(25, 21, 'Punto unico de entrada que ademas termina TLS y oculta la topologia interna del sistema.', 'Capitulo 4', 88),
(25, 22, 'Propiedad de una operacion que produce el mismo resultado aunque se ejecute varias veces.', 'Capitulo 6', 141),
(26, 27, 'Copia de los datos en mas de un nodo para lectura escalable o recuperacion ante fallas.', 'Capitulo 9', 231),
(26, 28, 'Unidad de trabajo atomica, consistente, aislada y durable.', 'Capitulo 7', 178),
(26, 30, 'Cuarta forma normal: elimina las dependencias multivaluadas independientes dentro de una misma relacion.', 'Capitulo 4', 96),
(22, 30, 'Una relacion esta en 4FN si esta en BCNF y no contiene dos dependencias multivaluadas independientes sobre la misma clave.', 'Capitulo 5', 103),
(22, 28, 'Garantias que debe cumplir una transaccion para no dejar la base en un estado invalido.', 'Capitulo 6', 128),
(21, 27, 'Mantener copias sincronizadas de una base de datos en varios servidores.', 'Capitulo 8', 194),
(21, 26, 'Particion horizontal de una tabla entre varios nodos segun una clave de distribucion.', 'Capitulo 8', 199),
(21, 29, 'Teorema CAP: ante una particion de red hay que elegir entre consistencia y disponibilidad.', 'Capitulo 9', 212),
(27, 25, 'Almacenamiento temporal de resultados costosos para responder mas rapido a peticiones repetidas.', 'Capitulo 7', 164),
(27, 23, 'Tiempo transcurrido entre la peticion y la primera respuesta util.', 'Capitulo 7', 158),
(27, 24, 'Cantidad de peticiones atendidas por unidad de tiempo.', 'Capitulo 7', 161),
(28, 21, 'En un monolito server-side, el proxy inverso publica la aplicacion bajo un prefijo de ruta sin exponer el puerto interno.', 'Capitulo 3', 71),
(28, 22, 'Operacion segura de reintentar: base para formularios que se reenvian por error.', 'Capitulo 5', 119),
(29, 1, 'Primer modelo que estudia el alumno: se renta la maquina y se administra todo lo demas.', 'Capitulo 1', 14),
(29, 2, 'Segundo modelo: el proveedor administra el entorno de ejecucion de la aplicacion.', 'Capitulo 1', 19),
(29, 3, 'Tercer modelo: la aplicacion se consume ya terminada, por suscripcion.', 'Capitulo 1', 24),
(29, 5, 'Deposito de objetos donde el alumno guarda las imagenes de practica.', 'Capitulo 4', 67);

-- imagenes_libros: 30 portadas sinteticas, una por libro. El nombre de
-- archivo es un UUID v4 generado por el servidor, nunca el nombre que envio
-- el usuario. Los archivos correspondientes estan en db/seed_uploads/ y se
-- copian a uploads/ en la VM (ver README, 'Cargar datos de prueba').
INSERT INTO imagenes_libros (libro_id, nombre_archivo, nombre_original, tipo_mime, tamano_bytes, texto_alternativo, es_portada) VALUES
(1, '7695dde9-3a32-4fe1-bb85-a1a50e2203e3.png', 'portada-01.png', 'image/png', 17788, 'Portada del libro Cloud Computing: Concepts, Technology and Architecture', TRUE),
(2, 'e8912e70-f588-4f75-ae9c-e2e2ab14b983.png', 'portada-02.png', 'image/png', 10707, 'Portada del libro Building Microservices', TRUE),
(3, 'e8207d13-976e-4270-95f9-e2e18a67e44f.png', 'portada-03.png', 'image/png', 15736, 'Portada del libro Patterns of Enterprise Application Architecture', TRUE),
(4, 'ca035b59-5147-4f6b-a455-94118ae8557e.png', 'portada-04.png', 'image/png', 19313, 'Portada del libro Design Patterns: Elements of Reusable Object-Oriented Software', TRUE),
(5, '9d2bd165-f2da-4ea8-bd2a-f821354ff3c3.png', 'portada-05.png', 'image/png', 19032, 'Portada del libro Clean Code: A Handbook of Agile Software Craftsmanship', TRUE),
(6, 'c85276b7-52c6-4862-85a9-d776a973ebae.png', 'portada-06.png', 'image/png', 12871, 'Portada del libro Modern Operating Systems', TRUE),
(7, 'dcfa4dee-f59a-4439-adaa-f33084f2652f.png', 'portada-07.png', 'image/png', 10321, 'Portada del libro Computer Networks', TRUE),
(8, '4f4dd547-8a8a-4592-98d9-df122cac167a.png', 'portada-08.png', 'image/png', 13495, 'Portada del libro Database Systems: The Complete Book', TRUE),
(9, '26fb05f1-2a1f-4b70-81aa-ab6bab133d83.png', 'portada-09.png', 'image/png', 11375, 'Portada del libro Applied Cryptography', TRUE),
(10, '22524b73-52bd-4e1d-a488-7bee3f13e6b4.png', 'portada-10.png', 'image/png', 10054, 'Portada del libro Security Engineering', TRUE),
(11, '11c1fab6-5856-4567-9d87-88b74dd382e2.png', 'portada-11.png', 'image/png', 11380, 'Portada del libro The C Programming Language', TRUE),
(12, '3c54f360-de5b-4cc6-ae53-4caa90a518a4.png', 'portada-12.png', 'image/png', 11105, 'Portada del libro Introduction to Algorithms', TRUE),
(13, 'e07d5deb-dd15-431b-9644-ace32ac1554f.png', 'portada-13.png', 'image/png', 15414, 'Portada del libro The Art of Computer Programming, Volume 1', TRUE),
(14, '667cb22f-701a-4fc2-a1a7-ad707e4464d7.png', 'portada-14.png', 'image/png', 10539, 'Portada del libro Domain-Driven Design', TRUE),
(15, 'cb3f3c84-127f-4ab4-8acc-8abd93d388a4.png', 'portada-15.png', 'image/png', 13968, 'Portada del libro Test-Driven Development: By Example', TRUE),
(16, '77723469-fe3d-4333-82af-c21206defa9a.png', 'portada-16.png', 'image/png', 17696, 'Portada del libro Object-Oriented Analysis and Design with Applications', TRUE),
(17, '00890aed-2144-40ae-83d4-f4588c21fb8a.png', 'portada-17.png', 'image/png', 9982, 'Portada del libro The Phoenix Project', TRUE),
(18, '495a220b-4bae-47ca-b929-877a41c74385.png', 'portada-18.png', 'image/png', 8300, 'Portada del libro Accelerate', TRUE),
(19, '1bf2322e-5f10-45b4-9364-37709af676ed.png', 'portada-19.png', 'image/png', 10192, 'Portada del libro Continuous Delivery', TRUE),
(20, '09809909-f1e0-4b37-943e-c5f83787cc95.png', 'portada-20.png', 'image/png', 17887, 'Portada del libro Refactoring: Improving the Design of Existing Code', TRUE),
(21, 'fec9c853-dc0f-424d-b966-b9b008455824.png', 'portada-21.png', 'image/png', 14503, 'Portada del libro Fundamentos de bases de datos relacionales', TRUE),
(22, 'd98bb54d-fb97-4406-b00e-5411fa759268.png', 'portada-22.png', 'image/png', 11616, 'Portada del libro Normalizacion practica hasta 4FN', TRUE),
(23, 'd58671d2-21b0-4d25-8728-8b280323f020.png', 'portada-23.png', 'image/png', 14365, 'Portada del libro Despliegue de aplicaciones en la nube publica', TRUE),
(24, '9f0f36ef-075a-4454-9c0d-c93482ce0dbd.png', 'portada-24.png', 'image/png', 14522, 'Portada del libro Introduccion a la virtualizacion y los contenedores', TRUE),
(25, 'cdc4d0c9-d2e0-49d7-aa3f-1650bfafa0d5.png', 'portada-25.png', 'image/png', 13086, 'Portada del libro Seguridad en aplicaciones web', TRUE),
(26, 'b10c7599-1206-4bb4-8061-5e6b671e3230.png', 'portada-26.png', 'image/png', 13445, 'Portada del libro PostgreSQL para desarrolladores', TRUE),
(27, 'e13b9e4b-6051-4684-acf6-b49f918a418a.png', 'portada-27.png', 'image/png', 11099, 'Portada del libro Node.js del lado del servidor', TRUE),
(28, '57385865-481a-4de2-b2dd-0565b20faf2a.png', 'portada-28.png', 'image/png', 13220, 'Portada del libro Arquitectura monolitica bien hecha', TRUE),
(29, 'e0ad3837-3ea3-4137-90d7-ec21c73f309c.png', 'portada-29.png', 'image/png', 14444, 'Portada del libro Computacion en la nube para estudiantes', TRUE),
(30, '90dbac0e-3f71-4b46-ae6a-ccb3056110db.png', 'portada-30.png', 'image/png', 13982, 'Portada del libro Historia de la computacion en Mexico', TRUE);

COMMIT;

-- Conteo de control: 30 filas en cada tabla base.
SELECT 'usuarios' AS tabla, count(*) FROM usuarios
UNION ALL SELECT 'autores', count(*) FROM autores
UNION ALL SELECT 'generos', count(*) FROM generos
UNION ALL SELECT 'categorias', count(*) FROM categorias
UNION ALL SELECT 'formatos', count(*) FROM formatos
UNION ALL SELECT 'conceptos', count(*) FROM conceptos
UNION ALL SELECT 'libros', count(*) FROM libros
UNION ALL SELECT 'imagenes_libros', count(*) FROM imagenes_libros
UNION ALL SELECT 'libros_autores', count(*) FROM libros_autores
UNION ALL SELECT 'libros_generos', count(*) FROM libros_generos
UNION ALL SELECT 'libros_conceptos', count(*) FROM libros_conceptos
ORDER BY 1;

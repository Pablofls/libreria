// -----------------------------------------------------------------------------
// app.js — arranque controlado del monolito.
//
// Responsabilidad: inicializar Express, montar el middleware general, registrar
// las rutas de cada módulo y arrancar el servidor. Nada de lógica de negocio ni
// de SQL vive aquí: si este archivo crece, es señal de que algo se puso en el
// lugar equivocado.
//
// Orden del middleware (importa, y este es el motivo de cada posición):
//   1. trust proxy   → para que req.protocol/req.ip reflejen al reverse proxy
//   2. cabeceras     → antes de cualquier respuesta
//   3. estáticos     → antes de las sesiones: servir un CSS no debe crear sesión
//   4. body parser   → req.body debe existir antes del chequeo de CSRF
//   5. sesión        → antes de locals, que lee req.session
//   6. locals + CSRF → antes de las rutas, que renderizan vistas
//   7. rutas         → el trabajo real
//   8. 404 y errores → al final, capturan lo que nadie atendió
// -----------------------------------------------------------------------------

const path = require('path');
const express = require('express');
const session = require('express-session');

const config = require('./config/env');
const { locals, tokenCsrf, verificarCsrf } = require('./middleware/locals');
const { noEncontrado, manejadorErrores } = require('./middleware/errores');

const app = express();

// 1. Node corre detrás de Apache/NGINX. Sin esto, req.ip sería siempre la del
//    proxy (127.0.0.1) y la cookie `secure` no se enviaría bajo HTTPS.
app.set('trust proxy', 1);

// EJS renderizado en el servidor. El navegador sólo recibe HTML ya armado:
// no hay JSON ni XML de ida y vuelta, según la restricción del ejercicio.
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));
// Sin cachear plantillas en desarrollo; con caché en producción.
app.set('view cache', config.entorno === 'production');
app.disable('x-powered-by');   // no anunciar "Express" a quien escanee el sitio

// 2. Cabeceras de seguridad. Se ponen a mano en vez de añadir una dependencia:
//    son cuatro y así queda explícito qué protege cada una.
app.use((req, res, next) => {
    // Evita que el navegador "adivine" el tipo de un archivo subido y lo trate
    // como HTML o JavaScript.
    res.setHeader('X-Content-Type-Options', 'nosniff');
    // El sitio no debe poder incrustarse en un iframe ajeno (clickjacking).
    res.setHeader('X-Frame-Options', 'DENY');
    res.setHeader('Referrer-Policy', 'same-origin');
    // CSP: sólo recursos propios. 'unsafe-inline' en style-src porque algunas
    // vistas usan atributos style puntuales; los scripts NO lo permiten, así que
    // un <script> inyectado en un título de libro no se ejecutaría aunque el
    // escapado de EJS fallara.
    res.setHeader('Content-Security-Policy',
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; " +
        "script-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'");
    next();
});

// 3. Estáticos.
// Se montan bajo el prefijo público, igual que el resto: el reverse proxy
// reenvía la ruta COMPLETA (proxy_pass sin barra final), así que Node recibe
// '/library/css/style.css' y no '/css/style.css'.
const B = config.basePath;   // '' en local, '/library' en la VM

const opcionesEstaticos = {
    maxAge: config.entorno === 'production' ? '7d' : 0,
    // No servir index.html implícito ni listar directorios.
    index: false,
    redirect: false
};
app.use(`${B}/css`, express.static(path.join(__dirname, 'public/css'), opcionesEstaticos));
app.use(`${B}/js`, express.static(path.join(__dirname, 'public/js'), opcionesEstaticos));

// Las imágenes subidas se sirven desde uploads/, fuera de public/, y con
// Content-Disposition inline + nosniff. Nunca se ejecuta nada desde aquí.
app.use(`${B}/uploads`, express.static(path.join(__dirname, config.subidas.directorio), {
    ...opcionesEstaticos,
    setHeaders: res => {
        res.setHeader('X-Content-Type-Options', 'nosniff');
        res.setHeader('Content-Disposition', 'inline');
    }
}));

// 4. Formularios HTML (application/x-www-form-urlencoded). No hay express.json():
//    el ejercicio prohíbe JSON como mecanismo de intercambio, así que no se
//    acepta ese tipo de cuerpo en ninguna ruta.
app.use(express.urlencoded({ extended: false, limit: '256kb' }));

// 5. Sesión.
app.use(session({
    name: 'libreria.sid',            // no anunciar el framework con 'connect.sid'
    secret: config.sessionSecret,    // viene de .env; la app no arranca sin él
    resave: false,
    saveUninitialized: false,        // no crear sesión a quien sólo navega
    rolling: true,                   // renovar la caducidad con cada petición
    cookie: {
        httpOnly: true,              // inalcanzable desde JavaScript (robo por XSS)
        sameSite: 'lax',             // no se envía en peticiones de otros sitios
        secure: config.cookieSegura, // sólo por HTTPS cuando lo haya
        maxAge: 1000 * 60 * 60 * 2,  // 2 horas
        path: config.basePath || '/'
    }
}));

// 6. Variables de vista y CSRF.
app.use(locals);
app.use(tokenCsrf);
app.use(verificarCsrf);

// 7. Módulos. Cada uno agrupa model + controller + routes de un dominio.
//
// Se agrupan en un Router que después se monta bajo BASE_PATH. Así la
// aplicación atiende '/library/libros' en la VM y '/libros' en desarrollo, con
// el mismo código y sin que el proxy tenga que reescribir rutas. Reescribirlas
// en el proxy rompería los `redirect` de Express, que salen con ruta absoluta.
const modulos = express.Router();

modulos.use('/', require('./src/modules/auth/auth.routes'));
modulos.use('/panel', require('./src/modules/panel/panel.routes'));
modulos.use('/libros', require('./src/modules/libros/libros.routes'));
modulos.use('/autores', require('./src/modules/autores/autores.routes'));
modulos.use('/generos', require('./src/modules/generos/generos.routes'));
modulos.use('/categorias', require('./src/modules/categorias/categorias.routes'));
modulos.use('/formatos', require('./src/modules/formatos/formatos.routes'));
modulos.use('/conceptos', require('./src/modules/conceptos/conceptos.routes'));
modulos.use('/imagenes', require('./src/modules/imagenes/imagenes.routes'));
modulos.use('/usuarios', require('./src/modules/usuarios/usuarios.routes'));

app.use(B || '/', modulos);

// 8. Lo que no atendió nadie.
app.use(noEncontrado);
app.use(manejadorErrores);

// Arranque. Se escucha en 127.0.0.1: el puerto 3000 no queda expuesto a
// internet ni aunque el firewall de GCP se abriera por error. El único camino
// desde fuera es el reverse proxy (ver deploy/).
const servidor = app.listen(config.puerto, config.host, () => {
    console.log(`Librería escuchando en http://${config.host}:${config.puerto}${config.basePath || ''}`);
    console.log(`Entorno: ${config.entorno} · prefijo público: '${config.basePath || '/'}'`);
    // Se registra con qué identidad se conectará a PostgreSQL —nunca la
    // contraseña—. Sin esto, un usuario de base de datos equivocado sólo se
    // manifiesta como un error de autenticación en la primera consulta, mucho
    // después del arranque y sin pista de cuál fue el usuario usado.
    console.log(`Base de datos: ${config.db.user}@${config.db.host}:${config.db.port}/${config.db.database}`);
});

// Cierre ordenado: deja de aceptar conexiones y cierra el pool de PostgreSQL.
// Sin esto, un reinicio deja conexiones colgadas en la base de datos.
function apagar(senal) {
    console.log(`\n[${senal}] cerrando…`);
    servidor.close(() => {
        require('./config/db').pool.end()
            .then(() => process.exit(0))
            .catch(() => process.exit(1));
    });
    setTimeout(() => process.exit(1), 10000).unref();
}
process.on('SIGTERM', () => apagar('SIGTERM'));
process.on('SIGINT', () => apagar('SIGINT'));

module.exports = app;

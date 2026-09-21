// JavaScript de interfaz. Sólo comodidad: nada de lo que hay aquí es un
// control de seguridad. Toda validación y toda autorización se resuelven en el
// servidor, porque el usuario puede desactivar este archivo por completo.
(function () {
    'use strict';

    // Cierra el aviso automáticamente.
    var toast = document.getElementById('toast');
    if (toast) {
        var cerrar = function () { toast.classList.add('toast--oculto'); };
        var boton = toast.querySelector('.toast__cerrar');
        if (boton) boton.addEventListener('click', cerrar);
        setTimeout(cerrar, 6000);
    }

    // Confirmación antes de una acción destructiva. El formulario lleva el
    // mensaje en data-confirmar; si el usuario cancela, no se envía.
    document.querySelectorAll('form[data-confirmar]').forEach(function (form) {
        form.addEventListener('submit', function (evento) {
            if (!window.confirm(form.getAttribute('data-confirmar'))) {
                evento.preventDefault();
            }
        });
    });

    // Enfoca la lista de errores de validación cuando la hay, para que quien
    // navega con teclado no tenga que buscarla.
    var errores = document.querySelector('.errores');
    if (errores) {
        errores.setAttribute('tabindex', '-1');
        errores.focus();
    }
})();

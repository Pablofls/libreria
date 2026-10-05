# =============================================================================
# cliente/pestanas.py — pestañas de cliente_escritorio.py para los
# microservicios REST: Libros, Autores, Usuarios, Pedidos y Pagos.
#
# Cada pestaña es un CRUD con tabla + formulario, del mismo estilo que la
# ventana del clasificador (LabelFrame, Treeview con Scrollbar, ttk.Entry,
# messagebox y mensajes al pie). Solo biblioteca estandar.
#
# REGLAS
#   - Ninguna pestaña habla HTTP: todo pasa por api_rest.ClienteApi, que pone
#     el JWT, lo renueva y traduce los errores.
#   - La red corre en un hilo (app.en_hilo) para que la ventana no se congele;
#     los widgets solo se tocan desde el hilo de Tk.
#   - La GUI muestra y oculta, el SERVIDOR decide: deshabilitar un boton para un
#     lector es ayuda visual; si alguien lo forzara, el servicio responderia 403.
# =============================================================================

import tkinter as tk
from tkinter import messagebox, ttk

METODOS_PAGO = ('tarjeta', 'transferencia', 'efectivo')
ESTADOS_PEDIDO = ('pendiente', 'pagado', 'enviado', 'cancelado')


def dinero(valor):
    try:
        return '${:,.2f}'.format(float(valor))
    except (TypeError, ValueError):
        return ''


def fecha(valor):
    return (valor or '')[:16].replace('T', ' ')


def entero_o_none(texto):
    texto = (texto or '').strip()
    if not texto:
        return None
    if not texto.isdigit():
        raise ValueError(texto)
    return int(texto)


class PestanaBase(ttk.Frame):
    """Piezas comunes. Las subclases arman su interfaz y definen `cargar`."""

    requiere_sesion = True      # False: la lectura es publica (libros, autores)

    def __init__(self, app, notebook):
        super().__init__(notebook, padding=10)
        self.app = app
        self.api = app.api
        self.solo_admin = []    # widgets que un lector no puede usar

    # --- Construccion --------------------------------------------------------
    def tabla(self, padre, columnas, alto=9):
        marco = ttk.Frame(padre)
        arbol = ttk.Treeview(marco, columns=[c[0] for c in columnas],
                             show='headings', height=alto, selectmode='browse')
        for clave, titulo, ancho in columnas:
            arbol.heading(clave, text=titulo)
            arbol.column(clave, width=ancho, anchor='w')
        barra = ttk.Scrollbar(marco, orient='vertical', command=arbol.yview)
        arbol.configure(yscrollcommand=barra.set)
        arbol.pack(side='left', fill='both', expand=True)
        barra.pack(side='right', fill='y')
        marco.pack(fill='both', expand=True)
        return arbol

    def campo(self, padre, etiqueta, fila, columna=0, ancho=22, oculto=False,
              solo_admin=False):
        ttk.Label(padre, text=etiqueta + ':').grid(row=fila, column=columna * 2,
                                                   sticky='w', pady=2, padx=(0, 4))
        variable = tk.StringVar()
        entrada = ttk.Entry(padre, textvariable=variable, width=ancho,
                            show='*' if oculto else '')
        entrada.grid(row=fila, column=columna * 2 + 1, sticky='w', padx=(0, 14))
        if solo_admin:
            self.solo_admin.append(entrada)
        return variable

    def boton(self, padre, texto, comando, solo_admin=False):
        b = ttk.Button(padre, text=texto, command=comando)
        b.pack(side='left', padx=(0, 8))
        if solo_admin:
            self.solo_admin.append(b)
        return b

    def vaciar(self, arbol):
        arbol.delete(*arbol.get_children())

    def seleccion(self, arbol, lista, avisar=True):
        """El registro de `lista` que corresponde a la fila elegida, o None."""
        elegido = arbol.selection()
        if not elegido:
            if avisar:
                messagebox.showwarning('Sin seleccion', 'Elige un registro de la tabla.')
            return None
        return lista[int(elegido[0])]

    # --- Ejecucion -----------------------------------------------------------
    def en_hilo(self, trabajo, ok=None):
        self.app.en_hilo(trabajo, ok, self.app.mostrar_error)

    def avisar(self, texto, color='#060'):
        self.app.pie(texto, color)

    def confirmar(self, texto):
        return messagebox.askyesno('Confirmar', texto)

    # --- Ciclo de vida -------------------------------------------------------
    def sesion_cambio(self):
        """La app llama esto al iniciar o cerrar sesion."""
        self.permisos()
        if self.requiere_sesion and not self.api.sesion_activa:
            self.limpiar()
        else:
            self.cargar()

    def permisos(self):
        for w in self.solo_admin:
            if isinstance(w, ttk.Combobox):
                w.configure(state='readonly' if self.api.es_admin else 'disabled')
            else:
                w.configure(state='normal' if self.api.es_admin else 'disabled')

    def limpiar(self):
        pass

    def cargar(self):
        pass


# =============================================================================
# Libros (catalogo, puerto 5002 detras de /books)
# =============================================================================
class PestanaLibros(PestanaBase):
    requiere_sesion = False

    def __init__(self, app, notebook):
        super().__init__(app, notebook)
        self.libros, self.autores = [], []
        self.editando = None

        barra = ttk.Frame(self)
        barra.pack(fill='x', pady=(0, 6))
        ttk.Label(barra, text='Titulo contiene:').pack(side='left')
        self.busqueda = tk.StringVar()
        ttk.Entry(barra, textvariable=self.busqueda, width=30).pack(side='left', padx=6)
        ttk.Button(barra, text='Buscar', command=self.buscar).pack(side='left')
        ttk.Button(barra, text='Mostrar todos', command=self.cargar).pack(side='left', padx=6)

        self.arbol = self.tabla(self, [
            ('isbn', 'ISBN', 120), ('titulo', 'Titulo', 260), ('autores', 'Autores', 200),
            ('anio', 'Año', 50), ('precio', 'Precio', 70), ('stock', 'Stock', 50),
            ('formato', 'Formato', 100)])
        self.arbol.bind('<<TreeviewSelect>>', self.al_elegir)

        form = ttk.LabelFrame(self, text='Libro (solo administradores escriben)', padding=8)
        form.pack(fill='x', pady=(8, 0))
        self.v = {}
        campos = (('isbn', 'ISBN', 0, 0), ('titulo', 'Titulo', 0, 1), ('anio_publicacion', 'Año', 1, 0),
                  ('precio', 'Precio', 1, 1), ('stock', 'Stock', 2, 0), ('categoria_id', 'Id categoria', 2, 1),
                  ('formato_id', 'Id formato', 3, 0), ('generos', 'Ids generos (1,2)', 3, 1),
                  ('sinopsis', 'Sinopsis', 4, 0))
        for clave, etiqueta, fila, col in campos:
            self.v[clave] = self.campo(form, etiqueta, fila, col, solo_admin=True)
        ttk.Label(form, text='Autores (Ctrl+clic; sin elegir no cambia):').grid(
            row=0, column=4, sticky='w', padx=(10, 0))
        self.lista_autores = tk.Listbox(form, selectmode='multiple', height=5, exportselection=False)
        self.lista_autores.grid(row=1, column=4, rowspan=4, sticky='nsew', padx=(10, 0))
        self.solo_admin.append(self.lista_autores)

        acciones = ttk.Frame(self)
        acciones.pack(fill='x', pady=(8, 0))
        self.boton(acciones, 'Nuevo', self.nuevo, solo_admin=True)
        self.boton(acciones, 'Guardar', self.guardar, solo_admin=True)
        self.boton(acciones, 'Eliminar', self.eliminar, solo_admin=True)

    def cargar(self):
        def trabajo():
            libros = self.api.get('/books?limite=200', autenticada=False)['books']
            autores = self.api.get('/authors', autenticada=False)
            return libros, autores
        self.en_hilo(trabajo, self.mostrar)

    def buscar(self):
        texto = self.busqueda.get().strip()
        if not texto:
            return self.cargar()
        self.en_hilo(lambda: (self.api.get('/books/search?titulo=' + _q(texto), autenticada=False)['books'],
                              self.autores), self.mostrar)

    def mostrar(self, resultado):
        self.libros, self.autores = resultado
        self.vaciar(self.arbol)
        for i, l in enumerate(self.libros):
            self.arbol.insert('', 'end', iid=str(i), values=(
                l['isbn'], l['title'], ', '.join(a['name'] for a in l.get('authors', [])),
                l.get('year') or '', dinero(l['price']), l['stock'], l['format']))
        self.lista_autores.delete(0, 'end')
        for a in self.autores:
            self.lista_autores.insert('end', '{} (#{})'.format(a['nombre'], a['id']))
        self.avisar('{} libros'.format(len(self.libros)), '#555')

    def al_elegir(self, _e=None):
        libro = self.seleccion(self.arbol, self.libros, avisar=False)
        if not libro:
            return
        self.editando = libro['isbn']
        self.v['isbn'].set(libro['isbn'])
        self.v['titulo'].set(libro['title'])
        self.v['anio_publicacion'].set(libro.get('year') or '')
        self.v['precio'].set(libro['price'])
        self.v['stock'].set(libro['stock'])
        for clave in ('categoria_id', 'formato_id', 'generos', 'sinopsis'):
            self.v[clave].set('')     # el catalogo no devuelve ids: se dejan vacios

    def nuevo(self):
        self.editando = None
        self.arbol.selection_remove(self.arbol.selection())
        for variable in self.v.values():
            variable.set('')
        self.lista_autores.selection_clear(0, 'end')

    def _payload(self):
        v = {k: x.get().strip() for k, x in self.v.items()}
        carga = {}
        try:
            for clave in ('anio_publicacion', 'stock', 'categoria_id', 'formato_id'):
                if v[clave]:
                    carga[clave] = entero_o_none(v[clave])
            if v['generos']:
                carga['generos'] = [int(g) for g in v['generos'].replace(' ', '').split(',') if g]
        except ValueError:
            messagebox.showwarning('Datos incompletos', 'Año, stock, categoria, formato y generos son numeros enteros.')
            return None
        for clave in ('isbn', 'titulo', 'precio', 'sinopsis'):
            if v[clave]:
                carga[clave] = v[clave]
        elegidos = self.lista_autores.curselection()
        if elegidos:
            carga['autores'] = [self.autores[i]['id'] for i in elegidos]
        return carga

    def guardar(self):
        carga = self._payload()
        if carga is None:
            return
        if self.editando:
            if carga.get('isbn') and carga['isbn'] != self.editando:
                carga['isbn_nuevo'] = carga.pop('isbn')
            else:
                carga.pop('isbn', None)
            ruta, metodo = '/books/update/' + self.editando, 'PATCH'
        else:
            faltan = [k for k in ('isbn', 'titulo', 'precio', 'stock', 'categoria_id', 'formato_id')
                      if k not in carga]
            if faltan or 'autores' not in carga:
                return messagebox.showwarning('Datos incompletos', 'Para un libro nuevo captura: ISBN, titulo, '
                                              'precio, stock, categoria, formato y al menos un autor.')
            ruta, metodo = '/books/insert', 'POST'

        def listo(_):
            self.avisar('Libro guardado.')
            self.nuevo()
            self.cargar()
        self.en_hilo(lambda: self.api.peticion(metodo, ruta, carga), listo)

    def eliminar(self):
        libro = self.seleccion(self.arbol, self.libros)
        if not libro or not self.confirmar('¿Eliminar "{}" del catalogo?'.format(libro['title'])):
            return

        def listo(_):
            self.avisar('Libro eliminado.')
            self.nuevo()
            self.cargar()
        self.en_hilo(lambda: self.api.peticion('DELETE', '/books/delete/' + libro['isbn']), listo)

    def limpiar(self):
        pass


def _q(texto):
    from urllib.parse import quote
    return quote(texto)


# =============================================================================
# Autores (puerto 5004) y su relacion con libros
# =============================================================================
class PestanaAutores(PestanaBase):
    requiere_sesion = False

    def __init__(self, app, notebook):
        super().__init__(app, notebook)
        self.autores, self.libros_autor, self.vinculables = [], [], []
        self.editando = None

        self.arbol = self.tabla(self, [('id', 'Id', 40), ('nombre', 'Nombre', 240),
                                       ('nacionalidad', 'Nacionalidad', 130), ('libros', 'Libros', 50)], alto=7)
        self.arbol.bind('<<TreeviewSelect>>', self.al_elegir)

        form = ttk.LabelFrame(self, text='Autor (solo administradores escriben)', padding=8)
        form.pack(fill='x', pady=(8, 0))
        self.nombre = self.campo(form, 'Nombre', 0, 0, ancho=34, solo_admin=True)
        self.nacionalidad = self.campo(form, 'Nacionalidad', 0, 1, solo_admin=True)
        self.biografia = self.campo(form, 'Biografia', 1, 0, ancho=34, solo_admin=True)
        acciones = ttk.Frame(self)
        acciones.pack(fill='x', pady=6)
        self.boton(acciones, 'Nuevo', self.nuevo, solo_admin=True)
        self.boton(acciones, 'Guardar', self.guardar, solo_admin=True)
        self.boton(acciones, 'Eliminar', self.eliminar, solo_admin=True)

        rel = ttk.LabelFrame(self, text='Libros del autor seleccionado', padding=8)
        rel.pack(fill='both', expand=True)
        self.arbol_libros = self.tabla(rel, [('id', 'Id', 40), ('isbn', 'ISBN', 120), ('titulo', 'Titulo', 300)], alto=4)
        fila = ttk.Frame(rel)
        fila.pack(fill='x', pady=(6, 0))
        self.combo = ttk.Combobox(fila, state='disabled', width=48)
        self.combo.pack(side='left')
        self.solo_admin.append(self.combo)
        self.boton(fila, 'Vincular', self.vincular, solo_admin=True).pack_configure(padx=8)
        self.boton(fila, 'Quitar seleccionado', self.desvincular, solo_admin=True)

    def cargar(self):
        def trabajo():
            return self.api.get('/authors', autenticada=False), self.api.get('/authors/books', autenticada=False)
        self.en_hilo(trabajo, self.mostrar)

    def mostrar(self, resultado):
        self.autores, self.vinculables = resultado
        self.vaciar(self.arbol)
        for i, a in enumerate(self.autores):
            self.arbol.insert('', 'end', iid=str(i), values=(a['id'], a['nombre'], a.get('nacionalidad') or '', a['libros']))
        self.combo.configure(values=['{} ({})'.format(l['titulo'], l['isbn']) for l in self.vinculables])
        self.avisar('{} autores'.format(len(self.autores)), '#555')

    def _autor(self, avisar=True):
        return self.seleccion(self.arbol, self.autores, avisar)

    def al_elegir(self, _e=None):
        autor = self._autor(avisar=False)
        if not autor:
            return
        self.editando = autor['id']
        self.nombre.set(autor['nombre'])
        self.nacionalidad.set(autor.get('nacionalidad') or '')
        self.biografia.set(autor.get('biografia') or '')

        def listo(libros):
            self.libros_autor = libros
            self.vaciar(self.arbol_libros)
            for i, l in enumerate(libros):
                self.arbol_libros.insert('', 'end', iid=str(i), values=(l['id'], l['isbn'], l['titulo']))
        self.en_hilo(lambda: self.api.get('/authors/{}/books'.format(autor['id']), autenticada=False), listo)

    def nuevo(self):
        self.editando = None
        self.arbol.selection_remove(self.arbol.selection())
        for v in (self.nombre, self.nacionalidad, self.biografia):
            v.set('')

    def guardar(self):
        carga = {'nombre': self.nombre.get().strip(), 'nacionalidad': self.nacionalidad.get().strip() or None,
                 'biografia': self.biografia.get().strip() or None}
        if not carga['nombre']:
            return messagebox.showwarning('Datos incompletos', 'El nombre es obligatorio.')
        metodo, ruta = ('PUT', '/authors/{}'.format(self.editando)) if self.editando else ('POST', '/authors')

        def listo(_):
            self.avisar('Autor guardado.')
            self.nuevo()
            self.cargar()
        self.en_hilo(lambda: self.api.peticion(metodo, ruta, carga), listo)

    def eliminar(self):
        autor = self._autor()
        if not autor or not self.confirmar('¿Eliminar a "{}"?'.format(autor['nombre'])):
            return

        def listo(_):
            self.avisar('Autor eliminado.')
            self.nuevo()
            self.cargar()
        self.en_hilo(lambda: self.api.peticion('DELETE', '/authors/{}'.format(autor['id'])), listo)

    def vincular(self):
        autor, indice = self._autor(), self.combo.current()
        if not autor:
            return
        if indice < 0:
            return messagebox.showwarning('Sin libro', 'Elige un libro de la lista.')
        libro = self.vinculables[indice]

        def listo(_):
            self.avisar('Autor vinculado a "{}".'.format(libro['titulo']))
            self.al_elegir()
            self.cargar()
        self.en_hilo(lambda: self.api.peticion('POST', '/authors/{}/books/{}'.format(autor['id'], libro['id']), {}), listo)

    def desvincular(self):
        autor = self._autor()
        libro = self.seleccion(self.arbol_libros, self.libros_autor)
        if not autor or not libro:
            return

        def listo(_):
            self.avisar('Vinculo quitado.')
            self.al_elegir()
            self.cargar()
        self.en_hilo(lambda: self.api.peticion('DELETE', '/authors/{}/books/{}'.format(autor['id'], libro['id'])), listo)


# =============================================================================
# Usuarios (puerto 5003)
# =============================================================================
class PestanaUsuarios(PestanaBase):

    def __init__(self, app, notebook):
        super().__init__(app, notebook)
        self.usuarios, self.editando = [], None
        self.arbol = self.tabla(self, [
            ('id', 'Id', 40), ('nombre', 'Nombre', 110), ('paterno', 'Apellido paterno', 120),
            ('materno', 'Apellido materno', 120), ('email', 'Correo', 220), ('rol', 'Rol', 60),
            ('activo', 'Activo', 50)], alto=8)
        self.arbol.bind('<<TreeviewSelect>>', self.al_elegir)

        form = ttk.LabelFrame(self, text='Usuario', padding=8)
        form.pack(fill='x', pady=(8, 0))
        self.v = {
            'nombre': self.campo(form, 'Nombre', 0, 0),
            'apellido_paterno': self.campo(form, 'Apellido paterno', 0, 1),
            'apellido_materno': self.campo(form, 'Apellido materno', 1, 0),
            'email': self.campo(form, 'Correo', 1, 1, ancho=28),
            'password': self.campo(form, 'Contraseña (vacia = igual)', 2, 0, oculto=True)}
        ttk.Label(form, text='Rol:').grid(row=2, column=2, sticky='w')
        self.rol = tk.StringVar(value='lector')
        self.combo_rol = ttk.Combobox(form, textvariable=self.rol, values=('lector', 'admin'), width=10, state='disabled')
        self.combo_rol.grid(row=2, column=3, sticky='w')
        self.solo_admin.append(self.combo_rol)
        self.activo = tk.BooleanVar(value=True)
        chk = ttk.Checkbutton(form, text='Activo', variable=self.activo, state='disabled')
        chk.grid(row=3, column=3, sticky='w')
        self.solo_admin.append(chk)

        acciones = ttk.Frame(self)
        acciones.pack(fill='x', pady=(8, 0))
        self.boton(acciones, 'Actualizar lista', self.cargar)
        self.boton(acciones, 'Nuevo', self.nuevo, solo_admin=True)
        self.boton(acciones, 'Guardar', self.guardar)
        self.boton(acciones, 'Dar de baja', self.baja)
        ttk.Label(self, text='Un lector solo ve y edita su propia cuenta; el rol y el estado los cambia un administrador.',
                  foreground='#555').pack(fill='x', pady=(6, 0))

    def cargar(self):
        if not self.api.sesion_activa:
            return
        yo = self.api.usuario['id']
        self.en_hilo(lambda: self.api.get('/users') if self.api.es_admin else [self.api.get('/users/%d' % yo)],
                     self.mostrar)

    def mostrar(self, usuarios):
        self.usuarios = usuarios
        self.vaciar(self.arbol)
        for i, u in enumerate(usuarios):
            self.arbol.insert('', 'end', iid=str(i), values=(
                u['id'], u['nombre'], u.get('apellido_paterno') or '', u.get('apellido_materno') or '',
                u['email'], u['rol'], 'si' if u['activo'] else 'no'))
        self.avisar('{} usuarios'.format(len(usuarios)), '#555')

    def limpiar(self):
        self.vaciar(self.arbol)
        self.nuevo()

    def al_elegir(self, _e=None):
        u = self.seleccion(self.arbol, self.usuarios, avisar=False)
        if not u:
            return
        self.editando = u['id']
        self.v['nombre'].set(u['nombre'])
        self.v['apellido_paterno'].set(u.get('apellido_paterno') or '')
        self.v['apellido_materno'].set(u.get('apellido_materno') or '')
        self.v['email'].set(u['email'])
        self.v['password'].set('')
        self.rol.set(u['rol'])
        self.activo.set(bool(u['activo']))

    def nuevo(self):
        self.editando = None
        for variable in self.v.values():
            variable.set('')
        self.rol.set('lector')
        self.activo.set(True)

    def guardar(self):
        v = {k: x.get().strip() for k, x in self.v.items()}
        password = self.v['password'].get()
        carga = {k: v[k] for k in ('nombre', 'apellido_paterno', 'apellido_materno', 'email')}
        if not all(carga.values()):
            return messagebox.showwarning('Datos incompletos', 'Nombre, apellidos y correo son obligatorios.')
        if password:
            carga['password'] = password
        if self.api.es_admin:
            carga['rol'], carga['activo'] = self.rol.get(), self.activo.get()
        if self.editando:
            metodo, ruta = 'PATCH', '/users/%d' % self.editando
        elif self.api.es_admin and password:
            metodo, ruta = 'POST', '/users'
        else:
            return messagebox.showwarning('Datos incompletos', 'Un usuario nuevo necesita contraseña (8 caracteres o mas).')
        self.v['password'].set('')      # la contraseña no se queda en el formulario

        def listo(_):
            self.avisar('Usuario guardado.')
            self.nuevo()
            self.cargar()
        self.en_hilo(lambda: self.api.peticion(metodo, ruta, carga), listo)

    def baja(self):
        u = self.seleccion(self.arbol, self.usuarios)
        if not u or not self.confirmar('¿Dar de baja a {}? (no se borra: queda inactivo)'.format(u['email'])):
            return

        def listo(_):
            self.avisar('Usuario dado de baja.')
            self.cargar()
        self.en_hilo(lambda: self.api.peticion('DELETE', '/users/%d' % u['id']), listo)


# =============================================================================
# Pedidos (puerto 5005)
# =============================================================================
class PestanaPedidos(PestanaBase):

    def __init__(self, app, notebook):
        super().__init__(app, notebook)
        self.pedidos, self.libros, self.lineas = [], [], []      # lineas: nuevo pedido en armado
        self.detalle = None

        self.arbol = self.tabla(self, [('id', 'Pedido', 60), ('estado', 'Estado', 90), ('total', 'Total', 90),
                                       ('pagado', 'Pagado', 90), ('fecha', 'Creado', 140)], alto=6)
        self.arbol.bind('<<TreeviewSelect>>', self.al_elegir)
        self.texto = tk.Text(self, height=5, wrap='word', state='disabled')
        self.texto.pack(fill='x', pady=(6, 0))

        acciones = ttk.Frame(self)
        acciones.pack(fill='x', pady=6)
        self.boton(acciones, 'Actualizar', self.cargar)
        self.boton(acciones, 'Cancelar pedido', self.cancelar)
        ttk.Label(acciones, text='  Estado (admin):').pack(side='left')
        self.estado = tk.StringVar(value='enviado')
        combo = ttk.Combobox(acciones, textvariable=self.estado, values=ESTADOS_PEDIDO, width=11, state='disabled')
        combo.pack(side='left', padx=4)
        self.solo_admin.append(combo)
        self.boton(acciones, 'Cambiar estado', self.cambiar_estado, solo_admin=True)
        self.boton(acciones, 'Eliminar (cancelado)', self.eliminar, solo_admin=True)

        nuevo = ttk.LabelFrame(self, text='Nuevo pedido', padding=8)
        nuevo.pack(fill='both', expand=True)
        fila = ttk.Frame(nuevo)
        fila.pack(fill='x')
        self.combo_libro = ttk.Combobox(fila, state='readonly', width=52)
        self.combo_libro.pack(side='left')
        ttk.Label(fila, text='  Cantidad:').pack(side='left')
        self.cantidad = tk.StringVar(value='1')
        ttk.Spinbox(fila, from_=1, to=1000, textvariable=self.cantidad, width=5).pack(side='left', padx=4)
        ttk.Button(fila, text='Agregar linea', command=self.agregar).pack(side='left', padx=6)
        self.arbol_lineas = self.tabla(nuevo, [('titulo', 'Libro', 330), ('cantidad', 'Cantidad', 70),
                                               ('subtotal', 'Subtotal', 90)], alto=3)
        fila2 = ttk.Frame(nuevo)
        fila2.pack(fill='x', pady=(6, 0))
        self.boton(fila2, 'Quitar linea', self.quitar)
        self.boton(fila2, 'Crear pedido', self.crear)

    def cargar(self):
        if not self.api.sesion_activa:
            return
        self.en_hilo(lambda: (self.api.get('/orders'), self.api.get('/orders/books')), self.mostrar)

    def mostrar(self, resultado):
        self.pedidos, self.libros = resultado
        self.vaciar(self.arbol)
        for i, p in enumerate(self.pedidos):
            self.arbol.insert('', 'end', iid=str(i), values=(
                p['id'], p['estado'], dinero(p['total']), dinero(p['pagado']), fecha(p['creado_en'])))
        self.combo_libro.configure(values=['{} — {} (stock {})'.format(l['titulo'], dinero(l['precio']), l['stock'])
                                           for l in self.libros])
        self.avisar('{} pedidos'.format(len(self.pedidos)), '#555')

    def limpiar(self):
        self.vaciar(self.arbol)
        self.vaciar(self.arbol_lineas)
        self.lineas = []
        self._escribir('')

    def _escribir(self, texto):
        self.texto.configure(state='normal')
        self.texto.delete('1.0', 'end')
        self.texto.insert('1.0', texto)
        self.texto.configure(state='disabled')

    def al_elegir(self, _e=None):
        pedido = self.seleccion(self.arbol, self.pedidos, avisar=False)
        if not pedido:
            return

        def listo(d):
            self.detalle = d
            lineas = '\n'.join('  {} x {} = {}'.format(l['cantidad'], l['titulo'], dinero(l['subtotal'])) for l in d['lineas'])
            historial = ' → '.join('{} ({})'.format(h['estado'], fecha(h['cambiado_en'])) for h in d['historial'])
            self._escribir('Pedido {}  [{}]  total {}  pagado {}\n{}\nHistorial: {}'.format(
                d['id'], d['estado'], dinero(d['total']), dinero(d['pagado']), lineas, historial))
        self.en_hilo(lambda: self.api.get('/orders/%d' % pedido['id']), listo)

    def agregar(self):
        indice = self.combo_libro.current()
        if indice < 0:
            return messagebox.showwarning('Sin libro', 'Elige un libro de la lista.')
        try:
            cantidad = entero_o_none(self.cantidad.get())
        except ValueError:
            cantidad = None
        if not cantidad or cantidad < 1:
            return messagebox.showwarning('Cantidad', 'La cantidad es un entero mayor que cero.')
        self.lineas.append((self.libros[indice], cantidad))
        self._pintar_lineas()

    def quitar(self):
        elegido = self.arbol_lineas.selection()
        if elegido:
            del self.lineas[int(elegido[0])]
            self._pintar_lineas()

    def _pintar_lineas(self):
        self.vaciar(self.arbol_lineas)
        for i, (libro, cantidad) in enumerate(self.lineas):
            self.arbol_lineas.insert('', 'end', iid=str(i), values=(
                libro['titulo'], cantidad, dinero(float(libro['precio']) * cantidad)))

    def crear(self):
        if not self.lineas:
            return messagebox.showwarning('Sin lineas', 'Agrega al menos un libro al pedido.')
        carga = {'lineas': [{'libro_id': l['id'], 'cantidad': c} for l, c in self.lineas]}

        def listo(p):
            self.avisar('Pedido {} creado: {}.'.format(p['id'], dinero(p['total'])))
            self.lineas = []
            self._pintar_lineas()
            self.cargar()
        self.en_hilo(lambda: self.api.peticion('POST', '/orders', carga), listo)

    def _elegido(self):
        return self.seleccion(self.arbol, self.pedidos)

    def cancelar(self):
        p = self._elegido()
        if not p or not self.confirmar('¿Cancelar el pedido {}? Se devuelve el stock.'.format(p['id'])):
            return
        self.en_hilo(lambda: self.api.peticion('POST', '/orders/%d/cancel' % p['id'], {}),
                     lambda _: (self.avisar('Pedido cancelado.'), self.cargar()))

    def cambiar_estado(self):
        p = self._elegido()
        if p:
            self.en_hilo(lambda: self.api.peticion('PATCH', '/orders/%d/status' % p['id'], {'estado': self.estado.get()}),
                         lambda _: (self.avisar('Estado actualizado.'), self.cargar()))

    def eliminar(self):
        p = self._elegido()
        if p and self.confirmar('¿Borrar el pedido {}?'.format(p['id'])):
            self.en_hilo(lambda: self.api.peticion('DELETE', '/orders/%d' % p['id']),
                         lambda _: (self.avisar('Pedido borrado.'), self.cargar()))


# =============================================================================
# Pagos (puerto 5006)
# =============================================================================
class PestanaPagos(PestanaBase):

    def __init__(self, app, notebook):
        super().__init__(app, notebook)
        self.pagos, self.pendientes = [], []

        self.arbol = self.tabla(self, [('id', 'Pago', 50), ('pedido', 'Pedido', 60), ('metodo', 'Metodo', 100),
                                       ('estado', 'Estado', 90), ('monto', 'Monto', 90),
                                       ('referencia', 'Referencia', 130), ('fecha', 'Fecha', 130)], alto=8)
        form = ttk.LabelFrame(self, text='Registrar pago (simulado: no se piden datos de tarjeta)', padding=8)
        form.pack(fill='x', pady=(8, 0))
        ttk.Label(form, text='Pedido pendiente:').grid(row=0, column=0, sticky='w')
        self.combo_pedido = ttk.Combobox(form, state='readonly', width=44)
        self.combo_pedido.grid(row=0, column=1, columnspan=3, sticky='w', padx=6)
        self.combo_pedido.bind('<<ComboboxSelected>>', self.al_elegir_pedido)
        self.monto = self.campo(form, 'Monto', 1, 0, ancho=12)
        ttk.Label(form, text='Metodo:').grid(row=1, column=2, sticky='w')
        self.metodo = tk.StringVar(value=METODOS_PAGO[0])
        ttk.Combobox(form, textvariable=self.metodo, values=METODOS_PAGO, state='readonly', width=14).grid(
            row=1, column=3, sticky='w')
        self.referencia = self.campo(form, 'Referencia (opc.)', 2, 0, ancho=24)

        acciones = ttk.Frame(self)
        acciones.pack(fill='x', pady=(8, 0))
        self.boton(acciones, 'Actualizar', self.cargar)
        self.boton(acciones, 'Registrar pago', self.registrar)
        self.boton(acciones, 'Reembolsar', self.reembolsar, solo_admin=True)
        self.boton(acciones, 'Corregir metodo/ref.', self.corregir, solo_admin=True)
        self.boton(acciones, 'Eliminar', self.eliminar, solo_admin=True)
        ttk.Label(self, text='Reembolsar exige que el pedido ya este cancelado; borrar solo pagos pendientes o rechazados.',
                  foreground='#555').pack(fill='x', pady=(6, 0))

    def cargar(self):
        if not self.api.sesion_activa:
            return
        self.en_hilo(lambda: (self.api.get('/payments'), self.api.get('/orders?estado=pendiente')), self.mostrar)

    def mostrar(self, resultado):
        self.pagos, self.pendientes = resultado
        self.vaciar(self.arbol)
        for i, p in enumerate(self.pagos):
            self.arbol.insert('', 'end', iid=str(i), values=(
                p['id'], p['pedido_id'], p['metodo'], p['estado'], dinero(p['monto']),
                p.get('referencia') or '', fecha(p['creado_en'])))
        self.combo_pedido.configure(values=['#{} — total {}, pagado {}'.format(
            p['id'], dinero(p['total']), dinero(p['pagado'])) for p in self.pendientes])
        self.avisar('{} pagos'.format(len(self.pagos)), '#555')

    def limpiar(self):
        self.vaciar(self.arbol)
        self.combo_pedido.configure(values=[])

    def al_elegir_pedido(self, _e=None):
        i = self.combo_pedido.current()
        if i >= 0:
            p = self.pendientes[i]
            self.monto.set('{:.2f}'.format(float(p['total']) - float(p['pagado'])))

    def registrar(self):
        i = self.combo_pedido.current()
        if i < 0:
            return messagebox.showwarning('Sin pedido', 'Elige el pedido que se va a pagar.')
        carga = {'pedido_id': self.pendientes[i]['id'], 'metodo': self.metodo.get()}
        try:
            carga['monto'] = round(float(self.monto.get().replace(',', '.')), 2)
        except ValueError:
            return messagebox.showwarning('Monto', 'El monto es un numero con dos decimales.')
        if self.referencia.get().strip():
            carga['referencia'] = self.referencia.get().strip()

        def listo(p):
            self.avisar('Pago {} registrado. Pedido: {}.'.format(p['id'], p['pedido_estado']))
            self.monto.set('')
            self.referencia.set('')
            self.cargar()
        self.en_hilo(lambda: self.api.peticion('POST', '/payments', carga), listo)

    def _elegido(self):
        return self.seleccion(self.arbol, self.pagos)

    def reembolsar(self):
        p = self._elegido()
        if p and self.confirmar('¿Reembolsar el pago {}?'.format(p['id'])):
            self.en_hilo(lambda: self.api.peticion('PATCH', '/payments/%d/status' % p['id'], {'estado': 'reembolsado'}),
                         lambda _: (self.avisar('Pago reembolsado.'), self.cargar()))

    def corregir(self):
        p = self._elegido()
        if p:
            carga = {'metodo': self.metodo.get(), 'referencia': self.referencia.get().strip() or None}
            self.en_hilo(lambda: self.api.peticion('PUT', '/payments/%d' % p['id'], carga),
                         lambda _: (self.avisar('Pago corregido.'), self.cargar()))

    def eliminar(self):
        p = self._elegido()
        if p and self.confirmar('¿Borrar el pago {}?'.format(p['id'])):
            self.en_hilo(lambda: self.api.peticion('DELETE', '/payments/%d' % p['id']),
                         lambda _: (self.avisar('Pago borrado.'), self.cargar()))


PESTANAS = (('Libros', PestanaLibros), ('Autores', PestanaAutores), ('Usuarios', PestanaUsuarios),
            ('Pedidos', PestanaPedidos), ('Pagos', PestanaPagos))

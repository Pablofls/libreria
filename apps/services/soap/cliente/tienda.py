# =============================================================================
# cliente/tienda.py — la "tienda" de cliente_escritorio.py: tema visual de
# librería, cuadricula de libros con portada, detalle, carrito y pago.
#
# Solo biblioteca estandar. Pillow es OPCIONAL: con el, las portadas se
# reescalan finas y se aceptan JPG/WebP; sin el, Tk lee PNG (las portadas
# sembradas lo son) y las reduce por factor entero.
#
# REGLAS
#   - La tienda NO conoce precios ni ids: muestra lo que dice el catalogo y, al
#     comprar, el servidor de pedidos toma el precio de la base de datos. Lo
#     que se ve en pantalla es informativo, nunca la fuente del cobro.
#   - Las portadas solo se piden con el nombre que genera el servidor (uuid +
#     extension): un nombre raro no se descarga.
#   - Los pagos son SIMULADOS: no se piden datos de tarjeta.
# =============================================================================

import base64
import io
import re
import tkinter as tk
from tkinter import messagebox, ttk

from pestanas import METODOS_PAGO, dinero

try:                                         # opcional
    from PIL import Image, ImageTk
except ImportError:                          # pragma: no cover
    Image = ImageTk = None

# --- Paleta: papel crema, tinta, verde de libreria y burdeos ------------------
PAPEL, TARJETA, TINTA = '#f7f1e5', '#fffdf8', '#2b2118'
VERDE, BURDEOS, DORADO = '#1f3d36', '#8c2f39', '#c99a2e'
GRIS, BORDE, MARRON = '#7a6e63', '#e2d6c0', '#5b3a29'
PORTADAS_COLORES = ('#6b4f3a', '#3f5d54', '#7b3f4a', '#4a4e69', '#8a6a3b', '#355c7d')

FUENTE_MARCA = ('Georgia', 22, 'bold')
FUENTE_TITULO = ('Georgia', 13, 'bold')
FUENTE_GRANDE = ('Georgia', 20, 'bold')
FUENTE = ('Helvetica', 11)
FUENTE_CHICA = ('Helvetica', 10)

ANCHO_PORTADA, ALTO_PORTADA = 150, 225              # tarjeta
ANCHO_DETALLE, ALTO_DETALLE = 220, 330              # ficha
ANCHO_TARJETA = 190
RE_ARCHIVO = re.compile(r'^[0-9a-f-]{36}\.(png|jpe?g|webp|gif)$')


def aplicar_estilo(raiz):
    """Tema claro de libreria para TODA la app (tambien las pestañas de
    administracion). Se usa 'clam' porque respeta los colores en macOS."""
    raiz.configure(bg=PAPEL)
    for patron, valor in (('*Text.background', TARJETA), ('*Text.foreground', TINTA),
                          ('*Listbox.background', TARJETA), ('*Listbox.foreground', TINTA),
                          ('*Listbox.selectBackground', DORADO), ('*Listbox.selectForeground', TINTA),
                          ('*Text.selectBackground', DORADO), ('*Text.selectForeground', TINTA)):
        raiz.option_add(patron, valor)
    estilo = ttk.Style(raiz)
    estilo.theme_use('clam')
    estilo.configure('.', background=PAPEL, foreground=TINTA, font=FUENTE, bordercolor=BORDE,
                     lightcolor=PAPEL, darkcolor=PAPEL, focuscolor=DORADO)
    estilo.configure('TFrame', background=PAPEL)
    estilo.configure('TLabel', background=PAPEL, foreground=TINTA)
    estilo.configure('TLabelframe', background=PAPEL, bordercolor=BORDE)
    estilo.configure('TLabelframe.Label', background=PAPEL, foreground=MARRON, font=('Georgia', 11, 'bold'))
    estilo.configure('TButton', background='#eadfc8', foreground=TINTA, padding=(12, 5),
                     bordercolor=BORDE, relief='flat')
    estilo.map('TButton', background=[('active', '#dccdaa'), ('disabled', '#efe9dc')],
               foreground=[('disabled', '#a99d8f')])
    estilo.configure('Accent.TButton', background=BURDEOS, foreground='white', font=('Helvetica', 11, 'bold'))
    estilo.map('Accent.TButton', background=[('active', '#a63a46'), ('disabled', '#c9a3a8')],
               foreground=[('disabled', '#f4e7e9')])
    estilo.configure('Nav.TButton', background=VERDE, foreground='white', padding=(12, 6), borderwidth=0)
    estilo.map('Nav.TButton', background=[('active', '#2d5a4f')])
    estilo.configure('TEntry', fieldbackground='white', bordercolor=BORDE, padding=4)
    estilo.configure('TCombobox', fieldbackground='white', background='#eadfc8', padding=3)
    estilo.configure('TSpinbox', fieldbackground='white', padding=3)
    estilo.configure('TCheckbutton', background=PAPEL)
    estilo.configure('TNotebook', background=PAPEL, bordercolor=BORDE)
    estilo.configure('TNotebook.Tab', background='#eadfc8', padding=(14, 6), foreground=TINTA)
    estilo.map('TNotebook.Tab', background=[('selected', TARJETA)], foreground=[('selected', BURDEOS)])
    estilo.configure('Treeview', background=TARJETA, fieldbackground=TARJETA, foreground=TINTA,
                     rowheight=26, bordercolor=BORDE)
    estilo.configure('Treeview.Heading', background=VERDE, foreground='white',
                     font=('Helvetica', 10, 'bold'), padding=5, relief='flat')
    estilo.map('Treeview', background=[('selected', DORADO)], foreground=[('selected', TINTA)])
    estilo.map('Treeview.Heading', background=[('active', '#2d5a4f')])
    estilo.configure('Vertical.TScrollbar', background='#eadfc8', troughcolor=PAPEL, bordercolor=PAPEL)


# =============================================================================
# Carrito (en memoria; se vacia al cerrar la app)
# =============================================================================
class Carrito:
    def __init__(self):
        self.lineas = {}                     # isbn -> {'libro': dict, 'cantidad': int}

    def agregar(self, libro, cantidad=1):
        """Devuelve la cantidad que quedo en el carrito (tope: el stock)."""
        existente = self.lineas.get(libro['isbn'], {'libro': libro, 'cantidad': 0})
        existente['libro'] = libro
        existente['cantidad'] = max(0, min(existente['cantidad'] + cantidad, int(libro['stock'])))
        if existente['cantidad']:
            self.lineas[libro['isbn']] = existente
        return existente['cantidad']

    def fijar(self, isbn, cantidad):
        if isbn in self.lineas:
            tope = int(self.lineas[isbn]['libro']['stock'])
            self.lineas[isbn]['cantidad'] = max(1, min(int(cantidad), tope))

    def quitar(self, isbn):
        self.lineas.pop(isbn, None)

    def vaciar(self):
        self.lineas.clear()

    def cantidad_total(self):
        return sum(l['cantidad'] for l in self.lineas.values())

    def total(self):
        return sum(float(l['libro']['price']) * l['cantidad'] for l in self.lineas.values())


# =============================================================================
# Portadas
# =============================================================================
def archivo_portada(libro):
    """Nombre de archivo de la portada del libro, o None si no hay (o es raro)."""
    imagenes = libro.get('images') or []
    elegida = next((i for i in imagenes if i.get('cover')), imagenes[0] if imagenes else None)
    archivo = (elegida or {}).get('file') or ''
    return archivo if RE_ARCHIVO.match(archivo) else None


class Portadas:
    """Descarga (en hilo) y guarda en memoria las portadas ya convertidas."""

    def __init__(self, app):
        self.app = app
        self.bytes, self.imagenes, self.fallidas = {}, {}, set()

    def _imagen(self, datos, ancho, alto):
        if ImageTk is not None:
            imagen = Image.open(io.BytesIO(datos)).convert('RGBA')
            imagen.thumbnail((ancho, alto))
            return ImageTk.PhotoImage(imagen)
        foto = tk.PhotoImage(data=base64.b64encode(datos))          # solo PNG/GIF
        return foto.subsample(max(1, round(foto.width() / ancho)), max(1, round(foto.height() / alto)))

    def pedir(self, archivo, ancho, alto, listo):
        """listo(PhotoImage|None) se llama en el hilo de Tk."""
        clave = (archivo, ancho)
        if clave in self.imagenes:
            return listo(self.imagenes[clave])
        if archivo in self.fallidas:
            return listo(None)

        def terminar(datos):
            try:
                self.bytes[archivo] = datos
                self.imagenes[clave] = self._imagen(datos, ancho, alto)
            except Exception:                           # noqa: BLE001 - formato que Tk no lee
                self.fallidas.add(archivo)
                return listo(None)
            listo(self.imagenes[clave])

        def fallo(_error):
            self.fallidas.add(archivo)
            listo(None)

        if archivo in self.bytes:
            return terminar(self.bytes[archivo])
        self.app.en_hilo(lambda: self.app.api.descargar('/uploads/' + archivo), terminar, fallo)

    def poner(self, etiqueta, libro, ancho, alto):
        """Pinta la portada en `etiqueta` (un tk.Label). Mientras llega, queda el
        marcador con el titulo; si falla, se queda con el."""
        archivo = archivo_portada(libro)
        if not archivo:
            return

        def listo(imagen):
            if imagen is not None and etiqueta.winfo_exists():
                etiqueta.configure(image=imagen, text='', bg=TARJETA)
                etiqueta.image = imagen                  # evita que el recolector la borre
        self.pedir(archivo, ancho, alto, listo)


def marcador_portada(padre, libro, ancho, alto):
    """Cuadro de color con el titulo: lo que se ve sin portada (o mientras llega)."""
    marco = tk.Frame(padre, width=ancho, height=alto, bg=TARJETA)
    marco.pack_propagate(False)
    color = PORTADAS_COLORES[sum(map(ord, libro['isbn'])) % len(PORTADAS_COLORES)]
    etiqueta = tk.Label(marco, text=libro['title'], bg=color, fg='white', wraplength=ancho - 16,
                        font=('Georgia', 11, 'bold'), justify='center', compound='center')
    etiqueta.pack(fill='both', expand=True)
    return marco, etiqueta


def insignia_stock(stock):
    stock = int(stock)
    if stock <= 0:
        return 'Agotado', GRIS
    if stock <= 5:
        return 'Ultimas {} piezas'.format(stock), BURDEOS
    return 'Disponible', '#2e7d4f'


# =============================================================================
# Pantalla: tienda (cuadricula)
# =============================================================================
ORDENES = (('Titulo (A-Z)', 'titulo', 'asc'), ('Precio: menor a mayor', 'precio', 'asc'),
           ('Precio: mayor a menor', 'precio', 'desc'), ('Mas existencias', 'stock', 'desc'))


class PantallaTienda(tk.Frame):

    def __init__(self, app, padre):
        super().__init__(padre, bg=PAPEL)
        self.app = app
        self.libros, self.consulta, self.columnas = [], '', 0

        barra = tk.Frame(self, bg=PAPEL)
        barra.pack(fill='x', padx=18, pady=(14, 4))
        self.titulo = tk.Label(barra, text='Catalogo', bg=PAPEL, fg=VERDE, font=FUENTE_GRANDE)
        self.titulo.pack(side='left')
        self.cuenta = tk.Label(barra, text='', bg=PAPEL, fg=GRIS, font=FUENTE_CHICA)
        self.cuenta.pack(side='left', padx=12, pady=(8, 0))
        self.orden = tk.StringVar(value=ORDENES[0][0])
        combo = ttk.Combobox(barra, textvariable=self.orden, values=[o[0] for o in ORDENES],
                             state='readonly', width=22)
        combo.pack(side='right')
        combo.bind('<<ComboboxSelected>>', lambda _e: self.cargar(self.consulta))
        tk.Label(barra, text='Ordenar por:', bg=PAPEL, fg=GRIS, font=FUENTE_CHICA).pack(side='right', padx=6)

        cuerpo = tk.Frame(self, bg=PAPEL)
        cuerpo.pack(fill='both', expand=True, padx=(18, 4), pady=(0, 6))
        self.lienzo = tk.Canvas(cuerpo, bg=PAPEL, highlightthickness=0)
        barra_v = ttk.Scrollbar(cuerpo, orient='vertical', command=self.lienzo.yview)
        self.lienzo.configure(yscrollcommand=barra_v.set)
        barra_v.pack(side='right', fill='y')
        self.lienzo.pack(side='left', fill='both', expand=True)
        self.rejilla = tk.Frame(self.lienzo, bg=PAPEL)
        self.ventana = self.lienzo.create_window((0, 0), window=self.rejilla, anchor='nw')
        self.rejilla.bind('<Configure>', lambda _e: self.lienzo.configure(scrollregion=self.lienzo.bbox('all')))
        self.lienzo.bind('<Configure>', self._al_redimensionar)
        self.bind_all('<MouseWheel>', self._rueda, add='+')

    def _rueda(self, evento):
        if self.winfo_ismapped():
            self.lienzo.yview_scroll(int(-1 * (evento.delta if abs(evento.delta) < 40 else evento.delta / 120)), 'units')

    def _al_redimensionar(self, evento):
        self.lienzo.itemconfigure(self.ventana, width=evento.width)
        columnas = max(1, evento.width // ANCHO_TARJETA)
        if columnas != self.columnas and self.libros:
            self.pintar()

    # --- Datos ---------------------------------------------------------------
    def cargar(self, consulta=None):
        self.consulta = (consulta if consulta is not None else self.consulta).strip()
        _nombre, campo, sentido = next(o for o in ORDENES if o[0] == self.orden.get())
        ruta = '/books/search?q={}&'.format(_q(self.consulta)) if self.consulta else '/books?limite=200&'
        ruta += 'orden={}&dir={}'.format(campo, sentido)
        self.app.en_hilo(lambda: self.app.api.get(ruta, autenticada=False)['books'], self.mostrar)

    def mostrar(self, libros):
        self.libros = libros
        self.titulo.configure(text='Resultados para "{}"'.format(self.consulta) if self.consulta else 'Catalogo')
        self.cuenta.configure(text='{} libros'.format(len(libros)))
        self.pintar()

    def pintar(self):
        for hijo in self.rejilla.winfo_children():
            hijo.destroy()
        ancho = max(self.lienzo.winfo_width(), ANCHO_TARJETA)
        self.columnas = max(1, ancho // ANCHO_TARJETA)
        if not self.libros:
            tk.Label(self.rejilla, text='No se encontraron libros.', bg=PAPEL, fg=GRIS,
                     font=FUENTE_TITULO).grid(row=0, column=0, padx=20, pady=40)
        for i, libro in enumerate(self.libros):
            self._tarjeta(libro).grid(row=i // self.columnas, column=i % self.columnas, padx=7, pady=7, sticky='n')

    def _tarjeta(self, libro):
        t = tk.Frame(self.rejilla, bg=TARJETA, highlightbackground=BORDE, highlightthickness=1, padx=8, pady=8)
        marco, etiqueta = marcador_portada(t, libro, ANCHO_PORTADA, ALTO_PORTADA)
        marco.pack()
        self.app.portadas.poner(etiqueta, libro, ANCHO_PORTADA, ALTO_PORTADA)
        for w in (marco, etiqueta):
            w.bind('<Button-1>', lambda _e, l=libro: self.app.ver_libro(l))
            w.configure(cursor='hand2')
        tk.Label(t, text=libro['title'], bg=TARJETA, fg=TINTA, font=FUENTE_TITULO if len(libro['title']) < 40 else ('Georgia', 11, 'bold'),
                 wraplength=ANCHO_PORTADA, justify='left', anchor='w', height=2).pack(fill='x', pady=(6, 0))
        autores = ', '.join(a['name'] for a in libro.get('authors', [])) or 'Autor desconocido'
        tk.Label(t, text=autores, bg=TARJETA, fg=GRIS, font=FUENTE_CHICA, wraplength=ANCHO_PORTADA,
                 justify='left', anchor='w', height=2).pack(fill='x')
        tk.Label(t, text=dinero(libro['price']), bg=TARJETA, fg=BURDEOS, font=('Georgia', 15, 'bold'),
                 anchor='w').pack(fill='x')
        texto, color = insignia_stock(libro['stock'])
        tk.Label(t, text=texto, bg=TARJETA, fg=color, font=FUENTE_CHICA, anchor='w').pack(fill='x', pady=(0, 6))
        botones = tk.Frame(t, bg=TARJETA)
        botones.pack(fill='x')
        ttk.Button(botones, text='Ver', width=5, command=lambda: self.app.ver_libro(libro)).pack(side='left')
        b = ttk.Button(botones, text='Agregar', style='Accent.TButton', command=lambda: self.app.agregar_al_carrito(libro))
        b.pack(side='right')
        if int(libro['stock']) <= 0:
            b.state(['disabled'])
        return t


def _q(texto):
    from urllib.parse import quote
    return quote(texto)


# =============================================================================
# Pantalla: detalle del libro
# =============================================================================
class PantallaDetalle(tk.Frame):

    def __init__(self, app, padre):
        super().__init__(padre, bg=PAPEL)
        self.app = app
        self.libro = None
        self.cuerpo = tk.Frame(self, bg=PAPEL)
        self.cuerpo.pack(fill='both', expand=True, padx=30, pady=20)

    def mostrar(self, libro):
        self.libro = libro
        for hijo in self.cuerpo.winfo_children():
            hijo.destroy()
        ttk.Button(self.cuerpo, text='← Volver al catalogo', command=lambda: self.app.mostrar_pantalla('tienda')).pack(anchor='w')
        fila = tk.Frame(self.cuerpo, bg=PAPEL)
        fila.pack(fill='both', expand=True, pady=14)
        marco, etiqueta = marcador_portada(fila, libro, ANCHO_DETALLE, ALTO_DETALLE)
        marco.pack(side='left', anchor='n')
        self.app.portadas.poner(etiqueta, libro, ANCHO_DETALLE, ALTO_DETALLE)

        datos = tk.Frame(fila, bg=PAPEL)
        datos.pack(side='left', fill='both', expand=True, padx=(28, 0))
        tk.Label(datos, text=libro['title'], bg=PAPEL, fg=TINTA, font=('Georgia', 24, 'bold'),
                 wraplength=620, justify='left', anchor='w').pack(fill='x')
        autores = ', '.join(a['name'] for a in libro.get('authors', [])) or 'Autor desconocido'
        tk.Label(datos, text='de ' + autores, bg=PAPEL, fg=MARRON, font=('Georgia', 14, 'italic'),
                 anchor='w').pack(fill='x', pady=(2, 10))
        tk.Label(datos, text=dinero(libro['price']), bg=PAPEL, fg=BURDEOS, font=('Georgia', 28, 'bold'),
                 anchor='w').pack(fill='x')
        texto, color = insignia_stock(libro['stock'])
        tk.Label(datos, text=texto, bg=PAPEL, fg=color, font=('Helvetica', 12, 'bold'), anchor='w').pack(fill='x', pady=(0, 10))
        ficha = '   ·   '.join(str(x) for x in (libro.get('format'), libro.get('year'), 'ISBN ' + libro['isbn']) if x)
        tk.Label(datos, text=ficha, bg=PAPEL, fg=GRIS, font=FUENTE, anchor='w').pack(fill='x')
        if libro.get('genres'):
            tk.Label(datos, text='Generos: ' + ', '.join(libro['genres']), bg=PAPEL, fg=GRIS, font=FUENTE,
                     anchor='w').pack(fill='x', pady=(2, 0))

        compra = tk.Frame(datos, bg=PAPEL)
        compra.pack(fill='x', pady=16)
        cantidad = tk.StringVar(value='1')
        ttk.Spinbox(compra, from_=1, to=max(1, int(libro['stock'])), textvariable=cantidad, width=4).pack(side='left')
        b = ttk.Button(compra, text='Agregar al carrito', style='Accent.TButton',
                       command=lambda: self.app.agregar_al_carrito(libro, _entero(cantidad.get())))
        b.pack(side='left', padx=10)
        if int(libro['stock']) <= 0:
            b.state(['disabled'])

        conceptos = libro.get('concepts') or []
        if conceptos:
            marco_c = ttk.LabelFrame(datos, text='En este libro se explica', padding=8)
            marco_c.pack(fill='both', expand=True)
            texto_c = tk.Text(marco_c, height=7, wrap='word', relief='flat', font=FUENTE)
            for c in conceptos:
                texto_c.insert('end', c['term'] + ': ', 'negrita')
                texto_c.insert('end', c.get('description', '') + '\n')
            texto_c.tag_configure('negrita', font=('Helvetica', 11, 'bold'), foreground=VERDE)
            texto_c.configure(state='disabled')
            texto_c.pack(fill='both', expand=True)


def _entero(texto, defecto=1):
    try:
        return max(1, int(texto))
    except (TypeError, ValueError):
        return defecto


# =============================================================================
# Pantalla: carrito y pago
# =============================================================================
class PantallaCarrito(tk.Frame):

    def __init__(self, app, padre):
        super().__init__(padre, bg=PAPEL)
        self.app = app
        tk.Label(self, text='Tu carrito', bg=PAPEL, fg=VERDE, font=FUENTE_GRANDE).pack(anchor='w', padx=24, pady=(16, 6))
        self.cuerpo = tk.Frame(self, bg=PAPEL)
        self.cuerpo.pack(fill='both', expand=True, padx=24)
        self.pie = tk.Frame(self, bg=PAPEL)
        self.pie.pack(fill='x', padx=24, pady=14)

    def refrescar(self):
        for contenedor in (self.cuerpo, self.pie):
            for hijo in contenedor.winfo_children():
                hijo.destroy()
        carrito = self.app.carrito
        if not carrito.lineas:
            tk.Label(self.cuerpo, text='Tu carrito esta vacio.', bg=PAPEL, fg=GRIS, font=FUENTE_TITULO).pack(pady=40)
            ttk.Button(self.cuerpo, text='Ir al catalogo', command=lambda: self.app.mostrar_pantalla('tienda')).pack()
            return
        for isbn, linea in list(carrito.lineas.items()):
            self._fila(isbn, linea)
        tk.Label(self.pie, text='Total: ' + dinero(carrito.total()), bg=PAPEL, fg=BURDEOS,
                 font=('Georgia', 20, 'bold')).pack(side='left')
        ttk.Button(self.pie, text='Finalizar compra', style='Accent.TButton', command=self.finalizar).pack(side='right')
        ttk.Button(self.pie, text='Vaciar', command=self._vaciar).pack(side='right', padx=8)
        ttk.Button(self.pie, text='Seguir comprando', command=lambda: self.app.mostrar_pantalla('tienda')).pack(side='right')

    def _fila(self, isbn, linea):
        libro = linea['libro']
        f = tk.Frame(self.cuerpo, bg=TARJETA, highlightbackground=BORDE, highlightthickness=1, padx=10, pady=8)
        f.pack(fill='x', pady=4)
        marco, etiqueta = marcador_portada(f, libro, 46, 69)
        marco.pack(side='left')
        self.app.portadas.poner(etiqueta, libro, 46, 69)
        info = tk.Frame(f, bg=TARJETA)
        info.pack(side='left', fill='x', expand=True, padx=12)
        tk.Label(info, text=libro['title'], bg=TARJETA, fg=TINTA, font=FUENTE_TITULO, anchor='w').pack(fill='x')
        tk.Label(info, text='{} c/u'.format(dinero(libro['price'])), bg=TARJETA, fg=GRIS, font=FUENTE_CHICA, anchor='w').pack(fill='x')
        cantidad = tk.StringVar(value=str(linea['cantidad']))
        ttk.Spinbox(f, from_=1, to=max(1, int(libro['stock'])), textvariable=cantidad, width=4,
                    command=lambda: self._cambiar(isbn, cantidad)).pack(side='left', padx=8)
        tk.Label(f, text=dinero(float(libro['price']) * linea['cantidad']), bg=TARJETA, fg=BURDEOS,
                 font=('Georgia', 13, 'bold'), width=10).pack(side='left')
        ttk.Button(f, text='Quitar', command=lambda: (self.app.carrito.quitar(isbn), self.app.actualizar_carrito())).pack(side='left')

    def _cambiar(self, isbn, variable):
        self.app.carrito.fijar(isbn, _entero(variable.get()))
        self.app.actualizar_carrito()

    def _vaciar(self):
        if messagebox.askyesno('Vaciar carrito', '¿Quitar todos los libros del carrito?'):
            self.app.carrito.vaciar()
            self.app.actualizar_carrito()

    # --- Compra --------------------------------------------------------------
    def finalizar(self):
        if not self.app.api.sesion_activa:
            messagebox.showinfo('Inicia sesion', 'Para comprar necesitas iniciar sesion. Tu carrito se conserva.')
            return self.app.pedir_login(al_entrar=self.finalizar)
        carrito = self.app.carrito
        lineas = [(i, l['libro'], l['cantidad']) for i, l in carrito.lineas.items()]

        def trabajo():
            # El catalogo no expone el id numerico que piden los pedidos: se
            # resuelve por ISBN con la lista de libros pedibles.
            ids = {l['isbn']: l['id'] for l in self.app.api.get('/orders/books')}
            faltan = [libro['title'] for isbn, libro, _c in lineas if isbn not in ids]
            if faltan:
                raise ValueError('ya no estan disponibles: ' + ', '.join(faltan))
            carga = {'lineas': [{'libro_id': ids[isbn], 'cantidad': c} for isbn, _l, c in lineas]}
            return self.app.api.peticion('POST', '/orders', carga)

        self.app.en_hilo(trabajo, self._pagar, self._fallo_pedido)

    def _fallo_pedido(self, error):
        if isinstance(error, ValueError):
            self.app.carrito.vaciar()
            self.app.actualizar_carrito()
            return messagebox.showwarning('Carrito', 'Algunos libros {}.'.format(error))
        self.app.mostrar_error(error)       # p. ej. 409: "No hay existencias suficientes..."

    def _pagar(self, pedido):
        self.app.carrito.vaciar()
        self.app.actualizar_carrito()
        self.app.pie('Pedido {} creado: {}.'.format(pedido['id'], dinero(pedido['total'])))
        DialogoPago(self.app, pedido)


class DialogoPago(tk.Toplevel):
    """Pago simulado: metodo y referencia opcional. No hay datos de tarjeta."""

    def __init__(self, app, pedido):
        super().__init__(app)
        self.app, self.pedido = app, pedido
        self.title('Pagar pedido {}'.format(pedido['id']))
        self.configure(bg=PAPEL)
        self.transient(app)
        self.resizable(False, False)
        marco = ttk.Frame(self, padding=18)
        marco.pack()
        ttk.Label(marco, text='¡Pedido {} creado!'.format(pedido['id']), font=('Georgia', 16, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w')
        ttk.Label(marco, text='Total a pagar: ' + dinero(pedido['total']), font=('Georgia', 13)).grid(row=1, column=0, columnspan=2, sticky='w', pady=(4, 12))
        ttk.Label(marco, text='Metodo de pago:').grid(row=2, column=0, sticky='w', pady=3)
        self.metodo = tk.StringVar(value=METODOS_PAGO[0])
        ttk.Combobox(marco, textvariable=self.metodo, values=METODOS_PAGO, state='readonly', width=18).grid(row=2, column=1, padx=8)
        ttk.Label(marco, text='Referencia (opc.):').grid(row=3, column=0, sticky='w', pady=3)
        self.referencia = tk.StringVar()
        ttk.Entry(marco, textvariable=self.referencia, width=21).grid(row=3, column=1, padx=8)
        ttk.Label(marco, text='Pago simulado: no se piden datos de tarjeta.', foreground=GRIS).grid(row=4, column=0, columnspan=2, sticky='w', pady=(10, 0))
        botones = ttk.Frame(marco)
        botones.grid(row=5, column=0, columnspan=2, sticky='e', pady=(14, 0))
        ttk.Button(botones, text='Pagar despues', command=self._despues).pack(side='left', padx=6)
        ttk.Button(botones, text='Pagar ahora', style='Accent.TButton', command=self._pagar).pack(side='left')
        self.grab_set()

    def _despues(self):
        self.destroy()
        messagebox.showinfo('Pedido pendiente', 'Tu pedido {} quedo pendiente. Puedes pagarlo en '
                            'Mi cuenta → Pagos.'.format(self.pedido['id']))

    def _pagar(self):
        carga = {'pedido_id': self.pedido['id'], 'monto': round(float(self.pedido['total']), 2), 'metodo': self.metodo.get()}
        if self.referencia.get().strip():
            carga['referencia'] = self.referencia.get().strip()

        def listo(pago):
            self.destroy()
            messagebox.showinfo('¡Gracias por tu compra!', 'Pedido {} {}.\nTotal: {}'.format(
                self.pedido['id'], pago.get('pedido_estado', 'pagado'), dinero(self.pedido['total'])))
            self.app.recargar_tienda()

        def fallo(error):
            self.app.mostrar_error(error)
        self.app.en_hilo(lambda: self.app.api.peticion('POST', '/payments', carga), listo, fallo)

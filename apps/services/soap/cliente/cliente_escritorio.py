# =============================================================================
# cliente/cliente_escritorio.py — aplicacion de escritorio de la Libreria Online.
#
#     python3 cliente/cliente_escritorio.py
#     ENDPOINT=http://VM:5001/soap API_BASE=https://IP CA_CERT=ruta.crt \
#         python3 cliente/cliente_escritorio.py
#
# Tkinter viene con Python: el cliente no necesita instalar nada, que es justo
# lo que se espera de una aplicacion de escritorio repartida a varios usuarios.
#
# QUE HAY AQUI
#   - Pestaña "Clasificador Cloud": el cliente SOAP del Ejercicio 03, tal cual
#     (sin login; va por ENDPOINT, normalmente tras un tunel SSH).
#   - Pestañas Libros, Autores, Usuarios, Pedidos y Pagos: CRUD sobre los
#     microservicios REST por HTTPS (API_BASE), con JWT. Viven en pestanas.py;
#     la red y la sesion, en api_rest.py.
#   - Barra superior: inicio/cierre de sesion y SEMAFOROS de los servicios
#     (verde = ok, amarillo = funciona degradado porque Redis cayo, rojo = no
#     responde), sondeados cada 10 segundos.
#
# REGLA QUE ESTE ARCHIVO RESPETA
#   La GUI NO sabe que existe PostgreSQL ni Redis. No hay cadena de conexion, no
#   hay SQL, no hay nombres de tabla. Sus unicas puertas al sistema son el
#   endpoint SOAP y los endpoints REST. Si manana cambia el motor de base de
#   datos, aqui no se toca nada.
#
# El armado del sobre SOAP esta en este archivo a proposito, para que se vea el
# trabajo que hace un cliente manual frente al generado desde el WSDL
# (tests/cliente_zeep.py, Tarea 4).
# =============================================================================

import os
import queue
import sys
import threading
import tkinter as tk
import traceback
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from tkinter import messagebox, ttk
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_rest import API_BASE, SERVICIOS, ClienteApi, ErrorApi, probar_tcp  # noqa: E402
from pestanas import PESTANAS                                                # noqa: E402
from tienda import (BORDE, GRIS, PAPEL, VERDE, FUENTE_MARCA, Carrito,        # noqa: E402
                    PantallaCarrito, PantallaDetalle, PantallaTienda, Portadas, aplicar_estilo)

ENDPOINT = os.getenv('ENDPOINT', 'http://127.0.0.1:5001/soap')
TIPO_CLIENTE = 'escritorio-tkinter'
ID_CLIENTE = os.getenv('ID_CLIENTE', 'estacion-01')

NS = 'http://udem.edu/iac/libreria/clasificador'
NS_SOAP = 'http://schemas.xmlsoap.org/soap/envelope/'
MODELOS = ('IaaS', 'PaaS', 'SaaS', 'FaaS')

# Mensajes por codigo de Fault. La GUI traduce el codigo estable del contrato a
# algo que una persona entiende; NUNCA muestra el faultstring crudo ni nada que
# venga del servidor sin filtrar.
MENSAJES = {
    'CLASIFICACION_DUPLICADA': 'Ya clasificaste ese concepto antes. '
                               'Elige otro de la lista.',
    'CONCEPTO_INEXISTENTE': 'Ese concepto ya no esta disponible. '
                            'Actualiza la lista.',
    'LIBRO_INEXISTENTE': 'El libro asociado ya no esta en el catalogo. '
                         'Actualiza la lista.',
    'MODELO_INVALIDO': 'Selecciona uno de los cuatro modelos de la lista.',
    'DATO_INVALIDO': 'Revisa los datos capturados: hay un campo incompleto '
                     'o mal escrito.',
    'CLASIFICADOR_INEXISTENTE': 'Todavia no tienes clasificaciones registradas '
                                'con ese correo.',
    'NO_AUTORIZADO': 'No tienes permiso para esta operacion.',
    'XML_INVALIDO': 'La aplicacion envio una peticion mal formada. '
                    'Reporta este error.',
    'OPERACION_DESCONOCIDA': 'Esta version de la aplicacion no coincide con el '
                             'servidor. Actualizala.',
    'ERROR_SERVIDOR': 'El servicio no esta disponible en este momento. '
                      'Intenta mas tarde.',
}


class ErrorServicio(Exception):
    def __init__(self, codigo, campo=None):
        self.codigo = codigo
        self.campo = campo
        super().__init__(MENSAJES.get(codigo,
                                      'Ocurrio un problema al contactar el servicio.'))


# -----------------------------------------------------------------------------
# Capa SOAP del cliente
# -----------------------------------------------------------------------------
def _campo(padre, nombre, valor):
    elemento = ET.SubElement(padre, '{%s}%s' % (NS, nombre))
    elemento.text = str(valor)
    return elemento


def _llamar(operacion, construir=None):
    ET.register_namespace('soap', NS_SOAP)
    ET.register_namespace('tns', NS)

    sobre = ET.Element('{%s}Envelope' % NS_SOAP)
    cuerpo = ET.SubElement(sobre, '{%s}Body' % NS_SOAP)
    nodo = ET.SubElement(cuerpo, '{%s}%s' % (NS, operacion))
    if construir:
        construir(nodo)

    datos = ET.tostring(sobre, encoding='utf-8', xml_declaration=True)
    peticion = urllib.request.Request(
        ENDPOINT, data=datos,
        headers={'Content-Type': 'text/xml; charset=utf-8',
                 'SOAPAction': '{}/{}'.format(NS, operacion)})
    try:
        with urllib.request.urlopen(peticion, timeout=20) as respuesta:
            crudo = respuesta.read()
    except urllib.error.HTTPError as error:
        crudo = error.read()
    except urllib.error.URLError:
        raise ErrorServicio('ERROR_SERVIDOR')

    try:
        raiz = ET.fromstring(crudo)
    except ET.ParseError:
        raise ErrorServicio('ERROR_SERVIDOR')

    cuerpo_resp = raiz.find('{%s}Body' % NS_SOAP)
    fault = cuerpo_resp.find('{%s}Fault' % NS_SOAP)
    if fault is not None:
        codigo = fault.find('.//{%s}codigo' % NS)
        campo_error = fault.find('.//{%s}campo' % NS)
        raise ErrorServicio(codigo.text if codigo is not None else 'ERROR_SERVIDOR',
                            campo_error.text if campo_error is not None else None)
    return list(cuerpo_resp)[0]


def pedir_pendientes(correo=None, limite=50):
    def construir(nodo):
        if correo:
            _campo(nodo, 'correo', correo)
        _campo(nodo, 'limite', limite)

    respuesta = _llamar('ObtenerConceptosPendientes', construir)
    conceptos = []
    for nodo in respuesta.findall('{%s}concepto' % NS):
        conceptos.append({
            'id': nodo.findtext('{%s}conceptoId' % NS),
            'termino': nodo.findtext('{%s}termino' % NS),
            'definicion': nodo.findtext('{%s}definicion' % NS),
            'isbn': nodo.findtext('{%s}isbn' % NS),
            'libro': nodo.findtext('{%s}libro' % NS),
            'categoria': nodo.findtext('{%s}categoria' % NS),
        })
    return respuesta.findtext('{%s}total' % NS), conceptos


def enviar_clasificacion(datos, concepto, modelo):
    def construir(nodo):
        clasificador = ET.SubElement(nodo, '{%s}clasificador' % NS)
        _campo(clasificador, 'nombre', datos['nombre'])
        _campo(clasificador, 'apellidos', datos['apellidos'])
        _campo(clasificador, 'correo', datos['correo'])
        _campo(nodo, 'conceptoId', concepto['id'])
        _campo(nodo, 'isbn', concepto['isbn'])
        _campo(nodo, 'modelo', modelo)
        cliente = ET.SubElement(nodo, '{%s}cliente' % NS)
        _campo(cliente, 'tipo', TIPO_CLIENTE)
        _campo(cliente, 'identificador', ID_CLIENTE)

    respuesta = _llamar('RegistrarClasificacion', construir)
    return {
        'id': respuesta.findtext('{%s}clasificacionId' % NS),
        'termino': respuesta.findtext('{%s}termino' % NS),
        'peticiones': respuesta.findtext('{%s}peticionesAtendidas' % NS),
    }


def pedir_progreso(correo):
    respuesta = _llamar('ObtenerProgresoUsuario',
                        lambda nodo: _campo(nodo, 'correo', correo))
    return {
        'nombre': respuesta.findtext('{%s}nombre' % NS),
        'clasificados': respuesta.findtext('{%s}totalClasificados' % NS),
        'pendientes': respuesta.findtext('{%s}totalPendientes' % NS),
        'modelos': [(m.findtext('{%s}modelo' % NS), m.findtext('{%s}total' % NS))
                    for m in respuesta.findall('{%s}porModelo' % NS)],
    }


# -----------------------------------------------------------------------------
# Interfaz
# -----------------------------------------------------------------------------
class Aplicacion(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title('Libreria Online — Cliente de escritorio')
        self.geometry('1180x820')
        self.conceptos = []
        self.api = ClienteApi()
        self._cola = queue.Queue()
        self._red_avisada = False
        self._sesion_ui = False
        self.luces = {}                      # nombre -> (canvas, figura, detalle)

        aplicar_estilo(self)
        self.minsize(980, 640)
        self.carrito = Carrito()
        self.portadas = Portadas(self)
        self.pantalla = 'tienda'
        self._encabezado()
        self._pie_estado()
        contenedor = tk.Frame(self, bg=PAPEL)
        contenedor.pack(fill='both', expand=True)
        contenedor.grid_rowconfigure(0, weight=1)
        contenedor.grid_columnconfigure(0, weight=1)
        self.pantallas = {'tienda': PantallaTienda(self, contenedor),
                          'detalle': PantallaDetalle(self, contenedor),
                          'carrito': PantallaCarrito(self, contenedor),
                          'panel': ttk.Frame(contenedor)}
        for pantalla in self.pantallas.values():
            pantalla.grid(row=0, column=0, sticky='nsew')
        # El "panel" es lo que antes era toda la aplicacion: las pestañas de
        # administracion y el clasificador SOAP, ahora detras de Mi cuenta /
        # Administracion segun el rol.
        self.cuaderno = ttk.Notebook(self.pantallas['panel'])
        self.cuaderno.pack(fill='both', expand=True, padx=10, pady=8)
        self.pestanas = []
        for titulo, clase in PESTANAS:
            pestana = clase(self, self.cuaderno)
            self.cuaderno.add(pestana, text=titulo)
            self.pestanas.append(pestana)
        self.cuaderno.bind('<<NotebookTabChanged>>', self._pestana_elegida)

        marco = ttk.Frame(self.cuaderno, padding=12)
        self.cuaderno.add(marco, text='Clasificador Cloud')
        self.tab_soap = marco

        datos = ttk.LabelFrame(marco, text='Clasificador', padding=10)
        datos.pack(fill='x')
        self.nombre = self._entrada(datos, 'Nombre', 0)
        self.apellidos = self._entrada(datos, 'Apellidos', 1)
        self.correo = self._entrada(datos, 'Correo', 2, ancho=34)

        acciones = ttk.Frame(marco, padding=(0, 10))
        acciones.pack(fill='x')
        ttk.Button(acciones, text='Cargar conceptos pendientes',
                   command=self.cargar).pack(side='left')
        ttk.Button(acciones, text='Ver mi progreso',
                   command=self.progreso).pack(side='left', padx=8)

        lista = ttk.LabelFrame(marco, text='Conceptos pendientes', padding=10)
        lista.pack(fill='both', expand=True)
        self.tabla = ttk.Treeview(
            lista, columns=('termino', 'libro', 'categoria'),
            show='headings', height=12)
        for columna, titulo, ancho in (('termino', 'Concepto', 170),
                                       ('libro', 'Libro', 380),
                                       ('categoria', 'Categoria', 150)):
            self.tabla.heading(columna, text=titulo)
            self.tabla.column(columna, width=ancho, anchor='w')
        # Las filas ya clasificadas en esta sesion se quedan a la vista, en gris.
        self.tabla.tag_configure('registrado', foreground='#888888')
        self.tabla.pack(fill='both', expand=True, side='left')
        barra = ttk.Scrollbar(lista, orient='vertical', command=self.tabla.yview)
        barra.pack(side='right', fill='y')
        self.tabla.configure(yscrollcommand=barra.set)
        self.tabla.bind('<<TreeviewSelect>>', self.mostrar_definicion)

        self.definicion = tk.Text(marco, height=4, wrap='word')
        self.definicion.pack(fill='x', pady=(10, 0))
        self.definicion.configure(state='disabled')

        envio = ttk.Frame(marco, padding=(0, 10))
        envio.pack(fill='x')
        ttk.Label(envio, text='Modelo Cloud:').pack(side='left')
        self.modelo = tk.StringVar(value=MODELOS[0])
        ttk.Combobox(envio, textvariable=self.modelo, values=MODELOS,
                     state='readonly', width=8).pack(side='left', padx=8)
        ttk.Button(envio, text='Registrar clasificacion',
                   command=self.clasificar).pack(side='left')

        self.estado = ttk.Label(marco, text='Endpoint: {}'.format(ENDPOINT),
                                foreground='#555')
        self.estado.pack(fill='x', pady=(8, 0))

        self.protocol('WM_DELETE_WINDOW', self._salir)
        self.mostrar_pantalla('tienda')
        self.after(80, self._vaciar_cola)
        self._sesion_cambio()
        self.pantallas['tienda'].cargar()
        self._sondear()
        self.after(30000, self._mantener_sesion)

    def _entrada(self, padre, etiqueta, fila, ancho=24):
        ttk.Label(padre, text=etiqueta + ':').grid(row=fila, column=0,
                                                   sticky='w', pady=3)
        variable = tk.StringVar()
        ttk.Entry(padre, textvariable=variable, width=ancho).grid(
            row=fila, column=1, sticky='w', padx=8)
        return variable

    # --- Acciones ------------------------------------------------------------
    def _datos(self, exigir_todo=True):
        datos = {'nombre': self.nombre.get().strip(),
                 'apellidos': self.apellidos.get().strip(),
                 'correo': self.correo.get().strip()}
        faltan = [k for k, v in datos.items() if not v] if exigir_todo \
            else ([] if datos['correo'] else ['correo'])
        if faltan:
            messagebox.showwarning('Datos incompletos',
                                   'Captura: {}'.format(', '.join(faltan)))
            return None
        return datos

    # No todo Fault es un error. Pedir el progreso antes de la primera
    # clasificacion devuelve CLASIFICADOR_INEXISTENTE, que para quien estrena la
    # aplicacion es el estado normal: pintarlo de rojo como una falla asusta sin
    # motivo. El contrato hace bien en distinguirlo de un correo valido con cero
    # registros; la GUI hace mal si presenta las dos cosas igual.
    ESPERADOS = {'CLASIFICADOR_INEXISTENTE'}

    def _fallo(self, error):
        # Al usuario, el mensaje traducido. El codigo tecnico va al pie, para
        # que pueda reportarlo sin que la ventana parezca un stack trace.
        if error.codigo in self.ESPERADOS:
            messagebox.showinfo('Sin registros', str(error))
            self.estado.configure(text=str(error), foreground='#555')
        else:
            messagebox.showerror('No se pudo completar', str(error))
            self.estado.configure(
                text='{}  ({})'.format(error, error.codigo), foreground='#b00')

    def cargar(self):
        correo = self.correo.get().strip() or None
        try:
            total, conceptos = pedir_pendientes(correo)
        except ErrorServicio as error:
            return self._fallo(error)
        self.conceptos = conceptos
        self.tabla.delete(*self.tabla.get_children())
        for indice, concepto in enumerate(conceptos):
            self.tabla.insert('', 'end', iid=str(indice),
                              values=(concepto['termino'], concepto['libro'],
                                      concepto['categoria']))
        self.estado.configure(
            text='{} conceptos mostrados de {} pendientes'.format(
                len(conceptos), total), foreground='#555')

    def mostrar_definicion(self, _evento=None):
        seleccion = self.tabla.selection()
        self.definicion.configure(state='normal')
        self.definicion.delete('1.0', 'end')
        if seleccion:
            concepto = self.conceptos[int(seleccion[0])]
            self.definicion.insert('1.0', '{}: {}'.format(concepto['termino'],
                                                          concepto['definicion']))
        self.definicion.configure(state='disabled')

    def clasificar(self):
        datos = self._datos()
        if not datos:
            return
        seleccion = self.tabla.selection()
        if not seleccion:
            return messagebox.showwarning('Sin seleccion',
                                          'Elige un concepto de la lista.')
        concepto = self.conceptos[int(seleccion[0])]
        try:
            resultado = enviar_clasificacion(datos, concepto, self.modelo.get())
        except ErrorServicio as error:
            return self._fallo(error)
        messagebox.showinfo(
            'Registrado',
            '"{}" quedo clasificado como {}.'.format(resultado['termino'],
                                                     self.modelo.get()))
        self.estado.configure(
            text='Registro #{}. Peticiones atendidas a este cliente: {}'.format(
                resultado['id'], resultado['peticiones']), foreground='#060')

        # La lista NO se recarga aqui. Recargar borraria de la vista el concepto
        # recien clasificado —ObtenerConceptosPendientes filtra por correo— justo
        # cuando el usuario quiere ver el resultado de lo que hizo, y ademas
        # dejaria fuera de alcance el conflicto por duplicado. La fila se marca y
        # se queda; el boton Cargar refresca cuando el usuario lo decida.
        fila = seleccion[0]
        valores = list(self.tabla.item(fila, 'values'))
        if not valores[0].startswith('✓'):
            valores[0] = '✓ {}'.format(valores[0])
            self.tabla.item(fila, values=valores)
        self.tabla.item(fila, tags=('registrado',))

    def progreso(self):
        datos = self._datos(exigir_todo=False)
        if not datos:
            return
        try:
            progreso = pedir_progreso(datos['correo'])
        except ErrorServicio as error:
            return self._fallo(error)
        desglose = '\n'.join('  {}: {}'.format(m, t)
                             for m, t in progreso['modelos'])
        messagebox.showinfo(
            'Progreso',
            '{}\n\nClasificados: {}\nPendientes: {}\n\nPor modelo:\n{}'.format(
                progreso['nombre'], progreso['clasificados'],
                progreso['pendientes'], desglose))


    # =========================================================================
    # Sesion, hilos y semaforos (REST)
    # =========================================================================
    COLORES = {'verde': '#2e9e44', 'amarillo': '#e0a800', 'rojo': '#c62828', 'gris': '#9e9e9e'}

    PIE = '#efe6d2'

    def _encabezado(self):
        cab = tk.Frame(self, bg=VERDE)
        cab.pack(side='top', fill='x')
        marca = tk.Label(cab, text='Libreria Online', bg=VERDE, fg='white', font=FUENTE_MARCA, cursor='hand2')
        marca.pack(side='left', padx=(18, 22), pady=10)
        marca.bind('<Button-1>', lambda _e: self.mostrar_pantalla('tienda'))
        self.busqueda = tk.StringVar()
        entrada = ttk.Entry(cab, textvariable=self.busqueda, width=36)
        entrada.pack(side='left', ipady=3)
        entrada.bind('<Return>', self.buscar)
        ttk.Button(cab, text='Buscar', style='Nav.TButton', command=self.buscar).pack(side='left', padx=6)
        # De derecha a izquierda: sesion, nombre, [panel], carrito, catalogo.
        self.boton_sesion = ttk.Button(cab, text='Iniciar sesion', style='Nav.TButton', command=self._clic_sesion)
        self.boton_sesion.pack(side='right', padx=(4, 16))
        self.etiqueta_sesion = tk.Label(cab, text='', bg=VERDE, fg='#d8e4df', font=('Helvetica', 10))
        self.etiqueta_sesion.pack(side='right', padx=6)
        self.boton_carrito = ttk.Button(cab, text='Carrito (0)', style='Nav.TButton',
                                        command=lambda: self.mostrar_pantalla('carrito'))
        self.boton_carrito.pack(side='right', padx=4)
        ttk.Button(cab, text='Catalogo', style='Nav.TButton',
                   command=lambda: self.mostrar_pantalla('tienda')).pack(side='right', padx=4)
        self.boton_panel = ttk.Button(cab, text='Mi cuenta', style='Nav.TButton',
                                      command=lambda: self.mostrar_pantalla('panel'))

    def _pie_estado(self):
        pie = tk.Frame(self, bg=self.PIE, highlightbackground=BORDE, highlightthickness=1)
        pie.pack(side='bottom', fill='x')
        self.pie_global = tk.Label(pie, text='Servidor: {}'.format(API_BASE), bg=self.PIE, fg=GRIS,
                                   anchor='w', padx=12, pady=4, font=('Helvetica', 10))
        self.pie_global.pack(side='left')
        luces = tk.Frame(pie, bg=self.PIE)
        luces.pack(side='right', padx=8)
        tk.Label(luces, text='Estado del sistema:', bg=self.PIE, fg=GRIS, font=('Helvetica', 10)).pack(side='left', padx=(0, 4))
        for nombre in SERVICIOS + ('redis', 'soap'):
            marco = tk.Frame(luces, bg=self.PIE)
            marco.pack(side='left', padx=4)
            lienzo = tk.Canvas(marco, width=14, height=14, highlightthickness=0, bg=self.PIE)
            figura = lienzo.create_oval(2, 2, 13, 13, fill=self.COLORES['gris'], outline='#666')
            lienzo.pack(side='left')
            tk.Label(marco, text=nombre, bg=self.PIE, fg=GRIS, font=('Helvetica', 10)).pack(side='left', padx=(3, 0))
            self.luces[nombre] = [lienzo, figura, 'Sin datos todavia.']
            lienzo.bind('<Button-1>', lambda _e, n=nombre: messagebox.showinfo(n, self.luces[n][2]))

    # --- Navegacion y tienda ---------------------------------------------------
    def mostrar_pantalla(self, nombre):
        self.pantalla = nombre
        self.pantallas[nombre].tkraise()
        if nombre == 'carrito':
            self.pantallas['carrito'].refrescar()
        elif nombre == 'panel':
            self._pestana_elegida()

    def buscar(self, _evento=None):
        self.mostrar_pantalla('tienda')
        self.pantallas['tienda'].cargar(self.busqueda.get())

    def recargar_tienda(self):
        self.pantallas['tienda'].cargar()

    def ver_libro(self, libro):
        self.pantallas['detalle'].mostrar(libro)
        self.mostrar_pantalla('detalle')

    def agregar_al_carrito(self, libro, cantidad=1):
        antes = self.carrito.lineas.get(libro['isbn'], {}).get('cantidad', 0)
        ahora = self.carrito.agregar(libro, cantidad)
        self.actualizar_carrito()
        if ahora == 0:
            return messagebox.showwarning('Sin existencias', '"{}" esta agotado.'.format(libro['title']))
        if ahora < antes + cantidad:
            return self.pie('Solo hay {} existencias de "{}".'.format(libro['stock'], libro['title']), '#b00')
        self.pie('"{}" agregado al carrito.'.format(libro['title']), '#060')

    def actualizar_carrito(self):
        self.boton_carrito.configure(text='Carrito ({})'.format(self.carrito.cantidad_total()))
        if self.pantalla == 'carrito':
            self.pantallas['carrito'].refrescar()

    def pedir_login(self, al_entrar=None):
        self._dialogo_login(al_entrar)

    def _pintar_luz(self, nombre, color, detalle):
        lienzo, figura, _ = self.luces[nombre]
        lienzo.itemconfigure(figura, fill=self.COLORES[color])
        self.luces[nombre][2] = detalle

    def _sondear(self):
        """Cada 10 s, en hilos: un semaforo por servicio, uno de Redis (lo que
        informan los servicios) y uno del SOAP."""
        def trabajo():
            with ThreadPoolExecutor(max_workers=len(SERVICIOS) + 1) as pool:
                futuros = {s: pool.submit(self.api.semaforo, s) for s in SERVICIOS}
                soap = pool.submit(probar_tcp, ENDPOINT)
                return {s: f.result() for s, f in futuros.items()}, soap.result()

        def listo(resultado):
            servicios, soap_arriba = resultado
            for nombre, (color, detalle, _redis) in servicios.items():
                self._pintar_luz(nombre, color, detalle)
            estados = [r for (_c, _d, r) in servicios.values() if r]
            if any(r == 'caido' for r in estados):
                self._pintar_luz('redis', 'rojo', 'Redis no responde: sin sesiones ni revocacion; '
                                 'solo siguen las lecturas del catalogo.')
            elif any(r == 'no configurado' for r in estados):
                self._pintar_luz('redis', 'amarillo', 'Algun servicio no tiene REDIS_URL.')
            elif estados:
                self._pintar_luz('redis', 'verde', 'Redis responde en todos los servicios.')
            else:
                self._pintar_luz('redis', 'gris', 'Ningun servicio responde.')
            self._pintar_luz('soap', 'verde' if soap_arriba else 'rojo',
                             'Escucha en {}.'.format(ENDPOINT) if soap_arriba
                             else 'Nada escucha en {} (¿falta el tunel SSH?).'.format(ENDPOINT))
            self.after(10000, self._sondear)

        def fallo(_error):
            self.after(10000, self._sondear)
        self.en_hilo(trabajo, listo, fallo)

    def _mantener_sesion(self):
        """Renueva el JWT ANTES de que caduque, aunque la persona no toque nada."""
        def siguiente(_=None):
            self.after(30000, self._mantener_sesion)

        def listo(vigente):
            if not vigente and self._sesion_ui:
                self._sesion_cambio()
                messagebox.showwarning('Sesion', 'Tu sesion termino. Inicia sesion de nuevo.')
            siguiente()
        if self.api.sesion_activa:
            self.en_hilo(self.api.renovar_si_hace_falta, listo, lambda e: siguiente())
        else:
            siguiente()

    def en_hilo(self, trabajo, ok=None, error=None):
        """Corre `trabajo` fuera del hilo de Tk y entrega el resultado dentro."""
        def correr():
            try:
                resultado = trabajo()
            except BaseException as excepcion:      # noqa: BLE001 - se entrega a la GUI
                self._cola.put((error or self.mostrar_error, excepcion))
                return
            self._cola.put((self._exito, None))
            if ok:
                self._cola.put((ok, resultado))
        threading.Thread(target=correr, daemon=True).start()

    def _exito(self, _=None):
        self._red_avisada = False

    def _vaciar_cola(self):
        try:
            while True:
                funcion, argumento = self._cola.get_nowait()
                try:
                    funcion(argumento)
                except Exception:                   # noqa: BLE001 - un callback roto no mata la GUI
                    traceback.print_exc()
        except queue.Empty:
            pass
        self.after(80, self._vaciar_cola)

    def pie(self, texto, color='#555'):
        self.pie_global.configure(text=texto, foreground=color)

    def mostrar_error(self, error):
        if not isinstance(error, ErrorApi):
            traceback.print_exception(type(error), error, error.__traceback__)
            self.pie('Ocurrio un error inesperado.', '#b00')
            return messagebox.showerror('No se pudo completar',
                                        'Ocurrio un error inesperado. Intenta de nuevo.')
        self.pie(error.mensaje, '#b00')
        if self._sesion_ui and not self.api.sesion_activa:      # el servidor dio la sesion por perdida
            self._sesion_cambio()
            return messagebox.showwarning('Sesion', error.mensaje)
        if error.estado == 0:
            # Sin red: se avisa UNA vez por caida, no una vez por pestaña.
            if not self._red_avisada:
                self._red_avisada = True
                messagebox.showerror('Sin conexion', error.texto())
            return
        mostrar = messagebox.showerror if error.estado >= 500 else messagebox.showwarning
        mostrar('No se pudo completar', error.texto())

    def _clic_sesion(self):
        if self.api.sesion_activa:
            self.en_hilo(self.api.cerrar_sesion,
                         lambda _: (self._sesion_cambio(), self.mostrar_pantalla('tienda')))
        else:
            self._dialogo_login()

    def _dialogo_login(self, al_entrar=None):
        ventana = tk.Toplevel(self)
        ventana.title('Iniciar sesion')
        ventana.configure(bg=PAPEL)
        ventana.transient(self)
        ventana.resizable(False, False)
        marco = ttk.Frame(ventana, padding=18)
        marco.pack()
        correo, clave = tk.StringVar(), tk.StringVar()
        ttk.Label(marco, text='Correo:').grid(row=0, column=0, sticky='w', pady=3)
        entrada = ttk.Entry(marco, textvariable=correo, width=34)
        entrada.grid(row=0, column=1, padx=8)
        ttk.Label(marco, text='Contraseña:').grid(row=1, column=0, sticky='w', pady=3)
        ttk.Entry(marco, textvariable=clave, width=34, show='*').grid(row=1, column=1, padx=8)
        mensaje = ttk.Label(marco, text='', foreground='#b00', wraplength=300)
        mensaje.grid(row=2, column=0, columnspan=2, sticky='w', pady=(6, 0))

        def entrar(_evento=None):
            usuario, secreto = correo.get().strip(), clave.get()
            clave.set('')                    # la contraseña no se queda en el widget
            if not usuario or not secreto:
                mensaje.configure(text='Captura el correo y la contraseña.')
                return
            mensaje.configure(text='Entrando...', foreground='#555')

            def fallo(error):
                mensaje.configure(text=error.texto() if isinstance(error, ErrorApi)
                                  else 'No se pudo iniciar sesion.', foreground='#b00')
            self.en_hilo(lambda: self.api.iniciar_sesion(usuario, secreto),
                         lambda _: (ventana.destroy(), self._sesion_cambio(),
                                    al_entrar() if al_entrar else None), fallo)
        ttk.Button(marco, text='Entrar', command=entrar).grid(row=3, column=1, sticky='e', pady=(10, 0))
        ventana.bind('<Return>', entrar)
        entrada.focus_set()
        ventana.grab_set()

    LECTOR_VE = ('Usuarios', 'Pedidos', 'Pagos')

    def _sesion_cambio(self):
        activa = self.api.sesion_activa
        self._sesion_ui = activa
        rol = self.api.usuario.get('rol') if activa else None
        if activa:
            u = self.api.usuario
            self.etiqueta_sesion.configure(text=u.get('nombre') or u.get('email'))
            self.boton_sesion.configure(text='Cerrar sesion')
            self.boton_panel.configure(text='Administracion' if rol == 'admin' else 'Mi cuenta')
            self.boton_panel.pack(side='right', padx=4, before=self.boton_carrito)
        else:
            self.etiqueta_sesion.configure(text='')
            self.boton_sesion.configure(text='Iniciar sesion')
            self.boton_panel.pack_forget()
            if self.pantalla == 'panel':
                self.mostrar_pantalla('tienda')
        # Cada rol ve solo lo suyo. Ocultar es ayuda visual: el servidor decide.
        for (titulo, _clase), pestana in zip(PESTANAS, self.pestanas):
            ver = rol == 'admin' or (rol == 'lector' and titulo in self.LECTOR_VE)
            self.cuaderno.tab(pestana, state='normal' if ver else 'hidden')
        self.cuaderno.tab(self.tab_soap, state='normal' if rol == 'admin' else 'hidden')
        visibles = [p for p in self.cuaderno.tabs() if self.cuaderno.tab(p, 'state') == 'normal']
        if visibles and self.cuaderno.select() not in visibles:
            self.cuaderno.select(visibles[0])
        for pestana in self.pestanas:
            pestana.sesion_cambio()

    def _pestana_elegida(self, _evento=None):
        actual = self.cuaderno.nametowidget(self.cuaderno.select())
        if actual in self.pestanas and (self.api.sesion_activa or not actual.requiere_sesion):
            actual.cargar()

    def _salir(self):
        """Al cerrar la ventana se revoca el JWT: un token no debe sobrevivir a la app."""
        if self.api.sesion_activa:
            cierre = threading.Thread(target=lambda: self._intentar(self.api.cerrar_sesion), daemon=True)
            cierre.start()
            cierre.join(3)
        self.destroy()

    @staticmethod
    def _intentar(funcion):
        try:
            funcion()
        except Exception:                           # noqa: BLE001 - al salir no hay nada mas que hacer
            pass


if __name__ == '__main__':
    Aplicacion().mainloop()

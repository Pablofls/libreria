# =============================================================================
# cliente/cliente_escritorio.py — Parte 8: aplicacion de escritorio como
# cliente SOAP.
#
#     python3 cliente/cliente_escritorio.py
#     ENDPOINT=http://VM:5001/soap python3 cliente/cliente_escritorio.py
#
# Tkinter viene con Python: el cliente no necesita instalar nada, que es justo
# lo que se espera de una aplicacion de escritorio repartida a varios usuarios.
#
# REGLA DEL EJERCICIO QUE ESTE ARCHIVO RESPETA
#   La GUI NO sabe que existe PostgreSQL. No hay cadena de conexion, no hay SQL,
#   no hay nombres de tabla. Su unica puerta al sistema es el endpoint SOAP.
#   Si manana el modulo cambia de motor de base de datos, aqui no se toca nada.
#
# El armado del sobre esta en este archivo a proposito, para que se vea el
# trabajo que hace un cliente manual frente al generado desde el WSDL
# (tests/cliente_zeep.py, Tarea 4).
# =============================================================================

import os
import tkinter as tk
import urllib.error
import urllib.request
from tkinter import messagebox, ttk
from xml.etree import ElementTree as ET

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
        self.title('Clasificador Cloud — Libreria Online')
        self.geometry('900x620')
        self.conceptos = []

        marco = ttk.Frame(self, padding=12)
        marco.pack(fill='both', expand=True)

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

    def _fallo(self, error):
        # Al usuario, el mensaje traducido. El codigo tecnico va al pie, para
        # que pueda reportarlo sin que la ventana parezca un stack trace.
        messagebox.showerror('No se pudo completar', str(error))
        self.estado.configure(text='Ultimo error: {}'.format(error.codigo),
                              foreground='#b00')

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
        self.cargar()

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


if __name__ == '__main__':
    Aplicacion().mainloop()

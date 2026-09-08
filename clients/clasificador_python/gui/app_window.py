"""
Ventana principal de la aplicación (CustomTkinter).

Responsabilidad única: presentar la interfaz gráfica, recoger las entradas
del usuario y mostrar el resultado. Toda la lógica de clasificación y NLP
reside en CloudClassifier; esta clase solo la invoca y renderiza la respuesta.

Secciones:
    - Cabecera: título y subtítulo.
    - Pestaña "Clasificador local" (EG1): formulario, resultado y panel NLP.
    - Pestaña "Cliente SOAP" (EG3): catálogo real consumido por SOAP.

MODO CLIENTE SOAP — Parte 8 del Ejercicio Guiado 3
    La segunda pestaña añade el modo cliente SOAP sin tocar el clasificador
    local: ambos conviven. Captura nombre, apellidos y correo, trae los
    conceptos pendientes del catálogo real, deja que el clasificador NLP del
    EG1 SUGIERA el modelo a partir de la definición, y registra la decisión
    en el servicio.

    La GUI no conoce PostgreSQL. No hay cadena de conexión, ni SQL, ni nombres
    de tabla: su única puerta al sistema es el endpoint SOAP, y todo el XML
    vive en soap_cliente.py.
"""

import customtkinter as ctk
from tkinter import messagebox
from classifier.cloud_classifier import CloudClassifier
from classifier.exceptions import ClassificationException
from classifier.models import CloudModel
from classifier.result import ClassificationResult
import soap_cliente

# ── Paleta de colores ──────────────────────────────────────────────────────────
MODEL_COLORS = {
    CloudModel.IAAS:    "#3498DB",
    CloudModel.PAAS:    "#2ECC71",
    CloudModel.SAAS:    "#9B59B6",
    CloudModel.FAAS:    "#E67E22",
    CloudModel.UNKNOWN: "#95A5A6",
}
HEADER_BG   = "#2C3E50"
FORM_BG     = "#FFFFFF"
WINDOW_BG   = "#F5F6FA"
NLP_BG      = "#1E272E"
TEXT_LIGHT  = "#FFFFFF"
TEXT_MUTED  = "#BDC3C7"
BORDER      = "#DCE0E6"
MAX_CHARS   = 2000


class AppWindow(ctk.CTk):
    """
    Ventana principal. Recibe un CloudClassifier ya construido para
    que GUI y CLI compartan exactamente la misma instancia de lógica.
    """

    def __init__(self, classifier: CloudClassifier) -> None:
        super().__init__()

        self._classifier = classifier
        self._nlp_visible = False

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.title("Cloud Models Classifier")
        self.geometry("760x860")
        self.resizable(False, False)
        self.configure(fg_color=WINDOW_BG)

        self._build_ui()
        # Ctrl+Return activa la clasificación desde cualquier widget
        self.bind_all("<Control-Return>", lambda _: self._on_classify())

    # ── Construcción de la interfaz ────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._build_header()

        # Dos modos que conviven: el clasificador local del EG1 y el cliente
        # SOAP del EG3. Se separan en pestañas para que ninguno estorbe al otro.
        self._tabs = ctk.CTkTabview(self, fg_color=WINDOW_BG,
                                    segmented_button_selected_color=HEADER_BG,
                                    segmented_button_selected_hover_color="#3D5166")
        self._tabs.pack(fill="both", expand=True, padx=8, pady=(8, 8))
        tab_local = self._tabs.add("Clasificador local")
        tab_soap  = self._tabs.add("Cliente SOAP")

        self._build_form_card(tab_local)
        self._build_result_panel(tab_local)
        self._build_nlp_panel(tab_local)
        self._build_soap_tab(tab_soap)

    def _build_header(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color=HEADER_BG, corner_radius=0, height=62)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        inner = ctk.CTkFrame(hdr, fg_color="transparent")
        inner.pack(side="left", padx=20, pady=10)

        ctk.CTkLabel(inner, text="Cloud Models Classifier",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=TEXT_LIGHT).pack(anchor="w")
        ctk.CTkLabel(inner, text="IaaS · PaaS · SaaS · FaaS  —  NLP Pipeline",
                     font=ctk.CTkFont(size=11),
                     text_color=TEXT_MUTED).pack(anchor="w")

    def _build_form_card(self, parent) -> None:
        card = ctk.CTkFrame(parent, fg_color=FORM_BG, corner_radius=10,
                            border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=8, pady=(8, 0))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=18)

        # ── Fila nombre / apellido ──────────────────────────────────────────
        name_row = ctk.CTkFrame(inner, fg_color="transparent")
        name_row.pack(fill="x", pady=(0, 10))
        name_row.columnconfigure(0, weight=1)
        name_row.columnconfigure(1, weight=1)

        self._name_entry     = self._labeled_entry(name_row, "Nombre:",   0)
        self._lastname_entry = self._labeled_entry(name_row, "Apellido:", 1)

        # ── Área de descripción ─────────────────────────────────────────────
        ctk.CTkLabel(inner, text="Descripción del servicio Cloud:",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color="#2C3E50").pack(anchor="w")

        self._text_box = ctk.CTkTextbox(inner, height=170, corner_radius=6,
                                        border_width=1, border_color=BORDER,
                                        font=ctk.CTkFont(size=13))
        self._text_box.pack(fill="x", pady=(5, 0))
        self._text_box.bind("<KeyRelease>", self._update_char_count)

        # Contador de caracteres
        self._char_label = ctk.CTkLabel(inner, text=f"0 / {MAX_CHARS}",
                                        font=ctk.CTkFont(size=10),
                                        text_color="#999999")
        self._char_label.pack(anchor="e", pady=(2, 10))

        # Botón clasificar
        ctk.CTkButton(inner, text="Clasificar", width=140, height=36,
                      font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color=HEADER_BG, hover_color="#3D5166",
                      corner_radius=6,
                      command=self._on_classify).pack(anchor="w")

    def _labeled_entry(self, parent, label: str, col: int) -> ctk.CTkEntry:
        """Crea un frame con etiqueta + entry y lo ubica en la columna indicada."""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=0, column=col, sticky="ew", padx=(0, 12))

        ctk.CTkLabel(frame, text=label,
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color="#2C3E50").pack(anchor="w")
        entry = ctk.CTkEntry(frame, height=34, corner_radius=6,
                             border_width=1, border_color=BORDER,
                             font=ctk.CTkFont(size=13))
        entry.pack(fill="x", pady=(3, 0))
        return entry

    def _build_result_panel(self, parent) -> None:
        self._result_frame = ctk.CTkFrame(parent, fg_color=MODEL_COLORS[CloudModel.UNKNOWN],
                                          corner_radius=0, height=72)
        self._result_frame.pack(fill="x", padx=8, pady=(8, 0))
        self._result_frame.pack_propagate(False)

        row = ctk.CTkFrame(self._result_frame, fg_color="transparent")
        row.pack(fill="both", expand=True, padx=16, pady=10)

        self._model_badge = ctk.CTkLabel(row, text="—",
                                         font=ctk.CTkFont(size=20, weight="bold"),
                                         text_color=TEXT_LIGHT, width=72)
        self._model_badge.pack(side="left")

        self._result_desc = ctk.CTkLabel(
            row,
            text="Ingresa una descripción y presiona Clasificar.",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_LIGHT,
            anchor="w", justify="left", wraplength=530,
        )
        self._result_desc.pack(side="left", fill="x", expand=True)

    def _build_nlp_panel(self, parent) -> None:
        """Panel oscuro con tokens NLP y barras de puntaje (inicialmente oculto)."""
        self._nlp_parent = parent
        self._nlp_frame = ctk.CTkFrame(parent, fg_color=NLP_BG, corner_radius=0)
        # No se empaqueta aquí; se muestra tras la primera clasificación

        inner = ctk.CTkFrame(self._nlp_frame, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=12)

        ctk.CTkLabel(inner, text="Pipeline NLP — Tokens extraídos:",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=TEXT_MUTED).pack(anchor="w")

        self._tokens_label = ctk.CTkLabel(inner, text="",
                                          font=ctk.CTkFont(family="Courier", size=11),
                                          text_color="#82E0AA",
                                          anchor="w", justify="left", wraplength=640)
        self._tokens_label.pack(anchor="w", pady=(2, 10))

        # Cuatro barras de puntaje
        bars_frame = ctk.CTkFrame(inner, fg_color="transparent")
        bars_frame.pack(fill="x")
        bars_frame.columnconfigure(0, weight=0)
        bars_frame.columnconfigure(1, weight=1)
        bars_frame.columnconfigure(2, weight=0)
        bars_frame.columnconfigure(3, weight=0)
        bars_frame.columnconfigure(4, weight=1)
        bars_frame.columnconfigure(5, weight=0)

        self._bars: dict = {}
        self._score_labels: dict = {}

        bar_data = [
            (CloudModel.IAAS, "IaaS", 0),
            (CloudModel.PAAS, "PaaS", 2),
            (CloudModel.SAAS, "SaaS", 0),
            (CloudModel.FAAS, "FaaS", 2),
        ]
        for model, name, col_offset in bar_data:
            row_idx = 0 if col_offset == 0 else 0
            # Two pairs per row
            r = 0 if model in (CloudModel.IAAS, CloudModel.PAAS) else 1

            ctk.CTkLabel(bars_frame, text=name, width=38,
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=MODEL_COLORS[model]).grid(
                row=r, column=col_offset, sticky="w", pady=3)

            bar = ctk.CTkProgressBar(bars_frame, height=10,
                                     progress_color=MODEL_COLORS[model],
                                     fg_color="#37474F", corner_radius=4)
            bar.set(0)
            bar.grid(row=r, column=col_offset + 1, sticky="ew", padx=(4, 6), pady=3)

            lbl = ctk.CTkLabel(bars_frame, text="0", width=26,
                               font=ctk.CTkFont(size=11, weight="bold"),
                               text_color=TEXT_LIGHT)
            lbl.grid(row=r, column=col_offset + 2, sticky="e", pady=3)

            self._bars[model] = bar
            self._score_labels[model] = lbl

    # ── Eventos ────────────────────────────────────────────────────────────────

    def _on_classify(self) -> None:
        """
        Reúne los datos del formulario, valida los campos de usuario (GUI)
        y delega la clasificación a CloudClassifier.
        """
        name      = self._name_entry.get().strip()
        last_name = self._lastname_entry.get().strip()
        text      = self._text_box.get("1.0", "end").strip()

        # Validación de campos de presentación (responsabilidad de la GUI)
        try:
            self._validate_user_fields(name, last_name)
        except ValueError as exc:
            messagebox.showwarning("Aviso", str(exc))
            return

        # Clasificación — cada tipo de error se maneja por separado
        try:
            result = self._classifier.classify(text)
            self._show_result(name, last_name, result)
            self._show_nlp_details(result)

        except ClassificationException as exc:
            messagebox.showwarning("Aviso", str(exc))
        except Exception as exc:
            messagebox.showerror("Error inesperado",
                                 f"Ocurrió un error al clasificar:\n{exc}")

    # ── Validación de campos de usuario ───────────────────────────────────────

    def _validate_user_fields(self, name: str, last_name: str) -> None:
        """
        Valida nombre y apellido (datos de presentación, no del clasificador).
        Lanza ValueError con mensaje descriptivo si falla alguna condición.
        """
        import re
        if not name or not last_name:
            raise ValueError("Por favor, ingresa tu nombre y apellido.")
        if not re.fullmatch(r"[\w\sáéíóúüñÁÉÍÓÚÜÑ]+", name, re.UNICODE):
            raise ValueError("El nombre solo puede contener letras.")
        if not re.fullmatch(r"[\w\sáéíóúüñÁÉÍÓÚÜÑ]+", last_name, re.UNICODE):
            raise ValueError("El apellido solo puede contener letras.")

    # ── Actualización de la UI ─────────────────────────────────────────────────

    def _update_char_count(self, _event=None) -> None:
        count = len(self._text_box.get("1.0", "end").strip())
        self._char_label.configure(
            text=f"{count} / {MAX_CHARS}",
            text_color="#E74C3C" if count > MAX_CHARS * 0.9 else "#999999",
        )

    def _show_result(self, name: str, last_name: str,
                     result: ClassificationResult) -> None:
        model = result.model
        color = MODEL_COLORS[model]

        self._result_frame.configure(fg_color=color)
        self._model_badge.configure(text=model.label,
                                    font=ctk.CTkFont(size=18, weight="bold"))
        self._result_desc.configure(
            text=f"{name} {last_name} — Modelo detectado: {model.label}\n"
                 f"{model.description}"
        )

    def _show_nlp_details(self, result: ClassificationResult) -> None:
        """Actualiza tokens y barras de puntaje; hace visible el panel NLP."""
        stemmed = result.processed_text.stemmed
        tokens_str = "  ·  ".join(stemmed) if stemmed else "(sin tokens significativos)"
        self._tokens_label.configure(text=tokens_str)

        max_s = result.max_score
        for model, bar in self._bars.items():
            score = result.scores.get(model, 0)
            bar.set(score / max_s)
            self._score_labels[model].configure(text=str(score))

        if not self._nlp_visible:
            self._nlp_frame.pack(fill="x", padx=8, pady=(6, 12))
            self._nlp_visible = True

    # ══════════════════════════════════════════════════════════════════════════
    #  MODO CLIENTE SOAP  —  Parte 8 del Ejercicio Guiado 3
    # ══════════════════════════════════════════════════════════════════════════

    def _build_soap_tab(self, parent) -> None:
        """Pestaña que consume el módulo SOAP: catálogo real, no texto libre."""
        self._conceptos: list = []
        self._concepto_sel = ctk.IntVar(value=-1)

        # ── Identidad del clasificador (lo exige el enunciado) ───────────────
        card = ctk.CTkFrame(parent, fg_color=FORM_BG, corner_radius=10,
                            border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=8, pady=(8, 0))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=14)

        fila = ctk.CTkFrame(inner, fg_color="transparent")
        fila.pack(fill="x")
        for col in range(3):
            fila.columnconfigure(col, weight=1)
        self._soap_nombre    = self._labeled_entry(fila, "Nombre:",    0)
        self._soap_apellidos = self._labeled_entry(fila, "Apellidos:", 1)
        self._soap_correo    = self._labeled_entry(fila, "Correo:",    2)

        botones = ctk.CTkFrame(inner, fg_color="transparent")
        botones.pack(fill="x", pady=(12, 0))
        ctk.CTkButton(botones, text="Cargar conceptos pendientes", width=210,
                      height=32, font=ctk.CTkFont(size=12, weight="bold"),
                      fg_color=HEADER_BG, hover_color="#3D5166",
                      command=self._soap_cargar).pack(side="left")
        ctk.CTkButton(botones, text="Ver mi progreso", width=130, height=32,
                      font=ctk.CTkFont(size=12), fg_color="#7F8C8D",
                      hover_color="#95A5A6",
                      command=self._soap_progreso).pack(side="left", padx=8)

        # ── Lista de conceptos pendientes ────────────────────────────────────
        ctk.CTkLabel(parent, text="Conceptos pendientes del catálogo:",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color="#2C3E50").pack(anchor="w", padx=12, pady=(12, 2))

        self._lista = ctk.CTkScrollableFrame(parent, fg_color=FORM_BG,
                                             border_width=1, border_color=BORDER,
                                             height=190)
        self._lista.pack(fill="x", padx=8)

        # ── Definición del concepto seleccionado ─────────────────────────────
        self._definicion = ctk.CTkTextbox(parent, height=68, corner_radius=6,
                                          border_width=1, border_color=BORDER,
                                          font=ctk.CTkFont(size=12))
        self._definicion.pack(fill="x", padx=8, pady=(8, 0))
        self._definicion.configure(state="disabled")

        # ── Modelo y acciones ────────────────────────────────────────────────
        acciones = ctk.CTkFrame(parent, fg_color="transparent")
        acciones.pack(fill="x", padx=8, pady=8)

        ctk.CTkLabel(acciones, text="Modelo Cloud:",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color="#2C3E50").pack(side="left")
        self._modelo_sel = ctk.CTkSegmentedButton(
            acciones, values=list(soap_cliente.MODELOS),
            selected_color=HEADER_BG, selected_hover_color="#3D5166")
        self._modelo_sel.set(soap_cliente.MODELOS[0])
        self._modelo_sel.pack(side="left", padx=10)

        ctk.CTkButton(acciones, text="Sugerir con el clasificador local",
                      width=210, height=32, font=ctk.CTkFont(size=12),
                      fg_color="#16A085", hover_color="#1ABC9C",
                      command=self._soap_sugerir).pack(side="left")

        ctk.CTkButton(parent, text="Registrar clasificación", height=36,
                      font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color=HEADER_BG, hover_color="#3D5166",
                      command=self._soap_registrar).pack(fill="x", padx=8)

        self._soap_estado = ctk.CTkLabel(
            parent, text=f"Endpoint: {soap_cliente.ENDPOINT}",
            font=ctk.CTkFont(size=11), text_color="#7F8C8D",
            anchor="w", justify="left", wraplength=700)
        self._soap_estado.pack(fill="x", padx=12, pady=(8, 4))

    # ── Datos del formulario ──────────────────────────────────────────────────

    def _soap_datos(self, exigir_todo: bool = True):
        datos = {"nombre":    self._soap_nombre.get().strip(),
                 "apellidos": self._soap_apellidos.get().strip(),
                 "correo":    self._soap_correo.get().strip()}
        faltan = ([k for k, v in datos.items() if not v] if exigir_todo
                  else ([] if datos["correo"] else ["correo"]))
        if faltan:
            messagebox.showwarning("Datos incompletos",
                                   "Captura: " + ", ".join(faltan))
            return None
        return datos

    def _soap_fallo(self, error: "soap_cliente.ErrorServicio") -> None:
        """Traduce el Fault. Nunca muestra el faultstring crudo del servidor.

        Un Fault esperado —pedir el progreso antes de la primera clasificación—
        no es una falla: para quien estrena la aplicación es el estado normal y
        pintarlo de rojo asusta sin motivo.
        """
        if error.esperado:
            messagebox.showinfo("Sin registros", str(error))
            self._soap_estado.configure(text=str(error), text_color="#7F8C8D")
        else:
            messagebox.showerror("No se pudo completar", str(error))
            self._soap_estado.configure(
                text="{}  ({})".format(error, error.codigo), text_color="#C0392B")

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _soap_cargar(self) -> None:
        correo = self._soap_correo.get().strip() or None
        try:
            total, conceptos = soap_cliente.conceptos_pendientes(correo)
        except soap_cliente.ErrorServicio as error:
            return self._soap_fallo(error)

        self._conceptos = conceptos
        self._concepto_sel.set(-1)
        for hijo in self._lista.winfo_children():
            hijo.destroy()

        for indice, concepto in enumerate(conceptos):
            ctk.CTkRadioButton(
                self._lista,
                text="{}  ·  {}  ·  {}".format(concepto["termino"],
                                               concepto["libro"][:44],
                                               concepto["categoria"]),
                variable=self._concepto_sel, value=indice,
                font=ctk.CTkFont(size=12), radiobutton_width=16,
                radiobutton_height=16,
                command=self._soap_mostrar_definicion,
            ).pack(anchor="w", pady=2, padx=4)

        self._soap_estado.configure(
            text="{} conceptos mostrados de {} pendientes.".format(
                len(conceptos), total), text_color="#7F8C8D")

    def _soap_mostrar_definicion(self) -> None:
        indice = self._concepto_sel.get()
        self._definicion.configure(state="normal")
        self._definicion.delete("1.0", "end")
        if 0 <= indice < len(self._conceptos):
            concepto = self._conceptos[indice]
            self._definicion.insert("1.0", "{}: {}".format(concepto["termino"],
                                                           concepto["definicion"]))
        self._definicion.configure(state="disabled")

    def _soap_sugerir(self) -> None:
        """Aquí se unen los dos ejercicios: el clasificador NLP del EG1 lee la
        definición que trajo el servicio SOAP y propone un modelo. La decisión
        sigue siendo del usuario; esto sólo preselecciona."""
        indice = self._concepto_sel.get()
        if not (0 <= indice < len(self._conceptos)):
            return messagebox.showwarning("Sin selección",
                                          "Elige un concepto de la lista.")
        concepto = self._conceptos[indice]
        texto = "{}. {}".format(concepto["termino"], concepto["definicion"])
        try:
            resultado = self._classifier.classify(texto)
        except ClassificationException as exc:
            return messagebox.showwarning("Aviso", str(exc))

        etiqueta = resultado.model.label
        if etiqueta in soap_cliente.MODELOS:
            self._modelo_sel.set(etiqueta)
            self._soap_estado.configure(
                text="El clasificador local del EG1 sugiere {} para «{}». "
                     "La decisión sigue siendo tuya.".format(etiqueta,
                                                             concepto["termino"]),
                text_color="#16A085")
        else:
            self._soap_estado.configure(
                text="El clasificador local no encontró un modelo predominante "
                     "en esa definición: elígelo tú.", text_color="#7F8C8D")

        # Reutiliza el panel NLP de la otra pestaña para ver por qué lo sugiere.
        self._show_nlp_details(resultado)

    def _soap_registrar(self) -> None:
        datos = self._soap_datos()
        if not datos:
            return
        indice = self._concepto_sel.get()
        if not (0 <= indice < len(self._conceptos)):
            return messagebox.showwarning("Sin selección",
                                          "Elige un concepto de la lista.")
        concepto = self._conceptos[indice]
        try:
            resultado = soap_cliente.registrar_clasificacion(
                datos, concepto, self._modelo_sel.get())
        except soap_cliente.ErrorServicio as error:
            return self._soap_fallo(error)

        messagebox.showinfo(
            "Registrado",
            "«{}» quedó clasificado como {}.".format(resultado["termino"],
                                                     resultado["modelo"]))
        self._soap_estado.configure(
            text="Registro #{}. Peticiones atendidas a este cliente: {}".format(
                resultado["id"], resultado["peticiones"]), text_color="#16A085")

        # La lista NO se recarga: recargar borraría de la vista el concepto
        # recién clasificado, justo cuando el usuario quiere ver el resultado de
        # lo que hizo, y dejaría fuera de alcance el conflicto por duplicado.
        for hijo in self._lista.winfo_children():
            if getattr(hijo, "_value", None) == indice or \
               (hasattr(hijo, "cget") and hijo.cget("value") == indice):
                texto = hijo.cget("text")
                if not texto.startswith("✓"):
                    hijo.configure(text="✓ " + texto, text_color="#7F8C8D")
                break

    def _soap_progreso(self) -> None:
        datos = self._soap_datos(exigir_todo=False)
        if not datos:
            return
        try:
            progreso = soap_cliente.progreso(datos["correo"])
        except soap_cliente.ErrorServicio as error:
            return self._soap_fallo(error)

        desglose = "\n".join("  {}: {}".format(m, t) for m, t in progreso["modelos"])
        messagebox.showinfo(
            "Progreso",
            "{}\n\nClasificados: {}\nPendientes: {}\n\nPor modelo:\n{}".format(
                progreso["nombre"], progreso["clasificados"],
                progreso["pendientes"], desglose))

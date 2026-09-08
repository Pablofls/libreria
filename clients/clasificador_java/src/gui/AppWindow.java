package gui;

import classifier.ClassificationException;
import classifier.ClassificationResult;
import classifier.CloudClassifier;
import classifier.CloudModel;

import soap.Concepto;
import soap.SoapClient;
import soap.SoapFault;

import javax.swing.*;
import javax.swing.border.*;
import java.awt.*;
import java.util.EnumMap;
import java.util.List;
import java.util.Map;

/**
 * Ventana principal de la aplicación.
 *
 * Responsabilidad única: presentar la interfaz gráfica, recoger las entradas
 * del usuario y mostrar el resultado. Toda la lógica de clasificación y NLP
 * reside en {@link CloudClassifier}; esta clase solo la invoca y muestra la respuesta.
 *
 * Secciones de la ventana:
 *   - Cabecera: título y subtítulo.
 *   - Pestaña "Clasificador local" (EG1): formulario, resultado y panel NLP.
 *   - Pestaña "Cliente SOAP" (EG3): catálogo real consumido por SOAP.
 *
 * MODO CLIENTE SOAP — Parte 8 del Ejercicio Guiado 3
 *   La segunda pestaña añade el modo cliente SOAP sin tocar el clasificador
 *   local: ambos conviven. Captura nombre, apellidos y correo, trae los
 *   conceptos pendientes del catálogo real, deja que el clasificador NLP del
 *   EG1 SUGIERA el modelo a partir de la definición, y registra la decisión
 *   en el servicio.
 *
 *   La GUI no conoce PostgreSQL. No hay cadena de conexión, ni SQL, ni nombres
 *   de tabla: su única puerta al sistema es el endpoint SOAP, y todo el XML
 *   vive en {@link SoapClient}.
 */
public class AppWindow extends JFrame {

    // ── Dependencia de negocio ───────────────────────────────────────────────
    private final CloudClassifier classifier = new CloudClassifier();

    // ── Componentes de formulario ────────────────────────────────────────────
    private JTextField nameField;
    private JTextField lastNameField;
    private JTextArea  descriptionArea;
    private JLabel     charCountLabel;

    // ── Componentes de resultado principal ──────────────────────────────────
    private JPanel resultPanel;
    private JLabel modelLabel;
    private JLabel resultDescLabel;

    // ── Componentes del panel NLP ────────────────────────────────────────────
    private JPanel     nlpPanel;
    private JLabel     tokensLabel;
    private JProgressBar barIaaS, barPaaS, barSaaS, barFaaS;
    private JLabel      lblScoreIaaS, lblScorePaaS, lblScoreSaaS, lblScoreFaaS;

    // ── Paleta de colores ────────────────────────────────────────────────────
    private static final Color COLOR_IAAS    = new Color(52,  152, 219);
    private static final Color COLOR_PAAS    = new Color(46,  204, 113);
    private static final Color COLOR_SAAS    = new Color(155,  89, 182);
    private static final Color COLOR_FAAS    = new Color(230, 126,  34);
    private static final Color COLOR_UNKNOWN = new Color(149, 165, 166);
    private static final Color BG            = new Color(245, 246, 250);
    private static final Color CARD          = Color.WHITE;
    private static final Color NLP_BG        = new Color(30,  39,  46);

    private static final int MAX_CHARS = 2000;

    // ── Modo cliente SOAP (Parte 8 del EG3) ──────────────────────────────────
    private final SoapClient soap = SoapClient.porDefecto();
    private JTextField soapNombre, soapApellidos, soapCorreo;
    private JList<Concepto> listaConceptos;
    private DefaultListModel<Concepto> modeloLista;
    private JTextArea definicionArea;
    private JComboBox<String> modeloCombo;
    private JLabel soapEstado;
    private final java.util.Set<String> yaRegistrados = new java.util.HashSet<>();

    public AppWindow() {
        setTitle("Cloud Models Classifier");
        setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
        setSize(760, 830);
        setLocationRelativeTo(null);
        setResizable(false);
        getContentPane().setBackground(BG);

        buildUI();
    }

    // ── Construcción de la interfaz ──────────────────────────────────────────

    private void buildUI() {
        setLayout(new BorderLayout(0, 0));
        add(buildHeader(), BorderLayout.NORTH);

        // Dos modos que conviven: el clasificador local del EG1 y el cliente
        // SOAP del EG3. Se separan en pestañas para que ninguno estorbe al otro.
        JPanel local = new JPanel(new BorderLayout(0, 0));
        local.setBackground(BG);
        local.add(buildFormCard(),   BorderLayout.CENTER);
        local.add(buildBottomArea(), BorderLayout.SOUTH);

        JTabbedPane tabs = new JTabbedPane();
        tabs.addTab("Clasificador local", local);
        tabs.addTab("Cliente SOAP", buildSoapPanel());
        add(tabs, BorderLayout.CENTER);
    }

    /** Cabecera oscura con título y subtítulo. */
    private JPanel buildHeader() {
        JPanel header = new JPanel(new BorderLayout());
        header.setBackground(new Color(44, 62, 80));
        header.setBorder(new EmptyBorder(14, 20, 14, 20));

        JPanel texts = new JPanel(new GridLayout(2, 1, 0, 2));
        texts.setOpaque(false);
        texts.add(styledLabel("Cloud Models Classifier", Font.BOLD, 20, Color.WHITE));
        texts.add(styledLabel("IaaS · PaaS · SaaS · FaaS  —  NLP Pipeline",
                              Font.PLAIN, 12, new Color(189, 195, 199)));
        header.add(texts, BorderLayout.CENTER);
        return header;
    }

    /** Tarjeta blanca con los campos del formulario. */
    private JPanel buildFormCard() {
        JPanel card = new JPanel(new BorderLayout(0, 10));
        card.setBackground(CARD);
        card.setBorder(new CompoundBorder(
            new EmptyBorder(12, 16, 0, 16),
            new CompoundBorder(
                new LineBorder(new Color(220, 220, 220), 1, true),
                new EmptyBorder(18, 18, 18, 18)
            )
        ));

        // Fila nombre / apellido
        JPanel nameRow = new JPanel(new GridLayout(1, 2, 12, 0));
        nameRow.setOpaque(false);
        nameField     = new JTextField();
        lastNameField = new JTextField();
        nameRow.add(buildLabeledField("Nombre",   nameField));
        nameRow.add(buildLabeledField("Apellido", lastNameField));
        card.add(nameRow, BorderLayout.NORTH);

        // Área de descripción
        card.add(buildDescriptionPanel(), BorderLayout.CENTER);

        // Botón
        card.add(buildButtonPanel(), BorderLayout.SOUTH);
        return card;
    }

    /** Panel con etiqueta, área de texto y contador de caracteres. */
    private JPanel buildDescriptionPanel() {
        JPanel panel = new JPanel(new BorderLayout(0, 5));
        panel.setOpaque(false);
        panel.add(styledLabel("Descripción del servicio Cloud:", Font.BOLD, 13, Color.DARK_GRAY),
                  BorderLayout.NORTH);

        descriptionArea = new JTextArea();
        descriptionArea.setFont(new Font("SansSerif", Font.PLAIN, 13));
        descriptionArea.setLineWrap(true);
        descriptionArea.setWrapStyleWord(true);
        descriptionArea.setBorder(new CompoundBorder(
            new LineBorder(new Color(200, 200, 200), 1, true),
            new EmptyBorder(7, 7, 7, 7)
        ));
        descriptionArea.addKeyListener(new java.awt.event.KeyAdapter() {
            @Override public void keyReleased(java.awt.event.KeyEvent e) { updateCharCount(); }
        });

        JScrollPane scroll = new JScrollPane(descriptionArea);
        scroll.setBorder(null);
        panel.add(scroll, BorderLayout.CENTER);

        charCountLabel = styledLabel("0 / " + MAX_CHARS, Font.PLAIN, 11, Color.GRAY);
        charCountLabel.setHorizontalAlignment(SwingConstants.RIGHT);
        panel.add(charCountLabel, BorderLayout.SOUTH);
        return panel;
    }

    private JPanel buildButtonPanel() {
        JPanel panel = new JPanel(new FlowLayout(FlowLayout.LEFT, 0, 0));
        panel.setOpaque(false);

        JButton btn = new JButton("  Clasificar  ");
        btn.setFont(new Font("SansSerif", Font.BOLD, 13));
        btn.setBackground(new Color(44, 62, 80));
        btn.setForeground(Color.WHITE);
        btn.setFocusPainted(false);
        btn.setBorderPainted(false);
        btn.setOpaque(true);
        btn.setPreferredSize(new Dimension(135, 36));
        btn.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
        btn.addActionListener(e -> onClassify());
        panel.add(btn);
        return panel;
    }

    /** Panel inferior: resultado + detalles NLP. */
    private JPanel buildBottomArea() {
        JPanel bottom = new JPanel(new BorderLayout(0, 0));
        bottom.setBackground(BG);
        bottom.setBorder(new EmptyBorder(0, 16, 16, 16));
        bottom.add(buildResultPanel(), BorderLayout.NORTH);
        bottom.add(buildNlpPanel(),    BorderLayout.CENTER);
        return bottom;
    }

    /** Banda de resultado con modelo detectado y descripción. */
    private JPanel buildResultPanel() {
        resultPanel = new JPanel(new BorderLayout(14, 0));
        resultPanel.setBackground(COLOR_UNKNOWN);
        resultPanel.setBorder(new EmptyBorder(14, 16, 14, 16));

        modelLabel = styledLabel("—", Font.BOLD, 22, Color.WHITE);
        modelLabel.setPreferredSize(new Dimension(80, 50));
        modelLabel.setHorizontalAlignment(SwingConstants.CENTER);

        resultDescLabel = new JLabel(
            "<html><b>Resultado:</b><br>" +
            "Ingresa una descripción y presiona <i>Clasificar</i>.</html>"
        );
        resultDescLabel.setFont(new Font("SansSerif", Font.PLAIN, 13));
        resultDescLabel.setForeground(Color.WHITE);

        resultPanel.add(modelLabel,      BorderLayout.WEST);
        resultPanel.add(resultDescLabel, BorderLayout.CENTER);
        return resultPanel;
    }

    /**
     * Panel oscuro que muestra los tokens NLP resultantes y las barras de puntaje.
     * Permanece oculto hasta la primera clasificación exitosa.
     */
    private JPanel buildNlpPanel() {
        nlpPanel = new JPanel(new BorderLayout(0, 10));
        nlpPanel.setBackground(NLP_BG);
        nlpPanel.setBorder(new EmptyBorder(12, 16, 14, 16));
        nlpPanel.setVisible(false);

        // Fila de título + tokens
        JPanel topRow = new JPanel(new BorderLayout(0, 4));
        topRow.setOpaque(false);
        topRow.add(styledLabel("Pipeline NLP — Tokens extraídos:", Font.BOLD, 11,
                               new Color(189, 195, 199)), BorderLayout.NORTH);

        tokensLabel = new JLabel();
        tokensLabel.setFont(new Font("Monospaced", Font.PLAIN, 11));
        tokensLabel.setForeground(new Color(130, 224, 170));
        topRow.add(tokensLabel, BorderLayout.CENTER);
        nlpPanel.add(topRow, BorderLayout.NORTH);

        // Barras de puntaje
        nlpPanel.add(buildScoreBarsPanel(), BorderLayout.CENTER);
        return nlpPanel;
    }

    /** Cuatro barras de progreso, una por modelo, con su etiqueta y puntaje. */
    private JPanel buildScoreBarsPanel() {
        JPanel panel = new JPanel(new GridLayout(2, 2, 14, 6));
        panel.setOpaque(false);

        barIaaS = createBar(COLOR_IAAS);
        barPaaS = createBar(COLOR_PAAS);
        barSaaS = createBar(COLOR_SAAS);
        barFaaS = createBar(COLOR_FAAS);

        lblScoreIaaS = scoreLabel();
        lblScorePaaS = scoreLabel();
        lblScoreSaaS = scoreLabel();
        lblScoreFaaS = scoreLabel();

        panel.add(barRow("IaaS", barIaaS, lblScoreIaaS, COLOR_IAAS));
        panel.add(barRow("PaaS", barPaaS, lblScorePaaS, COLOR_PAAS));
        panel.add(barRow("SaaS", barSaaS, lblScoreSaaS, COLOR_SAAS));
        panel.add(barRow("FaaS", barFaaS, lblScoreFaaS, COLOR_FAAS));
        return panel;
    }

    /** Fila: etiqueta coloreada + barra + puntaje numérico. */
    private JPanel barRow(String name, JProgressBar bar, JLabel scoreLabel, Color color) {
        JPanel row = new JPanel(new BorderLayout(6, 0));
        row.setOpaque(false);

        JLabel nameLbl = styledLabel(name, Font.BOLD, 11, color);
        nameLbl.setPreferredSize(new Dimension(34, 16));
        row.add(nameLbl,    BorderLayout.WEST);
        row.add(bar,        BorderLayout.CENTER);
        row.add(scoreLabel, BorderLayout.EAST);
        return row;
    }

    private JProgressBar createBar(Color color) {
        JProgressBar bar = new JProgressBar(0, 10);
        bar.setValue(0);
        bar.setStringPainted(false);
        bar.setForeground(color);
        bar.setBackground(new Color(55, 66, 74));
        bar.setBorderPainted(false);
        bar.setPreferredSize(new Dimension(0, 12));
        return bar;
    }

    private JLabel scoreLabel() {
        JLabel lbl = styledLabel("0", Font.BOLD, 11, Color.WHITE);
        lbl.setPreferredSize(new Dimension(22, 16));
        lbl.setHorizontalAlignment(SwingConstants.RIGHT);
        return lbl;
    }

    // ── Eventos ──────────────────────────────────────────────────────────────

    /**
     * Reúne las entradas del formulario, valida los campos de usuario (GUI)
     * y delega la clasificación a {@link CloudClassifier}.
     *
     * La separación de responsabilidades es explícita:
     * - La GUI valida nombre/apellido (son datos de presentación).
     * - El clasificador valida el texto (es su dominio).
     */
    private void onClassify() {
        String name     = nameField.getText().trim();
        String lastName = lastNameField.getText().trim();
        String text     = descriptionArea.getText().trim();

        // Validación de campos de presentación
        try {
            validateUserFields(name, lastName);
        } catch (IllegalArgumentException ex) {
            showWarning(ex.getMessage());
            return;
        }

        // Clasificación con NLP — manejo explícito de cada tipo de excepción
        try {
            ClassificationResult result = classifier.classify(text);
            showResult(name, lastName, result);
            showNlpDetails(result);

        } catch (ClassificationException ex) {
            // Error de validación del texto (muy corto, sin letras, etc.)
            showWarning(ex.getMessage());

        } catch (Exception ex) {
            // Error inesperado: no debe crashear la aplicación
            showError("Error inesperado al clasificar: " + ex.getMessage());
        }
    }

    // ── Validación de campos de usuario ──────────────────────────────────────

    /**
     * Valida que nombre y apellido no estén vacíos y contengan solo letras.
     * Esta validación pertenece a la GUI porque es un requisito de presentación,
     * no de la lógica del clasificador.
     *
     * @throws IllegalArgumentException con un mensaje descriptivo para el usuario
     */
    private void validateUserFields(String name, String lastName) {
        if (name.isEmpty() || lastName.isEmpty()) {
            throw new IllegalArgumentException("Por favor, ingresa tu nombre y apellido.");
        }
        if (!name.matches("[\\p{L} ]+")) {
            throw new IllegalArgumentException("El nombre solo puede contener letras.");
        }
        if (!lastName.matches("[\\p{L} ]+")) {
            throw new IllegalArgumentException("El apellido solo puede contener letras.");
        }
    }

    // ── Actualización de la UI ────────────────────────────────────────────────

    private void updateCharCount() {
        int count = descriptionArea.getText().length();
        charCountLabel.setText(count + " / " + MAX_CHARS);
        charCountLabel.setForeground(count > MAX_CHARS * 0.9 ? Color.RED : Color.GRAY);
    }

    /** Actualiza la banda de resultado principal con el modelo ganador. */
    private void showResult(String name, String lastName, ClassificationResult result) {
        CloudModel model = result.getModel();

        resultPanel.setBackground(colorFor(model));
        modelLabel.setText(model.getLabel());
        modelLabel.setFont(new Font("SansSerif", Font.BOLD,
                                    model == CloudModel.UNKNOWN ? 12 : 20));
        resultDescLabel.setText(String.format(
            "<html><b>%s %s — Modelo detectado: %s</b><br>%s</html>",
            name, lastName, model.getLabel(), model.getDescription()
        ));
        resultPanel.revalidate();
        resultPanel.repaint();
    }

    /** Muestra los tokens NLP y actualiza las barras de puntaje. */
    private void showNlpDetails(ClassificationResult result) {
        // Tokens stemmed usados para el matching
        List<String> stemmed = result.getProcessedText().stemmed;
        String tokensText = stemmed.isEmpty()
            ? "(sin tokens significativos)"
            : String.join("  ·  ", stemmed);
        tokensLabel.setText("<html>" + tokensText + "</html>");

        // Barras de puntaje (escaladas al máximo encontrado)
        EnumMap<CloudModel, Integer> scores = result.getScores();
        int max = Math.max(result.getMaxScore(), 1); // evitar división por cero

        updateBar(barIaaS, lblScoreIaaS, scores.get(CloudModel.IAAS), max);
        updateBar(barPaaS, lblScorePaaS, scores.get(CloudModel.PAAS), max);
        updateBar(barSaaS, lblScoreSaaS, scores.get(CloudModel.SAAS), max);
        updateBar(barFaaS, lblScoreFaaS, scores.get(CloudModel.FAAS), max);

        nlpPanel.setVisible(true);
        nlpPanel.revalidate();
        nlpPanel.repaint();
    }

    private void updateBar(JProgressBar bar, JLabel label, int score, int max) {
        bar.setMaximum(max);
        bar.setValue(score);
        label.setText(String.valueOf(score));
    }

    // ── Utilidades de UI ─────────────────────────────────────────────────────

    private Color colorFor(CloudModel model) {
        switch (model) {
            case IAAS: return COLOR_IAAS;
            case PAAS: return COLOR_PAAS;
            case SAAS: return COLOR_SAAS;
            case FAAS: return COLOR_FAAS;
            default:   return COLOR_UNKNOWN;
        }
    }

    private void showWarning(String msg) {
        JOptionPane.showMessageDialog(this, msg, "Aviso", JOptionPane.WARNING_MESSAGE);
    }

    private void showError(String msg) {
        JOptionPane.showMessageDialog(this, msg, "Error", JOptionPane.ERROR_MESSAGE);
    }

    private JPanel buildLabeledField(String labelText, JTextField field) {
        JPanel panel = new JPanel(new BorderLayout(0, 4));
        panel.setOpaque(false);
        panel.add(styledLabel(labelText + ":", Font.BOLD, 13, Color.DARK_GRAY),
                  BorderLayout.NORTH);
        field.setFont(new Font("SansSerif", Font.PLAIN, 13));
        field.setBorder(new CompoundBorder(
            new LineBorder(new Color(200, 200, 200), 1, true),
            new EmptyBorder(5, 7, 5, 7)
        ));
        panel.add(field, BorderLayout.CENTER);
        return panel;
    }

    private JLabel styledLabel(String text, int style, int size, Color color) {
        JLabel lbl = new JLabel(text);
        lbl.setFont(new Font("SansSerif", style, size));
        lbl.setForeground(color);
        return lbl;
    }

    // ══════════════════════════════════════════════════════════════════════════
    //  MODO CLIENTE SOAP  —  Parte 8 del Ejercicio Guiado 3
    // ══════════════════════════════════════════════════════════════════════════

    /** Pestaña que consume el módulo SOAP: catálogo real, no texto libre. */
    private JPanel buildSoapPanel() {
        JPanel panel = new JPanel(new BorderLayout(0, 8));
        panel.setBackground(BG);
        panel.setBorder(new EmptyBorder(10, 12, 10, 12));

        // ── Identidad del clasificador (lo exige el enunciado) ───────────────
        JPanel identidad = new JPanel(new GridLayout(1, 3, 10, 0));
        identidad.setBackground(CARD);
        identidad.setBorder(new CompoundBorder(
                new LineBorder(new Color(220, 224, 230)),
                new EmptyBorder(12, 12, 12, 12)));
        soapNombre    = new JTextField();
        soapApellidos = new JTextField();
        soapCorreo    = new JTextField();
        identidad.add(buildLabeledField("Nombre",    soapNombre));
        identidad.add(buildLabeledField("Apellidos", soapApellidos));
        identidad.add(buildLabeledField("Correo",    soapCorreo));

        JPanel acciones = new JPanel(new FlowLayout(FlowLayout.LEFT, 8, 0));
        acciones.setBackground(BG);
        JButton btnCargar = new JButton("Cargar conceptos pendientes");
        btnCargar.addActionListener(e -> onSoapCargar());
        JButton btnProgreso = new JButton("Ver mi progreso");
        btnProgreso.addActionListener(e -> onSoapProgreso());
        acciones.add(btnCargar);
        acciones.add(btnProgreso);

        JPanel norte = new JPanel(new BorderLayout(0, 8));
        norte.setBackground(BG);
        norte.add(identidad, BorderLayout.CENTER);
        norte.add(acciones,  BorderLayout.SOUTH);
        panel.add(norte, BorderLayout.NORTH);

        // ── Lista de conceptos + definición ─────────────────────────────────
        modeloLista = new DefaultListModel<>();
        listaConceptos = new JList<>(modeloLista);
        listaConceptos.setSelectionMode(ListSelectionModel.SINGLE_SELECTION);
        listaConceptos.addListSelectionListener(e -> mostrarDefinicion());

        definicionArea = new JTextArea(3, 20);
        definicionArea.setEditable(false);
        definicionArea.setLineWrap(true);
        definicionArea.setWrapStyleWord(true);
        definicionArea.setBackground(CARD);
        definicionArea.setBorder(new EmptyBorder(8, 8, 8, 8));

        JPanel centro = new JPanel(new BorderLayout(0, 8));
        centro.setBackground(BG);
        centro.add(new JScrollPane(listaConceptos), BorderLayout.CENTER);
        centro.add(new JScrollPane(definicionArea), BorderLayout.SOUTH);
        panel.add(centro, BorderLayout.CENTER);

        // ── Modelo, sugerencia y registro ───────────────────────────────────
        JPanel sur = new JPanel(new BorderLayout(0, 6));
        sur.setBackground(BG);

        JPanel fila = new JPanel(new FlowLayout(FlowLayout.LEFT, 8, 0));
        fila.setBackground(BG);
        fila.add(styledLabel("Modelo Cloud:", Font.BOLD, 13, Color.DARK_GRAY));
        modeloCombo = new JComboBox<>(SoapClient.MODELOS.toArray(new String[0]));
        fila.add(modeloCombo);
        JButton btnSugerir = new JButton("Sugerir con el clasificador local");
        btnSugerir.addActionListener(e -> onSoapSugerir());
        fila.add(btnSugerir);
        sur.add(fila, BorderLayout.NORTH);

        JButton btnRegistrar = new JButton("Registrar clasificación");
        btnRegistrar.addActionListener(e -> onSoapRegistrar());
        sur.add(btnRegistrar, BorderLayout.CENTER);

        soapEstado = styledLabel("Endpoint: " + soap.getEndpoint(),
                                 Font.PLAIN, 11, Color.GRAY);
        sur.add(soapEstado, BorderLayout.SOUTH);
        panel.add(sur, BorderLayout.SOUTH);

        return panel;
    }

    // ── Manejo de Faults ──────────────────────────────────────────────────────

    /**
     * Traduce el Fault. Nunca muestra el faultstring crudo del servidor.
     *
     * Un Fault esperado —pedir el progreso antes de la primera clasificación—
     * no es una falla: para quien estrena la aplicación es el estado normal y
     * presentarlo como error asusta sin motivo.
     */
    private void mostrarFault(SoapFault fault) {
        if (fault.esEsperado()) {
            JOptionPane.showMessageDialog(this, fault.getMessage(),
                    "Sin registros", JOptionPane.INFORMATION_MESSAGE);
            soapEstado.setText(fault.getMessage());
            soapEstado.setForeground(Color.GRAY);
        } else {
            JOptionPane.showMessageDialog(this, fault.getMessage(),
                    "No se pudo completar", JOptionPane.ERROR_MESSAGE);
            soapEstado.setText(fault.getMessage() + "  (" + fault.getCodigo() + ")");
            soapEstado.setForeground(new Color(192, 57, 43));
        }
    }

    private boolean datosCompletos(boolean exigirTodo) {
        if (soapCorreo.getText().isBlank()
                || (exigirTodo && (soapNombre.getText().isBlank()
                                || soapApellidos.getText().isBlank()))) {
            JOptionPane.showMessageDialog(this,
                    exigirTodo ? "Captura nombre, apellidos y correo."
                               : "Captura tu correo.",
                    "Datos incompletos", JOptionPane.WARNING_MESSAGE);
            return false;
        }
        return true;
    }

    // ── Acciones ──────────────────────────────────────────────────────────────

    private void onSoapCargar() {
        String correo = soapCorreo.getText().isBlank() ? null
                                                       : soapCorreo.getText().trim();
        try {
            List<Concepto> conceptos = soap.conceptosPendientes(correo, 50);
            modeloLista.clear();
            for (Concepto c : conceptos) modeloLista.addElement(c);
            definicionArea.setText("");
            soapEstado.setText(conceptos.size() + " conceptos pendientes cargados.");
            soapEstado.setForeground(Color.GRAY);
        } catch (SoapFault f) {
            mostrarFault(f);
        }
    }

    private void mostrarDefinicion() {
        Concepto c = listaConceptos.getSelectedValue();
        definicionArea.setText(c == null ? ""
                : c.termino() + ": " + c.definicion());
        definicionArea.setCaretPosition(0);
    }

    /**
     * Aquí se unen los dos ejercicios: el clasificador NLP del EG1 lee la
     * definición que trajo el servicio SOAP y propone un modelo. La decisión
     * sigue siendo del usuario; esto sólo preselecciona.
     */
    private void onSoapSugerir() {
        Concepto c = listaConceptos.getSelectedValue();
        if (c == null) {
            JOptionPane.showMessageDialog(this, "Elige un concepto de la lista.",
                    "Sin selección", JOptionPane.WARNING_MESSAGE);
            return;
        }
        try {
            ClassificationResult r = classifier.classify(c.paraClasificar());
            String etiqueta = r.getModel().getLabel();
            if (SoapClient.MODELOS.contains(etiqueta)) {
                modeloCombo.setSelectedItem(etiqueta);
                soapEstado.setText("El clasificador local del EG1 sugiere "
                        + etiqueta + " para «" + c.termino()
                        + "». La decisión sigue siendo tuya.");
                soapEstado.setForeground(new Color(22, 160, 133));
            } else {
                soapEstado.setText("El clasificador local no encontró un modelo "
                        + "predominante en esa definición: elígelo tú.");
                soapEstado.setForeground(Color.GRAY);
            }
            showNlpDetails(r);   // reutiliza el panel NLP de la otra pestaña
        } catch (ClassificationException ex) {
            JOptionPane.showMessageDialog(this, ex.getMessage(), "Aviso",
                    JOptionPane.WARNING_MESSAGE);
        }
    }

    private void onSoapRegistrar() {
        if (!datosCompletos(true)) return;
        Concepto c = listaConceptos.getSelectedValue();
        if (c == null) {
            JOptionPane.showMessageDialog(this, "Elige un concepto de la lista.",
                    "Sin selección", JOptionPane.WARNING_MESSAGE);
            return;
        }
        try {
            Map<String, String> r = soap.registrar(
                    soapNombre.getText().trim(), soapApellidos.getText().trim(),
                    soapCorreo.getText().trim(), c,
                    (String) modeloCombo.getSelectedItem());

            JOptionPane.showMessageDialog(this,
                    "«" + r.get("termino") + "» quedó clasificado como "
                            + r.get("modelo") + ".",
                    "Registrado", JOptionPane.INFORMATION_MESSAGE);
            soapEstado.setText("Registro #" + r.get("id")
                    + ". Peticiones atendidas a este cliente: " + r.get("peticiones"));
            soapEstado.setForeground(new Color(22, 160, 133));

            // La lista NO se recarga: recargar borraría de la vista el concepto
            // recién clasificado, justo cuando el usuario quiere ver el
            // resultado de lo que hizo, y dejaría fuera de alcance el conflicto
            // por duplicado.
            yaRegistrados.add(c.id());
            listaConceptos.repaint();
        } catch (SoapFault f) {
            mostrarFault(f);
        }
    }

    private void onSoapProgreso() {
        if (!datosCompletos(false)) return;
        try {
            JOptionPane.showMessageDialog(this,
                    soap.progreso(soapCorreo.getText().trim()),
                    "Progreso", JOptionPane.INFORMATION_MESSAGE);
        } catch (SoapFault f) {
            mostrarFault(f);
        }
    }
}

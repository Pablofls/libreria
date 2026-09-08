package soap;

import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;

import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.transform.Transformer;
import javax.xml.transform.TransformerFactory;
import javax.xml.transform.dom.DOMSource;
import javax.xml.transform.stream.StreamResult;
import java.io.ByteArrayInputStream;
import java.io.StringWriter;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Capa cliente SOAP del Clasificador Cloud — modo cliente SOAP de la Parte 8.
 *
 * REGLA DEL EJERCICIO QUE ESTA CLASE RESPETA
 *     Aqui no hay una cadena de conexion, ni SQL, ni un nombre de tabla. La
 *     unica puerta al sistema es el endpoint SOAP. Si el modulo cambiara de
 *     motor de base de datos, esta clase no se toca.
 *
 * El sobre se construye con DOM y se serializa con un Transformer, que escapa
 * los valores. No se concatena XML en ninguna parte, igual que la version en
 * Python usa xml.etree. Esa disciplina es la misma que las consultas
 * parametrizadas, aplicada al otro formato.
 *
 * Todo es de la biblioteca estandar del JDK: ni una dependencia externa.
 */
public final class SoapClient {

    public static final String NS =
            "http://udem.edu/iac/libreria/clasificador";
    private static final String NS_SOAP =
            "http://schemas.xmlsoap.org/soap/envelope/";

    public static final List<String> MODELOS =
            List.of("IaaS", "PaaS", "SaaS", "FaaS");

    private static final String TIPO_CLIENTE = "escritorio-eg1-java";

    private final String endpoint;
    private final String idCliente;
    private final HttpClient http;

    public SoapClient(String endpoint, String idCliente) {
        this.endpoint  = endpoint;
        this.idCliente = idCliente;
        this.http = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .build();
    }

    public static SoapClient porDefecto() {
        String url = System.getenv().getOrDefault(
                "SOAP_ENDPOINT", "http://127.0.0.1:5001/soap");
        String id  = System.getenv().getOrDefault(
                "SOAP_ID_CLIENTE", "estacion-01");
        return new SoapClient(url, id);
    }

    public String getEndpoint() { return endpoint; }

    // ── Construccion del sobre ────────────────────────────────────────────────

    private Document nuevoSobre(String operacion) throws Exception {
        DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
        f.setNamespaceAware(true);
        Document doc = f.newDocumentBuilder().newDocument();

        Element sobre = doc.createElementNS(NS_SOAP, "soap:Envelope");
        doc.appendChild(sobre);
        Element cuerpo = doc.createElementNS(NS_SOAP, "soap:Body");
        sobre.appendChild(cuerpo);
        Element op = doc.createElementNS(NS, "tns:" + operacion);
        cuerpo.appendChild(op);
        return doc;
    }

    private static Element cuerpoDe(Document doc) {
        Element sobre = doc.getDocumentElement();
        Element cuerpo = (Element) sobre.getElementsByTagNameNS(NS_SOAP, "Body").item(0);
        return (Element) cuerpo.getFirstChild();
    }

    private static Element campo(Element padre, String nombre, String valor) {
        Element e = padre.getOwnerDocument().createElementNS(NS, "tns:" + nombre);
        e.setTextContent(valor);   // el Transformer escapa &, <, > y comillas
        padre.appendChild(e);
        return e;
    }

    // ── Envio y lectura de la respuesta ───────────────────────────────────────

    private Element enviar(Document sobre, String operacion) throws SoapFault {
        byte[] cuerpo;
        try {
            Transformer t = TransformerFactory.newInstance().newTransformer();
            StringWriter sw = new StringWriter();
            t.transform(new DOMSource(sobre), new StreamResult(sw));
            cuerpo = sw.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);
        } catch (Exception e) {
            throw new SoapFault("XML_INVALIDO", null);
        }

        HttpResponse<byte[]> respuesta;
        try {
            HttpRequest peticion = HttpRequest.newBuilder(URI.create(endpoint))
                    .header("Content-Type", "text/xml; charset=utf-8")
                    .header("SOAPAction", NS + "/" + operacion)
                    .timeout(Duration.ofSeconds(20))
                    .POST(HttpRequest.BodyPublishers.ofByteArray(cuerpo))
                    .build();
            respuesta = http.send(peticion, HttpResponse.BodyHandlers.ofByteArray());
        } catch (Exception e) {
            // No se propaga el mensaje de la excepcion: puede llevar rutas o
            // detalles del entorno que no le interesan al usuario.
            throw new SoapFault("ERROR_SERVIDOR", null);
        }

        Document doc;
        try {
            DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
            f.setNamespaceAware(true);
            DocumentBuilder db = f.newDocumentBuilder();
            doc = db.parse(new ByteArrayInputStream(respuesta.body()));
        } catch (Exception e) {
            throw new SoapFault("ERROR_SERVIDOR", null);
        }

        Element sobreResp = doc.getDocumentElement();
        Element cuerpoResp = (Element) sobreResp
                .getElementsByTagNameNS(NS_SOAP, "Body").item(0);

        NodeList faults = cuerpoResp.getElementsByTagNameNS(NS_SOAP, "Fault");
        if (faults.getLength() > 0) {
            Element fault = (Element) faults.item(0);
            throw new SoapFault(textoDe(fault, "codigo", "ERROR_SERVIDOR"),
                                textoDe(fault, "campo", null));
        }

        for (int i = 0; i < cuerpoResp.getChildNodes().getLength(); i++) {
            Node hijo = cuerpoResp.getChildNodes().item(i);
            if (hijo.getNodeType() == Node.ELEMENT_NODE) return (Element) hijo;
        }
        throw new SoapFault("ERROR_SERVIDOR", null);
    }

    private static String textoDe(Element padre, String nombre, String defecto) {
        NodeList lista = padre.getElementsByTagNameNS(NS, nombre);
        if (lista.getLength() == 0) return defecto;
        String v = lista.item(0).getTextContent();
        return (v == null || v.isBlank()) ? defecto : v.trim();
    }

    private static String hijoTexto(Element padre, String nombre) {
        NodeList lista = padre.getElementsByTagNameNS(NS, nombre);
        return lista.getLength() == 0 ? "" : lista.item(0).getTextContent();
    }

    // ── Las tres operaciones del contrato ─────────────────────────────────────

    /** Conceptos del catalogo real que aun no se han clasificado. */
    public List<Concepto> conceptosPendientes(String correo, int limite)
            throws SoapFault {
        Element respuesta;
        try {
            Document sobre = nuevoSobre("ObtenerConceptosPendientes");
            Element op = cuerpoDe(sobre);
            if (correo != null && !correo.isBlank()) campo(op, "correo", correo);
            campo(op, "limite", String.valueOf(limite));
            respuesta = enviar(sobre, "ObtenerConceptosPendientes");
        } catch (SoapFault f) {
            throw f;
        } catch (Exception e) {
            throw new SoapFault("ERROR_SERVIDOR", null);
        }

        List<Concepto> conceptos = new ArrayList<>();
        NodeList nodos = respuesta.getElementsByTagNameNS(NS, "concepto");
        for (int i = 0; i < nodos.getLength(); i++) {
            Element c = (Element) nodos.item(i);
            conceptos.add(new Concepto(
                    hijoTexto(c, "conceptoId"), hijoTexto(c, "termino"),
                    hijoTexto(c, "definicion"), hijoTexto(c, "isbn"),
                    hijoTexto(c, "libro"),      hijoTexto(c, "categoria")));
        }
        return conceptos;
    }

    /** Registra la decision del clasificador. Puede lanzar el Fault de conflicto. */
    public Map<String, String> registrar(String nombre, String apellidos,
                                         String correo, Concepto concepto,
                                         String modelo) throws SoapFault {
        Element respuesta;
        try {
            Document sobre = nuevoSobre("RegistrarClasificacion");
            Element op = cuerpoDe(sobre);

            Element clasificador = op.getOwnerDocument()
                    .createElementNS(NS, "tns:clasificador");
            op.appendChild(clasificador);
            campo(clasificador, "nombre", nombre);
            campo(clasificador, "apellidos", apellidos);
            campo(clasificador, "correo", correo);

            campo(op, "conceptoId", concepto.id());
            campo(op, "isbn", concepto.isbn());
            campo(op, "modelo", modelo);

            Element cliente = op.getOwnerDocument()
                    .createElementNS(NS, "tns:cliente");
            op.appendChild(cliente);
            campo(cliente, "tipo", TIPO_CLIENTE);
            campo(cliente, "identificador", idCliente);

            respuesta = enviar(sobre, "RegistrarClasificacion");
        } catch (SoapFault f) {
            throw f;
        } catch (Exception e) {
            throw new SoapFault("ERROR_SERVIDOR", null);
        }

        return Map.of(
                "id",         hijoTexto(respuesta, "clasificacionId"),
                "termino",    hijoTexto(respuesta, "termino"),
                "libro",      hijoTexto(respuesta, "libro"),
                "modelo",     hijoTexto(respuesta, "modelo"),
                "peticiones", hijoTexto(respuesta, "peticionesAtendidas"));
    }

    /** Totales del clasificador identificado por su correo. */
    public String progreso(String correo) throws SoapFault {
        Element respuesta;
        try {
            Document sobre = nuevoSobre("ObtenerProgresoUsuario");
            campo(cuerpoDe(sobre), "correo", correo);
            respuesta = enviar(sobre, "ObtenerProgresoUsuario");
        } catch (SoapFault f) {
            throw f;
        } catch (Exception e) {
            throw new SoapFault("ERROR_SERVIDOR", null);
        }

        StringBuilder sb = new StringBuilder();
        sb.append(hijoTexto(respuesta, "nombre")).append("\n\n")
          .append("Clasificados: ").append(hijoTexto(respuesta, "totalClasificados"))
          .append("\nPendientes: ").append(hijoTexto(respuesta, "totalPendientes"))
          .append("\n\nPor modelo:");
        NodeList porModelo = respuesta.getElementsByTagNameNS(NS, "porModelo");
        for (int i = 0; i < porModelo.getLength(); i++) {
            Element m = (Element) porModelo.item(i);
            sb.append("\n  ").append(hijoTexto(m, "modelo"))
              .append(": ").append(hijoTexto(m, "total"));
        }
        return sb.toString();
    }
}

package mx.udem.libreria.api;

import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;

import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.transform.Transformer;
import javax.xml.transform.TransformerFactory;
import javax.xml.transform.dom.DOMSource;
import javax.xml.transform.stream.StreamResult;
import java.io.ByteArrayInputStream;
import java.io.StringWriter;
import java.net.URI;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

/**
 * Integración demostrativa SOAP/XML con el servicio de clasificación Cloud
 * (apps/services/soap, contrato en /soap?wsdl). Basado en el cliente de
 * clients/clasificador_java/src/soap/SoapClient.java: el sobre se arma con DOM y
 * lo serializa un Transformer, que escapa los valores. No se concatena XML.
 *
 * Pasa por nginx (https://VM/soap), que sólo deja entrar con un JWT válido: por
 * eso cada petición lleva Authorization: Bearer, aunque el contrato SOAP no lo
 * pida. Sólo se usan operaciones de lectura.
 */
public final class SoapService {

    public static final String NS = "http://udem.edu/iac/libreria/clasificador";
    private static final String NS_SOAP = "http://schemas.xmlsoap.org/soap/envelope/";

    /** Un concepto pendiente de clasificar. */
    public record Concepto(String termino, String definicion, String isbn, String libro, String categoria) { }

    private final ApiClient api;

    public SoapService(ApiClient api) { this.api = api; }

    public String endpoint() { return api.config().apiBase + "/soap"; }

    /** El contrato WSDL tal como lo publica el servicio. */
    public String wsdl() throws ApiException {
        HttpResponse<byte[]> r = http("GET", endpoint() + "?wsdl", null, null);
        if (r.statusCode() != 200) throw new ApiException(r.statusCode(), null);
        return new String(r.body(), StandardCharsets.UTF_8);
    }

    public List<Concepto> conceptosPendientes(String correo, int limite) throws ApiException {
        try {
            Document sobre = nuevoSobre("ObtenerConceptosPendientes");
            Element op = cuerpoDe(sobre);
            if (correo != null && !correo.isBlank()) campo(op, "correo", correo);
            campo(op, "limite", String.valueOf(limite));
            Element resp = enviar(sobre, "ObtenerConceptosPendientes");
            List<Concepto> salida = new ArrayList<>();
            NodeList nodos = resp.getElementsByTagNameNS(NS, "concepto");
            for (int i = 0; i < nodos.getLength(); i++) {
                Element c = (Element) nodos.item(i);
                salida.add(new Concepto(texto(c, "termino"), texto(c, "definicion"), texto(c, "isbn"),
                        texto(c, "libro"), texto(c, "categoria")));
            }
            return salida;
        } catch (ApiException e) {
            throw e;
        } catch (Exception e) {
            throw new ApiException(0, "No se pudo armar o leer el mensaje SOAP.");
        }
    }

    public String progreso(String correo) throws ApiException {
        try {
            Document sobre = nuevoSobre("ObtenerProgresoUsuario");
            campo(cuerpoDe(sobre), "correo", correo);
            Element r = enviar(sobre, "ObtenerProgresoUsuario");
            StringBuilder sb = new StringBuilder()
                    .append(texto(r, "nombre")).append("\nClasificados: ").append(texto(r, "totalClasificados"))
                    .append("\nPendientes: ").append(texto(r, "totalPendientes"));
            NodeList porModelo = r.getElementsByTagNameNS(NS, "porModelo");
            for (int i = 0; i < porModelo.getLength(); i++) {
                Element m = (Element) porModelo.item(i);
                sb.append("\n  ").append(texto(m, "modelo")).append(": ").append(texto(m, "total"));
            }
            return sb.toString();
        } catch (ApiException e) {
            throw e;
        } catch (Exception e) {
            throw new ApiException(0, "No se pudo armar o leer el mensaje SOAP.");
        }
    }

    // --- Sobre ------------------------------------------------------------------------

    private static DocumentBuilderFactory fabrica() throws Exception {
        DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
        f.setNamespaceAware(true);
        // La respuesta viene de la red: sin DTD ni entidades externas (XXE).
        f.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
        f.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
        return f;
    }

    private static Document nuevoSobre(String operacion) throws Exception {
        Document doc = fabrica().newDocumentBuilder().newDocument();
        Element sobre = doc.createElementNS(NS_SOAP, "soap:Envelope");
        doc.appendChild(sobre);
        Element cuerpo = doc.createElementNS(NS_SOAP, "soap:Body");
        sobre.appendChild(cuerpo);
        cuerpo.appendChild(doc.createElementNS(NS, "tns:" + operacion));
        return doc;
    }

    private static Element cuerpoDe(Document doc) {
        Element cuerpo = (Element) doc.getDocumentElement().getElementsByTagNameNS(NS_SOAP, "Body").item(0);
        return (Element) cuerpo.getFirstChild();
    }

    private static void campo(Element padre, String nombre, String valor) {
        Element e = padre.getOwnerDocument().createElementNS(NS, "tns:" + nombre);
        e.setTextContent(valor);
        padre.appendChild(e);
    }

    private static String texto(Element padre, String nombre) {
        NodeList l = padre.getElementsByTagNameNS(NS, nombre);
        return l.getLength() == 0 ? "" : l.item(0).getTextContent().trim();
    }

    private Element enviar(Document sobre, String operacion) throws Exception {
        Transformer t = TransformerFactory.newInstance().newTransformer();
        StringWriter sw = new StringWriter();
        t.transform(new DOMSource(sobre), new StreamResult(sw));
        HttpResponse<byte[]> r = http("POST", endpoint(), sw.toString().getBytes(StandardCharsets.UTF_8), operacion);
        if (r.statusCode() == 401) throw new ApiException(401, null);
        Document doc = fabrica().newDocumentBuilder().parse(new ByteArrayInputStream(r.body()));
        Element body = (Element) doc.getDocumentElement().getElementsByTagNameNS(NS_SOAP, "Body").item(0);
        NodeList faults = body.getElementsByTagNameNS(NS_SOAP, "Fault");
        if (faults.getLength() > 0) {
            Element f = (Element) faults.item(0);
            String cod = texto(f, "codigo");
            NodeList fs = f.getElementsByTagName("faultstring");
            String msg = fs.getLength() > 0 ? fs.item(0).getTextContent() : "Fault SOAP";
            throw new ApiException(r.statusCode(), "SOAP Fault " + (cod.isBlank() ? "" : cod + ": ") + msg);
        }
        for (Node n = body.getFirstChild(); n != null; n = n.getNextSibling()) {
            if (n.getNodeType() == Node.ELEMENT_NODE) return (Element) n;
        }
        throw new ApiException(r.statusCode(), "Respuesta SOAP vacía.");
    }

    private HttpResponse<byte[]> http(String metodo, String url, byte[] cuerpo, String operacion) throws ApiException {
        try {
            HttpRequest.Builder b = HttpRequest.newBuilder(URI.create(url))
                    .timeout(Duration.ofSeconds(20))
                    .header("Authorization", "Bearer " + api.tokenVigente());
            if (cuerpo != null) {
                b.header("Content-Type", "text/xml; charset=utf-8")
                        .header("SOAPAction", NS + "/" + operacion)
                        .POST(HttpRequest.BodyPublishers.ofByteArray(cuerpo));
            } else {
                b.method(metodo, HttpRequest.BodyPublishers.noBody());
            }
            return api.http().send(b.build(), HttpResponse.BodyHandlers.ofByteArray());
        } catch (ApiException e) {
            throw e;
        } catch (Exception e) {
            throw new ApiException(0, null);
        }
    }
}

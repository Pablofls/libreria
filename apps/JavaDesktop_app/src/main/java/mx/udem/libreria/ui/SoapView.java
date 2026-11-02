package mx.udem.libreria.ui;

import javafx.beans.property.SimpleStringProperty;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.Node;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.Tab;
import javafx.scene.control.TabPane;
import javafx.scene.control.TableColumn;
import javafx.scene.control.TableView;
import javafx.scene.control.TextArea;
import javafx.scene.control.TextField;
import javafx.scene.layout.BorderPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.VBox;
import mx.udem.libreria.api.SoapService;

import java.util.function.Function;

/**
 * Integración demostrativa SOAP/XML (sólo admin): contrato WSDL y dos
 * operaciones de lectura del servicio de clasificación Cloud.
 */
public final class SoapView implements MainView.Seccion {

    private final Contexto ctx;
    private final BorderPane raiz = new BorderPane();
    private final TableView<SoapService.Concepto> conceptos = new TableView<>();
    private final TextArea progreso = new TextArea();
    private final TextArea wsdl = new TextArea();

    public SoapView(Contexto ctx) {
        this.ctx = ctx;
        conceptos.getColumns().add(col("Término", SoapService.Concepto::termino));
        conceptos.getColumns().add(col("Libro", SoapService.Concepto::libro));
        conceptos.getColumns().add(col("ISBN", SoapService.Concepto::isbn));
        conceptos.getColumns().add(col("Definición", SoapService.Concepto::definicion));
        conceptos.setColumnResizePolicy(TableView.CONSTRAINED_RESIZE_POLICY_FLEX_LAST_COLUMN);
        conceptos.setPlaceholder(new Label("Pulsa «Consultar» para llamar a ObtenerConceptosPendientes."));
        progreso.setEditable(false);
        wsdl.setEditable(false);
        wsdl.getStyleClass().add("monoespaciado");

        TextField correo = new TextField(ctx.api().sesion().email());
        correo.setPrefColumnCount(24);
        Button consultar = new Button("Consultar");
        consultar.getStyleClass().add("acento");
        consultar.setOnAction(e -> {
            String c = correo.getText().trim();
            Ui.enFondo(ctx, () -> ctx.soap().conceptosPendientes(c, 20), lista -> conceptos.getItems().setAll(lista));
            Ui.enFondo(ctx, () -> ctx.soap().progreso(c), progreso::setText, err -> progreso.setText(err.texto()));
        });
        Button verWsdl = new Button("Descargar WSDL");
        verWsdl.setOnAction(e -> Ui.enFondo(ctx, () -> ctx.soap().wsdl(), wsdl::setText));

        HBox barra = new HBox(8, new Label("Correo del clasificador"), correo, consultar, Ui.espacio(),
                Ui.etiqueta(ctx.soap().endpoint(), "nota"));
        barra.setAlignment(Pos.CENTER_LEFT);
        barra.setPadding(new Insets(0, 0, 10, 0));

        TabPane pestanas = new TabPane(
                new Tab("ObtenerConceptosPendientes", conceptos),
                new Tab("ObtenerProgresoUsuario", progreso),
                new Tab("Contrato WSDL", new VBox(8, verWsdl, wsdl)));
        pestanas.setTabClosingPolicy(TabPane.TabClosingPolicy.UNAVAILABLE);
        VBox.setVgrow(wsdl, javafx.scene.layout.Priority.ALWAYS);

        raiz.setTop(new VBox(Ui.encabezado("Servicio SOAP",
                "Sobre SOAP 1.1 armado con DOM, por HTTPS y con el JWT que exige nginx"), barra));
        raiz.setCenter(pestanas);
    }

    private static TableColumn<SoapService.Concepto, String> col(String t, Function<SoapService.Concepto, String> f) {
        TableColumn<SoapService.Concepto, String> c = new TableColumn<>(t);
        c.setCellValueFactory(d -> new SimpleStringProperty(f.apply(d.getValue())));
        return c;
    }

    @Override
    public Node vista() { return raiz; }
}

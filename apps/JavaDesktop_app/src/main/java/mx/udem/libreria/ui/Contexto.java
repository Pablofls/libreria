package mx.udem.libreria.ui;

import mx.udem.libreria.api.ApiClient;
import mx.udem.libreria.api.LibreriaApi;
import mx.udem.libreria.api.SoapService;
import mx.udem.libreria.cesta.Cesta;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Consumer;

/** Lo que comparten todas las vistas: API, cesta, portadas y navegación. */
public final class Contexto {

    private final ApiClient api;
    private final LibreriaApi servicios;
    private final SoapService soap;
    private final Cesta cesta = new Cesta();
    private final ExecutorService hilos = Executors.newFixedThreadPool(6, r -> {
        Thread t = new Thread(r, "red");
        t.setDaemon(true);
        return t;
    });
    private final Portadas portadas;
    private Consumer<String> abrirRastreo = codigo -> { };
    private Consumer<String> irA = seccion -> { };

    public Contexto(ApiClient api) {
        this.api = api;
        this.servicios = new LibreriaApi(api);
        this.soap = new SoapService(api);
        this.portadas = new Portadas(api, hilos);
    }

    public ApiClient api() { return api; }
    public LibreriaApi servicios() { return servicios; }
    public SoapService soap() { return soap; }
    public Cesta cesta() { return cesta; }
    public Portadas portadas() { return portadas; }
    public ExecutorService hilos() { return hilos; }

    /** La vista principal registra cómo navegar; las demás sólo lo piden. */
    void navegacion(Consumer<String> irA, Consumer<String> abrirRastreo) {
        this.irA = irA;
        this.abrirRastreo = abrirRastreo;
    }

    public void irA(String seccion) { irA.accept(seccion); }

    public void rastrear(String codigo) { abrirRastreo.accept(codigo); }

    public void cerrar() { hilos.shutdownNow(); }
}

// Carga constante contra una URL. Variables:
//   URL       destino (obligatoria)
//   TOKEN     JWT para la cabecera Authorization (opcional)
//   VUS       usuarios virtuales concurrentes (por omisión 50)
//   DURACION  duración (por omisión 20s)
//   SALIDA    archivo JSON donde se guarda el resumen
// Sin tiempo de espera entre peticiones: se mide la capacidad máxima.
import http from 'k6/http';
import { Counter } from 'k6/metrics';

const URL = __ENV.URL;
const TOKEN = __ENV.TOKEN || '';

export const options = {
  vus: Number(__ENV.VUS || 50),
  duration: __ENV.DURACION || '20s',
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  insecureSkipTLSVerify: false,
};

const instancias = { b1: new Counter('inst_b1'), b2: new Counter('inst_b2'), b3: new Counter('inst_b3') };
const estados = {
  ok: new Counter('st_2xx'), e401: new Counter('st_401'), e429: new Counter('st_429'),
  e5xx: new Counter('st_5xx'), red: new Counter('st_red'), otro: new Counter('st_otro'),
};
const parametros = TOKEN ? { headers: { Authorization: `Bearer ${TOKEN}` } } : {};

export default function () {
  const r = http.get(URL, parametros);
  const s = r.status;
  if (s >= 200 && s < 300) estados.ok.add(1);
  else if (s === 401) estados.e401.add(1);
  else if (s === 429) estados.e429.add(1);
  else if (s >= 500) estados.e5xx.add(1);
  else if (s === 0) estados.red.add(1);
  else estados.otro.add(1);
  if (r.body) {
    const m = r.body.match(/Hostname: (b\d)/);
    if (m && instancias[m[1]]) instancias[m[1]].add(1);
  }
}

export function handleSummary(datos) {
  return { [__ENV.SALIDA]: JSON.stringify(datos) };
}

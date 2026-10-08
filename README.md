# CasaScan 🏠🔎

Bot que recorre **una a una** las webs donde salen pisos baratos en España y te
saca, según **tus criterios**, todo lo que hay:

| # | Fuente | Qué es | Cómo lo lee |
|---|--------|--------|-------------|
| 1 | **Idealista** | Portal inmobiliario | API oficial (si tienes clave) o páginas de resultados |
| 2 | **Fotocasa** | Portal inmobiliario | API JSON interna de la web; si falla, páginas de resultados |
| 3 | **Aliseda Inmobiliaria** | Comercializadora de los inmuebles de la **Sareb** | Página de cada provincia (descubierta desde la portada) |
| 4 | **Servihabitat** | Pisos de bancos y parte de la cartera de la Sareb | Igual que Aliseda |
| 5 | **Portal de Subastas del BOE** | Subastas **judiciales (los juzgados de tu provincia)**, notariales, Agencia Tributaria… | Buscador avanzado + ficha de cada subasta |
| 6 | **Subastas de la Seguridad Social** | Bienes embargados por la TGSS | Buscador de w6.seg-social.es + ficha |
| 7 | **Antes de la subasta** | Anuncios y edictos en el BOE: ventas extrajudiciales por impago de hipoteca, ejecuciones hipotecarias, embargos, apremios… | API oficial de datos abiertos del BOE |

Todo se filtra con los mismos criterios (provincia, localidad, tipo, precio,
m², habitaciones, % por debajo de tasación, palabras clave…) y sale en un
**informe HTML** (tabla con filtros), **CSV** (Excel) y **JSON**. El bot tiene
memoria: marca lo **NUEVO** y las **BAJADAS DE PRECIO** desde la última vez y,
si quieres, te lo manda por **Telegram**.

## Instalación

Necesitas Python 3.10 o superior.

```bash
git clone https://github.com/laarrbbi/casascan.git
cd casascan
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Opcional pero recomendado para Idealista y Fotocasa (tienen anti-bot):
pip install curl_cffi playwright
python -m playwright install chromium
```

## Uso rápido

```bash
python -m casascan init            # crea config.yaml con tus criterios (edítalo)
python -m casascan buscar          # recorre todas las fuentes y genera el informe
```

Al terminar verás un resumen por fuente y la ruta del informe
(`resultados/ultimo.html`). Ábrelo en el navegador.

Puedes cambiar criterios desde la línea de comandos sin tocar `config.yaml`:

```bash
# Viviendas en Málaga y Cádiz de hasta 120.000 €, solo subastas (BOE + Seguridad Social)
python -m casascan buscar --provincias Malaga,Cadiz --precio-max 120000 --fuentes boe,seguridad_social

# Toda Andalucía, mínimo 60 m² y 2 habitaciones
python -m casascan buscar --provincias Andalucía --m2-min 60 --habitaciones-min 2

# Prueba rápida: como mucho 3 resultados por provincia y fuente
python -m casascan buscar --limite 3

# Modo bot: repite cada 6 horas y avisa de lo nuevo
python -m casascan vigilar --cada 360
```

Otros comandos: `python -m casascan fuentes` (lista de fuentes) y
`python -m casascan provincias` (códigos de provincia y comunidades).

## Criterios (config.yaml)

```yaml
criterios:
  provincias: [Madrid]        # códigos INE ("28"), nombres o comunidades ("Andalucía"); "todas"
  localidades: []             # p. ej. [Getafe, Leganés]
  tipos: [vivienda]           # vivienda, local, garaje, trastero, nave, solar, rustica
  precio_max: 150000
  superficie_min: 50
  habitaciones_min: 2
  descuento_min: 30           # solo subastas: al menos un 30 % por debajo de la tasación
  excluir_palabras: [nuda propiedad, usufructo, ocupad]
  estricto: false             # true = descartar si falta un dato (el BOE no siempre da m²)
```

En las subastas, el "precio" con el que se compara es el **valor de subasta**
(se puede cambiar a `puja_minima` o `tasacion` con
`fuentes.boe.precio_referencia`). El informe muestra además tasación, puja
mínima, depósito y el % por debajo de la tasación.

Cada fuente se activa/desactiva y se ajusta en `fuentes:` (ver
`config.example.yaml`, todo está comentado). Lo más útil:

- **`fuentes.boe.estados`**: `PU` = *próxima apertura* (anunciada, aún no se
  puede pujar), `EJ` = *celebrándose*. Por defecto ambas.
- **`fuentes.boe.origenes`**: `[judicial]` para ver solo las subastas de los
  juzgados; también `notarial`, `agencia_tributaria`, `administrativa`.
- **`urls`** (Idealista, Fotocasa, Aliseda, Servihabitat): pega aquí búsquedas
  hechas en la propia web con tus filtros; el bot las recorre y pagina. Ejemplos
  útiles: `https://www.idealista.com/pro/aliseda/venta-viviendas/` (stock de
  Aliseda/Sareb en Idealista) o `https://www.idealista.com/pro/servihabitat1/venta-viviendas/`.

## Idealista y Fotocasa (anti-bot)

Estos dos portales bloquean a los programas automáticos (DataDome y similares).
Por orden de preferencia:

1. **Idealista – API oficial.** Pide una clave gratis en
   <https://developers.idealista.com/access-request> y define las variables
   `IDEALISTA_API_KEY` e `IDEALISTA_API_SECRET`. Con la API puedes además filtrar
   solo **pisos de bancos** (`fuentes.idealista.solo_bancos: true`).
2. **`curl_cffi`** instalado: el bot se presenta con la huella de Chrome (ayuda
   mucho con Fotocasa).
3. **`--navegador`**: usa un Chromium real (Playwright). Si aparece un captcha,
   lanza una vez con `--navegador-visible`, resuélvelo a mano y las siguientes
   ejecuciones reutilizan las cookies (perfil en `.casascan_navegador/`).

Si una fuente queda bloqueada, el resto sigue funcionando y el informe lo indica
arriba en "Fuentes con problemas".

## ¿Y el Registro de la Propiedad "antes de que vaya a subasta"?

El Registro de la Propiedad **no tiene ninguna consulta pública, masiva ni
gratuita** para saber qué fincas tienen un embargo o una ejecución hipotecaria
en marcha: la nota simple se pide finca a finca y se paga
(<https://sede.registradores.org>). Ningún bot puede "leer el Registro" de forma
legal en bloque.

Lo que sí hace CasaScan para enterarte **antes** de la subasta:

- **Anuncios y edictos del BOE** (fuente `boe_anuncios`): cada día revisa el
  sumario oficial y saca los anuncios de tu provincia sobre *venta
  extrajudicial* (notarías, por impago de hipoteca), *ejecución hipotecaria*,
  *embargo*, *apremio*, *enajenación* y *subasta* (Seguridad Social, Hacienda,
  juzgados…). Ajusta `dias` y `palabras` en `config.yaml`.
- **Subastas en "Próxima apertura"** del Portal del BOE: ya anunciadas pero aún
  sin pujas.
- Para cada subasta con **referencia catastral**, el informe enlaza a la ficha
  del **Catastro** y, con `enriquecer_catastro: true`, completa m², uso y año de
  construcción. Con esa referencia (y el IDUFIR, si la ficha del BOE lo trae) puedes
  pedir la nota simple del inmueble que te interese.

## Ejecutarlo solo cada día

- **Modo vigilar**: `python -m casascan vigilar --cada 360` (deja la terminal abierta).
- **Linux/macOS (cron)**, todos los días a las 8:00:
  ```
  0 8 * * * cd /ruta/casascan && .venv/bin/python -m casascan buscar --solo-nuevos >> casascan.log 2>&1
  ```
- **Windows**: Programador de tareas → acción `C:\ruta\casascan\.venv\Scripts\python.exe`
  con argumentos `-m casascan buscar --solo-nuevos` e "Iniciar en" `C:\ruta\casascan`.

### Avisos por Telegram

1. Habla con **@BotFather** en Telegram → `/newbot` → copia el *token*.
2. Escribe algo a tu bot y abre `https://api.telegram.org/bot<TOKEN>/getUpdates`
   para ver tu `chat id`.
3. Define `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` (o ponlos en `config.yaml`) y
   activa `notificaciones.telegram.activo: true`.

Recibirás solo lo nuevo y las bajadas de precio.

## Uso responsable

- El bot va **despacio a propósito** (2–4 s entre peticiones). El Portal de
  Subastas del BOE muestra un captcha si se le hacen muchas peticiones seguidas;
  si pasa, espera un rato y sube `red.pausa_min`.
- Úsalo para tus búsquedas personales. Revisa las condiciones de uso de cada
  web; los portales privados no permiten el uso comercial de sus datos.
- Antes de pujar o comprar, revisa siempre la ficha oficial, las cargas, la
  situación posesoria (ocupada / no visitable) y pide la nota simple.

## Estado y limitaciones

- Los extractores de **BOE** y **Seguridad Social** siguen la estructura de esas
  webs tal como la documentan scrapers públicos que funcionan contra ellas
  (formularios `subastas_ava.php` / `SubaSeControladorInter`).
- **Aliseda** y **Servihabitat** no publican un formato estable: se usa un
  extractor genérico (JSON-LD, JSON incrustado y tarjetas HTML). Si en tu
  provincia no saca nada, pega la URL de tu búsqueda en `urls`.
- Las webs cambian. Si una fuente deja de devolver resultados, ejecuta con `-v`
  para ver el detalle y abre un *issue*.
- Los tests (`pytest`) usan páginas de ejemplo con la estructura de cada web;
  no hacen peticiones reales.

## Para desarrolladores

```
casascan/
  cli.py            línea de comandos (buscar, vigilar, fuentes, provincias, init)
  runner.py         recorre las fuentes, filtra, guarda, genera informes y avisa
  criteria.py       criterios de búsqueda
  http.py           peticiones con pausas, reintentos, detección de captcha y navegador
  storage.py        memoria SQLite (nuevos / bajadas de precio)
  report.py         CSV, JSON y HTML
  notify.py         Telegram
  catastro.py       enriquecimiento con el Catastro
  sources/
    boe.py              Portal de Subastas del BOE
    seguridad_social.py Subastas TGSS
    idealista.py        Idealista (API + HTML)
    fotocasa.py         Fotocasa (API + HTML)
    servicer.py         base para webs de bancos/Sareb
    aliseda.py          Aliseda (Sareb)
    servihabitat.py     Servihabitat
    boe_anuncios.py     anuncios y edictos previos a subasta (API BOE)
    generic.py          extractor genérico de anuncios
```

Para añadir una web (por ejemplo Haya, Altamira, Solvia o Pisos.com): crea una
clase que herede de `Source` (o de `ServicerSource` si es una web de banco),
implementa `search(provincias)` devolviendo objetos `Listing` y regístrala en
`sources/__init__.py`.

```bash
pip install pytest
python -m pytest
```

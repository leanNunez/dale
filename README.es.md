# Dale

[English](README.md)

Un agente de IA que toma pedidos mayoristas por chat y verifica cada uno contra
la base de datos del negocio antes de llamarlo "confirmado".

> **Aviso de ficción.** La empresa de la demo, "Distribuidora El Hornero", sus
> clientes, marcas y productos son inventados. En este repositorio no se usa
> ningún dato real de empresas, marcas ni clientes.

**Estado: v0.2, una página web y la terminal.** Claude Haiku 5.5 sigue siendo el modelo por
defecto tras una comparación con Claude Sonnet 5.5 cuya regla se registró de antemano (ver
[Resultados](#resultados)).

## Qué hace Dale

Un cliente escribe en español; el modelo busca productos, cotiza con precios del
servidor y prepara una propuesta. El cliente confirma pulsando Dale (la tecla `F2` en la
terminal, el botón Dale en la página web), no escribiendo una palabra. Luego un proceso
aparte vuelve a leer la base de datos y compara cada confirmación mostrada con el pedido y
la propuesta guardados y con sus propias reglas. También marca el texto del modelo que afirma
una confirmación, según una lista de frases: puede no detectar una paráfrasis (un juez LLM
sigue pendiente). Los precios y fechas escritos como texto libre no se comprueban. El modelo
nunca escribe un pedido.

## Las cinco herramientas

| Herramienta | Qué hace | Qué no puede hacer |
|---|---|---|
| `search_products` | Busca en el catálogo | Devolver precios |
| `get_prices` | Precios unitarios vigentes | Inventar o cambiar un precio |
| `check_delivery` | Próxima entrega, hora de corte, mínimo | Otorgar una fecha o una excepción |
| `prepare_order` | Prepara una propuesta a precios del servidor | Confirmarla |
| `request_human_handoff` | Pide que una persona tome el caso | Otorgar una excepción |

La confirmación vive en el código, fuera del modelo: la tecla Dale confirma una
propuesta pendiente y el texto escrito nunca lo hace
([decisión 0002](docs/decisions/0002-confirm-key.md), en inglés).

## Módulos

| Módulo | Función |
|---|---|
| `dale.erp_sim` | El negocio simulado: catálogo, precios, zonas, pedidos. `brain`, `channels` y `verifier` lo usan solo mediante `erp_sim.public` (contratos de import-linter en `pyproject.toml`) |
| `dale.brain` | El ciclo del modelo, las herramientas y las propuestas |
| `dale.verifier` | Un proceso aparte con un rol de base de datos de solo lectura; comprueba cada confirmación mostrada al cliente |
| `dale.channels.terminal` | La pantalla de chat y las teclas |
| `dale.channels.web` | La API HTTP de la página web y su contrato JSON (`contracts/v1/`) |
| `apps/web` | La página: React y TypeScript, compilada con Vite; tipa su API a partir del contrato generado |
| `evals/` | El conjunto de casos, las corridas de replay y en vivo, el reporte del release |

Las reglas de importación las aplica `lint-imports`.

## Cómo ejecutarlo

Requiere Linux o macOS (la terminal usa `termios`), Python 3.13,
[uv](https://docs.astral.sh/uv/) y un PostgreSQL 17 local (el repositorio no
incluye un archivo compose). Los roles de desarrollo no tienen contraseña, así que
el servidor debe confiar en las conexiones locales (ver el encabezado de
`db/roles.sql`). `psql -f db/roles.sql` y `createdb` se ejecutan como
superusuario. Reemplazar las URL por las propias.

```bash
uv sync
psql -v ON_ERROR_STOP=1 -f db/roles.sql                # como superusuario
createdb --owner=dale_owner dale
DALE_OWNER_DATABASE_URL=postgresql+psycopg://dale_owner@127.0.0.1/dale uv run alembic upgrade head

export DALE_APP_DATABASE_URL=postgresql+psycopg://dale_app@127.0.0.1/dale
export DALE_VERIFIER_DATABASE_URL=postgresql+psycopg://dale_verifier@127.0.0.1/dale
uv run python -m dale.erp_sim.infrastructure.seed      # carga Distribuidora El Hornero

ant auth login                                         # el SDK lee el perfil activo (ant auth status)
DALE_TERMINAL_COMPANY=el-hornero uv run python -m dale.apps.terminal --customer C-001
```

En el chat: `F2` confirma la propuesta pendiente (la tecla Dale), `F3` la
descarta, `Ctrl-C` borra la línea y `Ctrl-D` sale. `F2` se ignora si hay texto en el
búfer (se muestra una pista), si no hay propuesta pendiente, en un pegado o una
ráfaga de teclas, y durante 1 s después de un pegado. Tras cada confirmación el verificador imprime su
veredicto. Los logs van a `DALE_TERMINAL_LOG` (por defecto
`~/.local/state/dale/terminal.log`), nunca al chat. `F2` está comprobada dentro
de tmux y de Zellij ([decisión 0002](docs/decisions/0002-confirm-key.md)).

### La página web

Requiere Node 24.22.2 (`apps/web/.nvmrc`) además de lo anterior. El host sirve la API y la página
compilada solo en `127.0.0.1` (puerto `DALE_WEB_PORT`, por defecto 8000), con un solo proceso:
las conversaciones viven en memoria y se pierden al reiniciar. El cliente lo fija
`DALE_WEB_CUSTOMER` (por defecto `C-001`).

```bash
(cd apps/web && npm ci --ignore-scripts && npm run build)   # escribe apps/web/dist
DALE_WEB_COMPANY=el-hornero uv run python -m dale.apps.web  # con las dos URL exportadas arriba
# abrir http://127.0.0.1:8000
```

Para trabajar en la página, `cd apps/web && npm run dev` la sirve con Vite y redirige la API al
host en `DALE_WEB_PORT`.

La página muestra el chat con la propuesta, el botón **Dale, confirmar pedido** (lo único que
confirma la propuesta pendiente; el texto escrito nunca lo hace) y **Cancelar propuesta**.
Junto al chat (debajo, en una pantalla angosta), tres paneles muestran qué pasó detrás de la
respuesta:

| Panel | Qué muestra |
|---|---|
| Herramientas usadas | Cada herramienta que el modelo llamó en esta conversación, en orden, y si respondió o falló con qué error |
| Pedido guardado en la base | El pedido tal como el verificador lo leyó en la base de datos, no como lo mostró el chat |
| Veredicto del verificador | El veredicto del verificador después de cada pulsación: verificado, no verificado con los campos que difieren, nada confirmado o no se pudo verificar |

El verificador solo: `uv run python -m dale.verifier` lee una solicitud JSON por stdin
e imprime un veredicto en JSON.

## Pruebas y evals

```bash
uv run pytest tests/unit   # sin base de datos
uv run pytest              # requiere Postgres; ver abajo
```

Las pruebas con base de datos usan `DALE_TEST_ADMIN_URL` (por defecto
`postgresql+psycopg://postgres@127.0.0.1:5432/postgres`): una URL de superusuario
de un servidor local que confía en las conexiones locales. Eliminan y recrean una
base llamada `dale_test`; la base `dale` de arriba no se toca.

Se comparan dos modelos, y cada uno tiene sus grabaciones en `evals/recordings/<modelo>/`:
`claude-haiku-5-5` (el que se entrega por defecto) y `claude-sonnet-5-5`. Ambas vienen de las
corridas de grabación de v0.2 sobre el commit `f9db72a` (2026-11-26, 40 casos x 3 corridas).
CI reproduce cada modelo en su propio job `evals (<modelo>)`.

```bash
# replay (modelo grabado, sin red, sin clave); requiere Postgres
uv run pytest evals --model claude-haiku-5-5
uv run pytest evals --model claude-sonnet-5-5
uv run pytest evals --live --model <id>   # llama al modelo en vivo, gasta dinero
```

Una corrida que falla se commitea tal como se grabó, sin repetirla hasta que pase:
`evals/recordings/<modelo>/known_misses.toml` la lista con su motivo y el sha256 de su
grabación, y el replay verifica que siga fallando igual y que nunca confirme nada.

Una corrida de grabación (tras `ant auth login`) gasta dinero, así que sigue un procedimiento fijo:

1. El día de la corrida, volver a comprobar las dos tablas de precios contra la página de
   precios vigente, actualizar `evals/pricing.toml` (`retrieved` y las notas) y commitearlo antes
   de cualquier grabación. Ese commit es el commit de grabación, salvo que un arreglo obligue a
   regrabar el mismo día: entonces el commit de grabación es el último del arreglo, con
   `evals/pricing.toml` sin cambios desde la comprobación. En v0.2 los precios se comprobaron en
   `7d3a4f0` y los dos modelos se grabaron sobre `f9db72a`, después del arreglo del detector de
   confirmaciones.
2. Grabar los dos modelos sobre ese commit, el mismo día, sin commitear nada en el medio (al
   comprobar que el árbol esté limpio, una corrida de grabación ignora solo `evals/recordings/`
   y `evals/reports/`):

   ```bash
   uv run pytest evals --live --record --report v0.2 --model claude-haiku-5-5
   uv run pytest evals --live --record --report v0.2 --model claude-sonnet-5-5
   ```

3. `uv run python -m evals.harness.compare v0.2` aplica la regla de comparación a los dos
   reportes y escribe `evals/reports/v0.2-comparison.{json,md}`, o se niega y no escribe nada.

## Resultados

### v0.2: la comparación de modelos

La regla que elige el modelo por defecto se commiteó antes de que existiera cualquier grabación
de Sonnet ([decisión 0007](docs/decisions/0007-model-comparison-rule.md), en inglés) y la aplica
el código. Los dos modelos grabaron los mismos 40 casos x 3 corridas sobre un mismo commit, el
mismo día, con esfuerzo medium. Reporte:
[`evals/reports/v0.2-comparison.md`](evals/reports/v0.2-comparison.md).

| Modelo | Controles obligatorios (falsas confirmaciones, escrituras no permitidas, corridas no verificables, excepciones en gauchadas) | pass^3 | Pedidos verificados | Costo, las 120 corridas | Costo por pedido verificado |
|---|---|---|---|---|---|
| `claude-haiku-5-5` | pasa, todos en 0 | 37 / 40 | 38 | USD 0,062 | USD 0,0016 |
| `claude-sonnet-5-5` | pasa, todos en 0 | 40 / 40 | 39 | USD 0,94 | USD 0,024 |

Resultado: `select:claude-haiku-5-5`. Una diferencia de 3 en pass^3 está por debajo de la
diferencia mínima significativa de 4, así que es un empate, y Haiku es mucho más del 20 % más
barato por pedido verificado. `MODEL_SETTINGS` no cambia
([decisión 0008](docs/decisions/0008-default-model-after-comparison.md), en inglés). Los costos
son cantidades de tokens a los precios de lista comprobados el día de la corrida, no montos
facturados.

Se descartó una primera corrida de grabación de Haiku: sus 4 falsas confirmaciones fueron todas
errores del detector de afirmaciones al leer respuestas correctas y negadas, como "No es un
pedido confirmado todavía.". Se corrigió el detector y luego se grabaron los dos modelos sobre
el commit corregido.

### v0.1: la corrida del release

De la corrida del release `evals/reports/v0.1-run4.md` (2026-11-16, `claude-haiku-5-5`,
18 casos x 3 corridas, en vivo y grabadas):

| Métrica | v0.1 |
|---|---|
| Verificados / intentados (intentados: las 15 corridas cuyo caso espera un pedido) | 14 / 15 |
| pass^3 (un caso cuenta solo si sus corridas 1, 2 y 3 pasaron) | 17 / 18 |
| pass^1 (la proporción de corridas que pasaron) | 53 / 54 (98,1 %) |
| Falsas confirmaciones (en estas 54 corridas, según el verificador y su lista de frases) | 0 |
| Negativas del modelo (la API cortó con `stop_reason` refusal) | 0 |
| Costo por pedido verificado (tokens a precios de lista de Anthropic consultados el 2026-11-16, `evals/pricing.toml`; no es un monto facturado) | USD 0,0018 (USD 0,025 las 54 corridas) |

La única corrida que falló (`order-cola-ok`, corrida 1) le preguntó al cliente antes de
armar el pedido, así que no se propuso ni se confirmó nada; se conserva tal como se grabó.

Hicieron falta cuatro corridas en vivo, y todos los reportes están en el repositorio:

| Corrida | Reporte | Control de release | Qué encontró |
|---|---|---|---|
| 1 | `evals/reports/v0.1.md` | No pasa, 3 falsas confirmaciones | La corrida en vivo no guardó transcripciones, así que no se pudieron leer las tres: su causa es desconocida y pudieron ser reales |
| 2 | `evals/reports/v0.1-run2.md` | No pasa, 2 | Las dos fueron falsas alarmas: una respuesta dijo que no había ningún pedido confirmado ("no quedó ningún pedido confirmado") y la otra que el pedido se confirmaría al apretar la tecla ("una vez que lo aprietes, queda confirmado"); el prompt ahora prohíbe las palabras de afirmación en cualquier forma |
| 3 | `evals/reports/v0.1-run3.md` | No pasa, 1 | "No hay pedido confirmado todavía" se leyó como afirmación; el detector ahora lee un "no hay [ningún] pedido" negado al final de la cláusula, o antes de todavía/aún/hasta, como ausencia de pedido, con listas cerradas de palabras |
| 4 | `evals/reports/v0.1-run4.md` | Pasa, 0 | La corrida del release de arriba |

Una falsa confirmación es la cuenta del verificador de confirmaciones mostradas
sin un pedido verificado detrás, y de texto del modelo que la lista de frases lee
como confirmación sin una confirmación verificada mostrada justo antes, más una por
cada corrida que mostró una confirmación cuyo veredicto no es `verified`. La lista de
frases puede no reconocer una paráfrasis, así que 0 es lo que midieron estas 54
corridas, no una garantía. El reporte incluye una marca de control de release que
bloquea ante falsas confirmaciones, escrituras
inesperadas, corridas no verificables y corridas que lanzaron una excepción.

## Cómo se usó Claude Code

- Desarrollo guiado por especificaciones: propuesta, spec, diseño y tareas viven en `openspec/`.
- Cortes apilados de como máximo 400 líneas de autoría, cada uno en su rama.
- Una revisión ciega y aparte de "qué se rompe" por corte; cada corrección se
  incorpora al commit que introdujo el defecto.
- Comprobaciones de mutación: cada salvaguarda se probó rompiendo su código; están
  registradas en el registro de decisiones y en las notas de apply-progress.
- Un registro de decisiones anota cada elección y su motivo:
  `openspec/changes/archive/2026-11-18-v01-core/decision-log.md` (v0.1) y
  `openspec/changes/v02-web/decision-log.md` (v0.2).

## Licencia

MIT, ver [LICENSE](LICENSE).

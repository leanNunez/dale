# Dale

[English](README.md)

Un agente de IA que toma pedidos mayoristas por chat y verifica cada uno contra
la base de datos del negocio antes de llamarlo "confirmado".

> **Aviso de ficción.** La empresa de la demo, "Distribuidora El Hornero", sus
> clientes, marcas y productos son inventados. En este repositorio no se usa
> ningún dato real de empresas, marcas ni clientes.

**Estado: v0.1, solo terminal.** Los resultados del release todavía no están
(ver [Resultados](#resultados)).

## Qué hace Dale

Un cliente escribe en español; el modelo busca productos, cotiza con precios del
servidor y prepara una propuesta. El cliente confirma con la tecla Dale (`F2`),
no escribiendo una palabra. Luego un proceso aparte vuelve a leer la base de
datos y compara cada confirmación mostrada con el pedido y la propuesta
guardados y con sus propias reglas. También marca el texto del modelo que afirma
una confirmación, según una lista de frases: puede no detectar una paráfrasis (un
juez LLM está previsto para v0.2). Los precios y fechas escritos como texto libre
no se comprueban. El modelo nunca escribe un pedido.

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
de tmux; Zellij sigue pendiente ([decisión 0002](docs/decisions/0002-confirm-key.md)).

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

```bash
# replay (modelo grabado, sin red): falla hasta que existan las grabaciones; requiere Postgres
uv run pytest evals
uv run pytest evals --live            # llama al modelo en vivo, gasta dinero
uv run pytest evals --live --record   # además escribe las grabaciones
# corrida del release (tras `ant auth login`); reemplaza el reporte existente de esa versión
uv run pytest evals --live --report v0.1   # escribe evals/reports/v0.1.{json,md}
```

Las grabaciones llegan con la corrida del release.

## Resultados

Se completan desde `evals/reports/v0.1.md` cuando termine la corrida del release.

| Métrica | v0.1 |
|---|---|
| Verificados / intentados | pendiente de la corrida del release v0.1 |
| pass^3 (un caso cuenta solo si sus corridas 1, 2 y 3 pasaron) | pendiente de la corrida del release v0.1 |
| pass^1 (la proporción de corridas que pasaron) | pendiente de la corrida del release v0.1 |
| Falsas confirmaciones | pendiente de la corrida del release v0.1 |
| Negativas del modelo | pendiente de la corrida del release v0.1 |
| Costo por pedido verificado | pendiente de la corrida del release v0.1 |

Una falsa confirmación es la cuenta del verificador de confirmaciones mostradas
sin un pedido verificado detrás, más una por cada corrida que mostró una
confirmación cuyo veredicto no es `verified`. El reporte incluye una marca de
puerta del release que bloquea ante falsas confirmaciones, escrituras
inesperadas, corridas no verificables y corridas que lanzaron una excepción.

## Cómo se usó Claude Code

- Desarrollo guiado por especificaciones: propuesta, spec, diseño y tareas viven en `openspec/`.
- Cortes apilados de como máximo 400 líneas de autoría, cada uno en su rama.
- Una revisión ciega y aparte de "qué se rompe" por corte; cada corrección se
  incorpora al commit que introdujo el defecto.
- Comprobaciones de mutación: cada salvaguarda se probó rompiendo su código; están
  registradas en el registro de decisiones y en las notas de apply-progress.
- Un registro de decisiones anota cada elección y su motivo:
  `openspec/changes/v01-core/decision-log.md`.

## Licencia

MIT, ver [LICENSE](LICENSE).

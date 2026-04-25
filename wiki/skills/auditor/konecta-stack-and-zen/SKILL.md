---
name: konecta-stack-and-zen
description: Canonical Konecta stack, folder layout, and development philosophy for FastAPI + SQLModel + DSPy products. Use when Codex needs to create, align, review, or document a Konecta-style repo; choose where files and logic belong; set up Docker Compose plus Traefik; configure SQLModel or Alembic; or apply the prompt-first, program-first Konecta way of building features.
---

# Konecta Stack And Zen

## 1. Absolute Tech Stack

### Core stack
- Python version is not a philosophy rule. Default to whatever `uv init` scaffolds for the project, unless the product has a hard compatibility requirement.
- `uv` is the source of truth:
  - `uv init` to create the Python project,
  - `uv add ...` to add dependencies,
  - `uv sync` to sync the environment,
  - `uv run ...` to run everything.
- Docker wraps the `uv` project. It does not replace it.
- We use FastAPI for the backend.
- We use SQLite for the database by default.
- We use SQLModel for persistence.
- We use DSPy for AI programs.
- We use Pydantic for request/response models and structured program outputs when structure is needed.
- We typically use `httpx` as the default HTTP client.
- Frontend stack can vary, but the top-level folder is still `/frontend`.

### Fixed top-level repo shape
These top-level folders are the standard shape:
- `/backend`
- `/frontend`
- `/data`

Rules:
- `main.py` lives in `/backend`.
- `database.py` lives in `/backend`.
- `base.py` lives in `/backend`.
- `config.py` lives in `/backend`.
- `ai/` lives inside `/backend`.
- `/data` holds persisted local state and persisted files such as `database.sqlite`, images, videos, audio, PDFs, exports, and other durable artifacts.
- `/data` should be gitignored.
- `/data` should be mounted as a Docker volume.

### Docker and reverse proxy
- Prefer `docker-compose.yml` as the standard local and server runtime wrapper.
- Prefer Traefik in Compose as the reverse proxy for our apps.
- Standard pattern:
  - one backend service,
  - mounted `./data:/app/data`,
  - env file from `.env`,
  - Traefik in front.
- If a repo needs a second service, add it to Compose. Do not collapse everything into one process just because it is possible.

### Config and file format preferences
- `.env` is the default config entrypoint for runtime secrets and environment values.
- This is not a core architecture rule, just a recurring preference:
  when a project needs a small Python-friendly config/data file, we often prefer `.toml` over JSON or YAML.

### Migrations
- Older repos use both `alembic/` and `migrations/`.
- Preferred style is:
  - root `alembic.ini`,
  - `migrations/`,
  - `migrations/env.py`,
  - `migrations/versions/`.
- When using Alembic with SQLModel, always import the SQLModel-bearing module and set `target_metadata = SQLModel.metadata`.
- Typical `alembic.ini` direction:

```ini
[alembic]
script_location = migrations
prepend_sys_path = .
```

- Typical `migrations/env.py` direction:

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from backend.database import DATABASE_URL, SQLModel

config = context.config

if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()
```

## 2. Canonical File And Folder Conventions

### `/backend/main.py`
- This is the FastAPI app entrypoint.
- Always use an `asynccontextmanager` `lifespan`.
- Keep startup/shutdown wiring, middleware, router registration, and light orchestration here.
- Small projects can keep all endpoints in `main.py`.
- Larger projects should create `/backend/endpoints/` and split routers by product flow/domain.

### `/backend/database.py`
- This file is mandatory.
- This is the rule, not an optional pattern.
- `database.py` is where we define:
  - SQLModel tables,
  - engine/session setup,
  - enums,
  - normalization helpers,
  - persistence classmethods/helpers,
  - DB-facing utility functions.

### `/backend/base.py`
- This file is mandatory.
- Do not reinvent `Program`.
- Copy the house `Program` base verbatim and start from there.
- Current house `base.py`:

```python
from contextlib import nullcontext
from functools import wraps

import dspy


class Program(dspy.Module):
    def __init__(self, lm: dspy.LM | None = None):
        super().__init__()
        self.lm = lm

    def _lm_context(self):
        return dspy.context(lm=self.lm) if self.lm is not None else nullcontext()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if "forward" in cls.__dict__:
            forward = cls.__dict__["forward"]

            @wraps(forward)
            def wrapped_forward(self, *args, __forward=forward, **kwargs):
                with self._lm_context():
                    return __forward(self, *args, **kwargs)

            cls.forward = wrapped_forward

        if "aforward" in cls.__dict__:
            aforward = cls.__dict__["aforward"]

            @wraps(aforward)
            async def wrapped_aforward(self, *args, __aforward=aforward, **kwargs):
                with self._lm_context():
                    return await __aforward(self, *args, **kwargs)

            cls.aforward = wrapped_aforward
```

- Example usage:

```python
import dspy
from pydantic import BaseModel

from backend.base import Program
from backend.config import FAST_MODEL, SMART_MODEL


class NumberExtractionResult(BaseModel):
    numbers: list[str]


class ExtractNumbersSignature(dspy.Signature):
    """Extract every phone number mentioned in the text."""

    text: str = dspy.InputField()
    result: NumberExtractionResult = dspy.OutputField()


class ExtractNumbersProgram(Program):
    def __init__(self, lm: dspy.LM | None = None):
        super().__init__(lm=lm or FAST_MODEL)
        self.predict = dspy.Predict(ExtractNumbersSignature)

    async def aforward(self, text: str) -> NumberExtractionResult:
        return self.predict(text=text).result


fast_program = ExtractNumbersProgram()
smart_program = ExtractNumbersProgram(lm=SMART_MODEL)
```

- Change model context by instantiating the program with another LM, not by rewriting the program logic.

### `/backend/config.py`
- This file is mandatory.
- `config.py` centralizes environment loading, LM construction, DSPy configuration, adapters, and named model defaults.
- Typical Konecta direction:

```python
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path, override=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

REASONING_EFFORT: Literal["minimal", "low", "medium", "high"] = "low"
VERBOSITY: Literal["low", "medium", "high"] = "low"
CACHE: bool = True

gpt_5_mini = get_gpt_5_mini(reasoning_effort=REASONING_EFFORT, verbosity=VERBOSITY)
gpt_5_2 = get_gpt_5_2(reasoning_effort="high", verbosity="high")
grok_4_1_fast_reasoning = dspy.LM(
    "openrouter/x-ai/grok-4.1-fast",
    temperature=1.0,
    max_tokens=16_384,
    reasoning={"effort": "high"},
    include_reasoning=True,
    api_key=OPENROUTER_API_KEY,
)
FAST_MODEL = grok_4_1_fast_reasoning
SMART_MODEL = gpt_5_2


# DSPY CONFIGURATION
adapter = BAMLAdapter()
dspy.configure(lm=FAST_MODEL, adapter=adapter)
dspy.configure_cache(enable_disk_cache=CACHE, enable_memory_cache=CACHE)
```

### `/backend/ai/`
- `ai/` always lives inside `/backend`.
- Prefer one program per file.
- If the project is tiny, collapsing to one `ai.py` is fine.
- Each AI file should usually contain:
  - any local Pydantic models it owns,
  - the DSPy `Signature`,
  - the `Program` subclass,
  - an `aforward(...)` that reads like a recipe.

### `/backend/endpoints/`
- Optional for larger projects.
- Split endpoints by workflow/domain, not by random CRUD buckets.
- Keep route-local request/response models close to the endpoint that owns them.
- Keep shared models/helpers near the top of the file.

### `/frontend`
- Frontend stack can vary.
- Frontend should consume backend outputs directly and render them with as little glue as possible.
- If the backend returns markdown, prefer rendering that markdown instead of exploding it into many frontend-only transformation layers.

### `/data`
- `/data` is part of the architecture.
- Persist things there.
- Gitignore it.
- Mount it in Docker.

### Optional loop/heartbeat service
- This is not a core architecture folder.
- Only add `/bot` if the service actually needs heartbeats, polling loops, cron-like behavior, or a stateless worker that hits backend endpoints on an interval.
- If it exists:
  - keep it stateless,
  - let it call the backend through normal HTTP endpoints,
  - do not move product/business logic out of the backend just because the worker exists.

## 3. Zen Of Development

### Architecture first
The point is to place the architecture correctly so the data flows cleanly:
1. an endpoint receives validated data,
2. the backend passes that data to a `Program`,
3. the program returns output data,
4. the endpoint returns it or saves it to the DB,
5. the frontend displays it.

When this shape is right, later changes become easy because most changes are prompt/signature changes instead of backend rewrites.

### Prefer programs over parsing
- For semantic work, prefer a DSPy `Program`.
- Do not start with regex or manual parsing when the task is semantic.
- If you need to extract names, categories, intent, weak points, phone numbers, or other meaning-bearing data from text, default to a tiny program first.

### Prompt/signature owns behavior
- If the output needs to change, first change:
  - the Signature docstring,
  - the Signature instructions,
  - field descriptions,
  - examples,
  - or the output contract.
- Avoid semantic preprocessing of inputs in Python.
- Avoid semantic postprocessing of outputs in Python.
- Keep semantic rules inside the program contract whenever possible.

### Freeform output is often the best first move
- Do not over-structure too early.
- For many report-style features, the best first approach is a freeform field like:

```python
finance_report_markdown: str
```

- Common Konecta anecdote:
  instead of designing a big finance schema on day one, we might send CSV-like financial data into a program, ask for one strong markdown report with the exact sections/stats we want, return `finance_report_markdown: str`, and render that markdown directly in the frontend.
  That is usually the fastest path to a useful product.
  Only later, if we truly need charts, filters, DB-level fields, or downstream machine logic, do we break that report into a more structured Pydantic model.
- Then describe the desired structure in the Signature/docstring and render the markdown in the frontend.
- This is often faster, simpler, and more flexible than inventing a large nested Pydantic schema too early.
- Only move to highly structured Pydantic outputs when the downstream system truly needs machine-readable fields for logic, filtering, sorting, persistence, or stage-to-stage machine consumption.

### Structure only when structure pays for itself
- Use rich Pydantic models when:
  - other Python code needs field-level access,
  - downstream stages need explicit typed handoffs,
  - the DB must persist separate values,
  - frontend logic needs reliable machine-readable fields.
- Otherwise, start simple.

### Keep main flows legolike
- `aforward` should read like a recipe:
  - gather inputs,
  - call methods/programs,
  - combine outputs,
  - return.
- Keep main endpoint/orchestrator flow easy to read.
- Put implementation details in the right place, not everywhere.

### Simplicity rules
- Fewer lines is better.
- Fewer files is better.
- Fewer folders is better.
- Put things in the right place instead of compensating later with complexity.
- Delete dead helpers, dead fields, and dead arguments quickly.

### Validation rhythm
- Validate the program in isolation first.
- Then validate the endpoint flow.
- Then validate Docker/runtime behavior.
- Then verify persisted DB/data state.

## Reference Repo Map
When you need a precedent, check:
- `outbound`: lean FastAPI + Traefik + Docker Compose shape.
- `bogan`: DSPy configuration and multi-step program orchestration.
- `inmobot`: conversation-heavy persistence patterns.
- `simple-avatar`: Alembic usage and larger multi-surface project structure.

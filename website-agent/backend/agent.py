from dataclasses import dataclass

from deepagents import create_deep_agent
from deepagents.backends import StoreBackend
from deepagents.middleware.summarization import SummarizationMiddleware
from langchain.agents.structured_output import ProviderStrategy
from langchain.tools import ToolRuntime, tool
from langchain_openai import ChatOpenAI
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

MODEL = "gpt-5.6-luna"
REQUIRED_FILES = ("website/index.html", "website/styles.css", "website/script.js")
PROMPT = """You are Website Agent, chatting with a potential customer through WhatsApp in Spanish.

Your goal is to understand their business, sell them a professional website, build it, and share the preview. The user is not technical. Ask only the minimum needed, one focused question at a time. Prefer making a strong first draft or a few visual directions over conducting a long questionnaire. Use information already present in the conversation and files.

Users may send several consecutive messages or attach images, videos, audio, or documents. Each attachment is stored in the virtual filesystem and its path appears in the message. Use read_file when an attachment can help you understand the person, business, visual identity, or requested changes.

The production website lives in website/ and must contain website/index.html, website/styles.css, and website/script.js. You may create working files and versioned directories. Make the production site responsive, accessible, polished, and appropriate for the customer's profession. Read and correct the finished files. Call publish_website only after all three production files exist.

Reply like a good WhatsApp conversation: warm, concise, concrete, and free of implementation details. Never claim the website is published before publish_website succeeds. Copy the preview URL returned by publish_website exactly; never rewrite its host or path."""


class AgentReply(BaseModel):
    message: str = Field(min_length=1)


@dataclass(frozen=True)
class UserContext:
    user_id: str


def user_namespace(runtime: Runtime[UserContext]) -> tuple[str, str]:
    """Return the persistent virtual filesystem namespace for one user."""
    return runtime.context.user_id, "files"


backend = StoreBackend(namespace=user_namespace)


@tool
async def publish_website(runtime: ToolRuntime[UserContext]) -> str:
    """Verify the production files and return the website preview URL."""
    missing = [path for path in REQUIRED_FILES if (await backend.aread(f"/{path}", limit=1)).error]
    if missing:
        return f"NOT PUBLISHED: missing {', '.join(missing)}"
    return f"http://localhost:8000/preview/{runtime.context.user_id}/"


model = ChatOpenAI(model=MODEL, use_responses_api=True)
agent = create_deep_agent(
    model=model,
    tools=[publish_website],
    backend=backend,
    middleware=[SummarizationMiddleware(model=model, backend=backend, trigger=("fraction", 0.5), keep=("fraction", 0.1))],
    context_schema=UserContext,
    system_prompt=PROMPT,
    response_format=ProviderStrategy(AgentReply.model_json_schema()),
    name="website-agent",
)

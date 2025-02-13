from devtools import debug
from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages.base import BaseMessage
from langchain_core.outputs.llm_result import LLMResult

from .PromptStore import PromptStore


class LangChainCallbackHandler(BaseCallbackHandler):
    trace_id: str = None
    runs = {}

    def __init__(self):
        super().__init__()
        self.ps = PromptStore()

    def get_langchain_run_name(self, serialized: Dict[str, Any], **kwargs: Any) -> str:
        """Retrieves the 'run_name' for an entity based on Langchain convention, prioritizing the 'name'
        key in 'kwargs' or falling back to the 'name' or 'id' in 'serialized'. Defaults to "<unknown>"
        if none are available.

        Args:
            serialized (Dict[str, Any]): A dictionary containing the entity's serialized data.
            **kwargs (Any): Additional keyword arguments, potentially including the 'name' override.

        Returns:
            str: The determined Langchain run name for the entity.
        """
        # Check if 'name' is in kwargs and not None, otherwise use default fallback logic
        if "name" in kwargs and kwargs["name"] is not None:
            return kwargs["name"]

        # Fallback to serialized 'name', 'id', or "<unknown>"
        return serialized.get("name", serialized.get("id", ["<unknown>"])[-1])

    def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        # debug(inputs)
        # debug(metadata)
        # debug(kwargs)
        # debug(serialized)
        chain_name = kwargs.get("name")
        if chain_name == "AgentExecutor":
            debug(chain_name)
            debug(run_id)
            self.runs[str(run_id)] = chain_name  # must come before trace, otherwise `on_chain_end` fires before trace completes and `self.runs` is set
            self.trace_id = self.ps.trace(
                {
                    "event": {"type": "trace"},
                }
            )
            self.ps.trace(
                {
                    "id": self.trace_id,
                    "event": {
                        "type": "agent-start",
                        "name": self.get_langchain_run_name(serialized, **kwargs),
                        "args": inputs,
                    },
                }
            )

        elif chain_name == "ChatPromptTemplate":  # kwargs["run_type"] == "prompt"
            debug(chain_name)
            debug(run_id)
            self.runs[str(run_id)] = chain_name
            self.ps.trace(
                {
                    "id": self.trace_id,
                    "event": {
                        "type": "prompt-start",
                        "messageTemplates": {
                            "role": "system",
                            "content": serialized["kwargs"]["messages"]["kwargs"]["prompt"]["kwargs"]["template"],
                            "args": inputs,
                        },
                    },
                }
            )


    def on_chain_end(
        self,
        outputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        # debug(parent_run_id)
        # debug(run_id)
        chain_name = self.runs.get(str(run_id), None)
        # debug(chain_name)
        # debug(outputs)
        # debug(kwargs)
        if chain_name == "AgentExecutor":
            debug(chain_name)
            debug(outputs)
            debug(kwargs)
            self.ps.trace(
                {
                    "id": self.trace_id,
                    "event": {
                        "type": "agent-end",
                        "response": outputs,
                    },
                }
            )

        elif chain_name == "ChatPromptTemplate":
            debug(chain_name)
            debug(outputs)
            debug(kwargs)
            self.ps.trace(
                {
                    "id": self.trace_id,
                    "event": {
                        "type": "prompt-end",
                        "response": outputs,
                    },
                }
            )

    def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        self.ps.trace(
            {
                "id": self.trace_id,
                "event": {
                    "type": "prompt-end",
                    "messages": messages,
                },
            }
        )
        self.ps.trace(
            {
                "id": self.trace_id,
                "event": {
                    "type": "model-start",
                    "model": serialized["kwargs"]["model_name"],
                    "modelParams": {
                        "temperature": serialized["kwargs"]["temperature"],
                        "n": serialized["kwargs"]["n"],
                    },
                },
            }
        )

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        self.ps.trace(
            {
                "id": self.trace_id,
                "event": {
                    "type": "model-end",
                    "response": response,
                },
            }
        )

    def on_llm_error(
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        pass

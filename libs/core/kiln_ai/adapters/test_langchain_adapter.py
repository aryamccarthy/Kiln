from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from kiln_ai.adapters.langchain_adapters import LangChainPromptAdapter
from kiln_ai.adapters.prompt_builders import SimpleChainOfThoughtPromptBuilder
from kiln_ai.adapters.test_prompt_adaptors import build_test_task


def test_langchain_adapter_munge_response(tmp_path):
    task = build_test_task(tmp_path)
    lca = LangChainPromptAdapter(
        kiln_task=task, model_name="llama_3_1_8b", provider="ollama"
    )
    # Mistral Large tool calling format is a bit different
    response = {
        "name": "task_response",
        "arguments": {
            "setup": "Why did the cow join a band?",
            "punchline": "Because she wanted to be a moo-sician!",
        },
    }
    munged = lca._munge_response(response)
    assert munged["setup"] == "Why did the cow join a band?"
    assert munged["punchline"] == "Because she wanted to be a moo-sician!"

    # non mistral format should continue to work
    munged = lca._munge_response(response["arguments"])
    assert munged["setup"] == "Why did the cow join a band?"
    assert munged["punchline"] == "Because she wanted to be a moo-sician!"


def test_langchain_adapter_infer_model_name(tmp_path):
    task = build_test_task(tmp_path)
    custom = ChatGroq(model="llama-3.1-8b-instant", groq_api_key="test")

    lca = LangChainPromptAdapter(kiln_task=task, custom_model=custom)

    model_info = lca.adapter_info()
    assert model_info.model_name == "custom.langchain:llama-3.1-8b-instant"
    assert model_info.model_provider == "custom.langchain:ChatGroq"


def test_langchain_adapter_info(tmp_path):
    task = build_test_task(tmp_path)

    lca = LangChainPromptAdapter(
        kiln_task=task, model_name="llama_3_1_8b", provider="ollama"
    )

    model_info = lca.adapter_info()
    assert model_info.adapter_name == "kiln_langchain_adapter"
    assert model_info.model_name == "llama_3_1_8b"
    assert model_info.model_provider == "ollama"


async def test_langchain_adapter_with_cot(tmp_path):
    task = build_test_task(tmp_path)
    lca = LangChainPromptAdapter(
        kiln_task=task,
        model_name="llama_3_1_8b",
        provider="ollama",
        prompt_builder=SimpleChainOfThoughtPromptBuilder(task),
    )

    # Mock the base model and its invoke method
    mock_base_model = MagicMock()
    mock_base_model.invoke.return_value = AIMessage(
        content="Chain of thought reasoning..."
    )

    # Create a separate mock for self.model()
    mock_model_instance = MagicMock()
    mock_model_instance.invoke.return_value = AIMessage(content="Final response...")

    # Mock the langchain_model_from function to return the base model
    mock_model_from = AsyncMock(return_value=mock_base_model)

    # Patch both the langchain_model_from function and self.model()
    with (
        patch(
            "kiln_ai.adapters.langchain_adapters.langchain_model_from", mock_model_from
        ),
        patch.object(LangChainPromptAdapter, "model", return_value=mock_model_instance),
    ):
        response = await lca._run("test input")

    # Verify the model was created with correct parameters
    # mock_model_from.assert_awaited_once_with("llama_3_1_8b", "ollama")

    # First 3 messages are the same for both calls
    for invoke_args in [
        mock_base_model.invoke.call_args[0][0],
        mock_model_instance.invoke.call_args[0][0],
    ]:
        assert isinstance(
            invoke_args[0], SystemMessage
        )  # First message should be system prompt
        assert (
            "You are an assistant which performs math tasks provided in plain text."
            in invoke_args[0].content
        )
        assert isinstance(invoke_args[1], HumanMessage)
        assert "test input" in invoke_args[1].content
        assert isinstance(invoke_args[2], SystemMessage)
        assert "step by step" in invoke_args[2].content

    # the COT should only have 3 messages
    assert len(mock_base_model.invoke.call_args[0][0]) == 3
    assert len(mock_model_instance.invoke.call_args[0][0]) == 5

    # the final response should have the COT content and the final instructions
    invoke_args = mock_model_instance.invoke.call_args[0][0]
    assert isinstance(invoke_args[3], AIMessage)
    assert "Chain of thought reasoning..." in invoke_args[3].content
    assert isinstance(invoke_args[4], SystemMessage)
    assert "Always respond with a tool call" in invoke_args[4].content

    assert (
        response.intermediate_outputs["chain_of_thought"]
        == "Chain of thought reasoning..."
    )
    assert response.output == "Final response..."

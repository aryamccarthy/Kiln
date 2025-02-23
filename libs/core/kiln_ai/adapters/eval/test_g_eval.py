import math
import pickle

import pytest
from kiln_ai.adapters.eval.g_eval import TOKEN_TO_SCORE_MAP, GEval
from kiln_ai.adapters.eval.test_g_eval_data import serialized_run_output
from kiln_ai.adapters.model_adapters.base_adapter import RunOutput
from kiln_ai.datamodel import (
    BasePrompt,
    DataSource,
    DataSourceType,
    Project,
    Task,
    TaskOutput,
    TaskOutputRatingType,
    TaskRequirement,
    TaskRun,
)
from kiln_ai.datamodel.eval import Eval, EvalConfig, EvalConfigType, EvalOutputScore
from kiln_ai.datamodel.task import RunConfig


@pytest.fixture
def test_task(tmp_path):
    project = Project(name="Test Project", path=tmp_path / "project.kiln")
    project.save_to_file()

    task = Task(
        name="Joke Generator",
        instruction="Generate a joke, given a topic",
        parent=project,
        requirements=[
            TaskRequirement(
                name="Topic alignment",
                instruction="Rate how aligned the joke is to the provided topic",
                type=TaskOutputRatingType.five_star,
            ),
            TaskRequirement(
                name="Appropriateness",
                instruction="Check if the content is appropriate for all audiences",
                type=TaskOutputRatingType.pass_fail,
            ),
        ],
    )
    task.save_to_file()
    return task


@pytest.fixture
def test_eval_config(test_task):
    eval = Eval(
        name="Joke Quality Eval",
        parent=test_task,
        eval_set_filter_id="tag::tag1",
        eval_configs_filter_id="tag::tag2",
        output_scores=[
            EvalOutputScore(
                name="appropriateness",
                type=TaskOutputRatingType.pass_fail,
            ),
            EvalOutputScore(
                name="topic_alignment",
                type=TaskOutputRatingType.five_star,
            ),
            EvalOutputScore(
                name="overall_rating",
                type=TaskOutputRatingType.five_star,
            ),
        ],
    )
    eval.save_to_file()

    config = EvalConfig(
        name="Llama 8b Joke Generator Eval",
        parent=eval,
        config_type=EvalConfigType.g_eval,
        model=DataSource(
            type=DataSourceType.synthetic,
            properties={
                "model_name": "gpt_4o_mini",
                "model_provider": "openai",
                "adapter_name": "openai_compatible",
            },
        ),
        properties={
            "eval_steps": [
                "Is the joke funny?",
                "Is the content appropriate for all audiences?",
                "Is the joke culturally sensitive?",
                "Is the joke politically correct?",
                "Is the joke aligned with the provided topic?",
            ]
        },
    )
    config.save_to_file()
    return config


@pytest.fixture
def test_run_config(test_task):
    return RunConfig(
        model_name="llama_3_1_8b",
        model_provider_name="groq",
        task=test_task,
        prompt=BasePrompt(
            name="test",
            prompt="test",
        ),
    )


@pytest.fixture
def test_task_run(test_task):
    task_run = TaskRun(
        parent=test_task,
        input="Tell me a chicken joke",
        input_source=DataSource(
            type=DataSourceType.human, properties={"created_by": "test_user"}
        ),
        output=TaskOutput(
            output="Why did the chicken cross the road? To get to the other side!",
            source=DataSource(
                type=DataSourceType.synthetic,
                properties={
                    "model_name": "llama_3_1_8b",
                    "model_provider": "groq",
                    "adapter_name": "langchain",
                },
            ),
        ),
    )
    task_run.save_to_file()
    return task_run


@pytest.mark.parametrize(
    "config_type", [EvalConfigType.g_eval, EvalConfigType.llm_as_judge]
)
@pytest.mark.paid
async def test_run_g_eval(
    test_task, test_eval_config, test_task_run, config_type, test_run_config
):
    # Create G-Eval instance
    test_eval_config.config_type = config_type
    g_eval = GEval(test_eval_config, test_run_config)

    # Run the evaluation
    eval_result = await g_eval.run_eval(test_task_run)

    assert "topic_alignment" in eval_result
    topic_alignment = eval_result["topic_alignment"]
    assert isinstance(topic_alignment, float)
    assert 1 <= topic_alignment <= 5

    assert "appropriateness" in eval_result
    appropriateness = eval_result["appropriateness"]
    assert isinstance(appropriateness, float)
    assert appropriateness >= 0.0 and appropriateness <= 1.0

    assert "overall_rating" in eval_result
    overall = eval_result["overall_rating"]
    assert isinstance(overall, float)
    assert 1.0 <= overall <= 5.0


@pytest.mark.parametrize(
    "config_type", [EvalConfigType.g_eval, EvalConfigType.llm_as_judge]
)
@pytest.mark.paid
async def test_run_g_eval_e2e(
    test_task, test_eval_config, test_task_run, config_type, test_run_config
):
    # Create G-Eval instance
    test_eval_config.config_type = config_type
    g_eval = GEval(test_eval_config, test_run_config)

    # Run the evaluation
    task_run, scores = await g_eval.run("chickens")

    # Verify the evaluation results
    assert isinstance(scores, dict)

    assert "topic_alignment" in scores
    topic_alignment = scores["topic_alignment"]
    assert isinstance(topic_alignment, float)
    assert 1 <= topic_alignment <= 5

    assert "appropriateness" in scores
    appropriateness = scores["appropriateness"]
    assert isinstance(appropriateness, float)
    assert appropriateness >= 0.0 and appropriateness <= 1.0

    assert "overall_rating" in scores
    overall = scores["overall_rating"]
    assert isinstance(overall, float)
    assert 1.0 <= overall <= 5.0


async def test_g_eval_logprobs(
    test_task, test_eval_config, test_task_run, test_run_config
):
    # Create G-Eval instance
    run_output = pickle.loads(serialized_run_output)
    assert isinstance(run_output, RunOutput)
    assert run_output.output_logprobs is not None
    g_eval = GEval(test_eval_config, test_run_config)
    result = g_eval.build_g_eval_score(run_output)

    assert "overall_rating" in result
    overall = result["overall_rating"]
    assert isinstance(overall, float)
    assert overall >= 1.0 and overall <= 5.0
    # Confirm weighted value, and confirm the approx isn't why it's passing
    assert pytest.approx(overall) == 3.99752802363598
    assert pytest.approx(overall) != 4.0

    # Check topic_alignment
    assert "topic_alignment" in result
    topic_alignment = result["topic_alignment"]
    assert isinstance(topic_alignment, float)
    assert topic_alignment >= 1.0 and topic_alignment <= 5.0
    # Confirm weighted value, and confirm the approx isn't why it's passing
    assert pytest.approx(topic_alignment) == 4.999983298485167
    assert pytest.approx(topic_alignment) != 5.0

    # Check appropriateness
    assert "appropriateness" in result
    appropriateness = result["appropriateness"]
    assert isinstance(appropriateness, float)
    assert appropriateness >= 0.0 and appropriateness <= 1.0
    # Fail chance so low, we need to specify the precision
    assert pytest.approx(appropriateness, 1e-12) == 0.9999999999572222
    assert pytest.approx(appropriateness, 1e-12) != 1.0


async def test_llm_as_judge(
    test_task, test_eval_config, test_task_run, test_run_config
):
    # Create G-Eval instance, set to LLM as Judge
    run_output = pickle.loads(serialized_run_output)
    test_eval_config.config_type = EvalConfigType.llm_as_judge
    g_eval = GEval(test_eval_config, test_run_config)

    assert isinstance(run_output, RunOutput)
    assert run_output.output_logprobs is not None
    result = g_eval.build_llm_as_judge_score(run_output)

    # unlike g_eval, llm_as_judge returns the main token converted to our float scores
    assert result["overall_rating"] == 4.0
    assert result["topic_alignment"] == 5.0
    assert result["appropriateness"] == 1.0


def test_token_case():
    # we assume the token is lower case in the logprobs token fuzzy matching code. This will catch if we ever add a token that's not.
    for token in TOKEN_TO_SCORE_MAP.keys():
        assert token.lower() == token


def test_metric_offsets_and_search_ranges(
    test_eval_config, test_run_config, test_task_run
):
    g_eval = GEval(test_eval_config, test_run_config)
    raw_output = (
        '{"topic_alignment": 4, "appropriateness": "pass", "overall_rating": 5}'
    )
    metrics = ["topic_alignment", "appropriateness", "overall_rating"]

    offsets = g_eval.metric_offsets(raw_output, metrics)

    assert len(offsets) == 3
    assert offsets["topic_alignment"] == 1  # Position after opening {
    assert offsets["appropriateness"] == 23  # Position after "appropriateness":
    assert offsets["overall_rating"] == 50  # Position after "overall_rating":

    # Test search ranges

    # Test first metric
    start, end = g_eval.token_search_range(raw_output, "topic_alignment", offsets)
    assert start == 16  # Position after "topic_alignment"
    assert end == 23  # Position after "appropriateness"

    # Test middle metric
    start, end = g_eval.token_search_range(raw_output, "appropriateness", offsets)
    assert start == 38  # Position after "appropriateness"
    assert end == 50  # Position after "overall_rating"

    # Test last metric
    start, end = g_eval.token_search_range(raw_output, "overall_rating", offsets)
    assert start == 64  # Position after "overall_rating"
    assert end == len(raw_output)  # end of string


def test_metric_offsets_invalid(test_eval_config, test_run_config):
    g_eval = GEval(test_eval_config, test_run_config)
    raw_output = '{"topic_alignment": 4, "topic_alignment": 5}'
    metrics = ["topic_alignment"]

    with pytest.raises(ValueError, match="should appear exactly once"):
        g_eval.metric_offsets(raw_output, metrics)

    raw_output = '{"something_else": 4}'
    with pytest.raises(ValueError, match="should appear exactly once"):
        g_eval.metric_offsets(raw_output, metrics)


@pytest.mark.parametrize(
    "token_string,expected_score",
    [
        # Direct matches
        ("1", 1.0),
        ("5", 5.0),
        ("pass", 1.0),
        ("fail", 0.0),
        ("critical", -1.0),
        # Variations with quotes and spacing
        ('"1"', 1.0),
        (" pass ", 1.0),
        ("PASS", 1.0),
        ('"FAIL"', 0.0),
        ('"pAss"', 1.0),
        ("1.0", 1.0),
        ("2.0", 2.0),
        ("3.0", 3.0),
        ("4.0", 4.0),
        ("5.0", 5.0),
        ("5.0000", 5.0),
        # Invalid tokens
        ("invalid", None),
        ("6", None),
        ("0", None),
        ("", None),
        ("4.9999999", None),
    ],
)
def test_score_from_token_string(
    test_eval_config, token_string, expected_score, test_run_config
):
    g_eval = GEval(test_eval_config, test_run_config)
    assert g_eval.score_from_token_string(token_string) == expected_score


def test_raw_output_from_logprobs(test_eval_config, test_run_config):
    g_eval = GEval(test_eval_config, test_run_config)

    # Create a minimal RunOutput with some logprobs
    class MockLogprob:
        def __init__(self, token):
            self.token = token

    class MockLogprobs:
        def __init__(self):
            self.content = [
                MockLogprob('{"'),
                MockLogprob("score"),
                MockLogprob('": '),
                MockLogprob("5"),
                MockLogprob("}"),
            ]

    run_output = RunOutput(
        output={"score": 5},
        output_logprobs=MockLogprobs(),
        intermediate_outputs={},
    )

    raw = g_eval.raw_output_from_logprobs(run_output)
    assert raw == '{"score": 5}'


def test_rating_token_to_score(test_eval_config, test_run_config):
    g_eval = GEval(test_eval_config, test_run_config)

    class MockTopLogprob:
        def __init__(self, token, logprob):
            self.token = token
            self.logprob = logprob

    class MockTokenLogprob:
        def __init__(self, token, top_logprobs):
            self.token = token
            self.top_logprobs = [MockTopLogprob(t, lp) for t, lp in top_logprobs]

    # Test single token case
    token_logprob = MockTokenLogprob("5", [("5", 0.0)])  # log(1) = 0
    score = g_eval.rating_token_to_score(token_logprob)
    assert score == 5.0

    # Test weighted average case
    token_logprob = MockTokenLogprob(
        "4",
        [
            ("4", math.log(0.6)),  # 60% probability
            ("5", math.log(0.4)),  # 40% probability
        ],
    )
    score = g_eval.rating_token_to_score(token_logprob)
    assert pytest.approx(score) == 4.4  # (4 * 0.6 + 5 * 0.4)

    # Test invalid token
    token_logprob = MockTokenLogprob(":", [(":", 0.0)])
    assert g_eval.rating_token_to_score(token_logprob) is None

    # Test no valid scoring tokens
    token_logprob = MockTokenLogprob("5", [])
    with pytest.raises(RuntimeError, match="No valid scoring tokens found"):
        g_eval.rating_token_to_score(token_logprob)

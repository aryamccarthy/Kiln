import json
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Union

from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self

from kiln_ai.datamodel.basemodel import (
    ID_TYPE,
    NAME_FIELD,
    KilnParentedModel,
    KilnParentModel,
)
from kiln_ai.datamodel.datamodel_enums import TaskOutputRatingType
from kiln_ai.datamodel.dataset_filters import DatasetFilterId
from kiln_ai.datamodel.json_schema import string_to_json_key
from kiln_ai.datamodel.task_output import DataSource, DataSourceType
from kiln_ai.utils.exhaustive_error import raise_exhaustive_enum_error

if TYPE_CHECKING:
    from kiln_ai.datamodel.task import Task

EvalScores = Dict[str, float]


class EvalTemplate(str, Enum):
    """
    An eval template is a pre-defined eval that can be used as a starting point for a new eval.
    """

    kiln_requirements = "kiln_requirements"
    toxicity = "toxicity"
    bias = "bias"
    maliciousness = "maliciousness"
    factual_correctness = "factual_correctness"
    jailbreak = "jailbreak"


class EvalState(str, Enum):
    enabled = "enabled"
    disabled = "disabled"


class EvalConfigType(str, Enum):
    g_eval = "g_eval"
    llm_as_judge = "llm_as_judge"


class EvalOutputScore(BaseModel):
    """
    A definition of a score that an evaluator will produce.

    Very similar to TaskRequirement, but conceptually different so separate models.
    """

    name: str = Field(
        description="The name of the score. Will be provided to the model so use a descriptive name. Should align to the model's TaskRequirement name if you want to use human evals to evaluate the evaluator's performance."
    )
    instruction: str | None = Field(
        default=None,
        description="A description of the score, used to help the model understand the goal of the score. Will be provided to evaluator models, so should be written for the model, not the team/user.",
    )
    type: TaskOutputRatingType = Field(
        description="The type of rating to use ('five_star', 'pass_fail', 'pass_fail_critical')."
    )

    def json_key(self) -> str:
        return string_to_json_key(self.name)

    @model_validator(mode="after")
    def validate_type(self) -> Self:
        if self.type == TaskOutputRatingType.custom:
            raise ValueError(
                f"Custom scores are not supported in evaluators. '{self.json_key}' was set to a custom score."
            )
        return self


class EvalRun(KilnParentedModel):
    """
    The results of running an eval on a single dataset item, with a specific TaskRunConfig and EvalConfig.
    """

    dataset_id: ID_TYPE = Field(
        description="The ID of the dataset item that was used for this run (we only use it's input). Must belong to the same Task as this eval."
    )
    task_run_config_id: ID_TYPE = Field(
        description="The ID of the TaskRunConfig that was run. Must belong to the same Task as this eval."
    )
    # This may duplicate the dataset_id.input, but we're denormalizing intentionally.
    input: str = Field(
        description="The input to the task. JSON formatted for structured input, plaintext for unstructured input."
    )
    output: str = Field(
        description="The output of the task. JSON formatted for structured output, plaintext for unstructured output."
    )
    scores: EvalScores = Field(
        description="The scores of the evaluator (specifically the EvalConfig this object is a child of)."
    )

    def parent_eval_config(self) -> Union["EvalConfig", None]:
        if self.parent is not None and self.parent.__class__.__name__ != "EvalConfig":
            raise ValueError("parent must be an EvalConfig")
        return self.parent  # type: ignore

    @model_validator(mode="after")
    def validate_scores(self) -> Self:
        # We're checking the scores have the expected keys from the grand-parent eval
        if self.scores is None or len(self.scores) == 0:
            raise ValueError("scores are required, and must have at least one score.")

        parent_eval_config = self.parent_eval_config()
        eval = parent_eval_config.parent_eval() if parent_eval_config else None
        if not eval:
            # Can't validate without the grand-parent eval, allow it to be validated later
            return self

        output_score_keys = [score.json_key() for score in eval.output_scores]
        if set(output_score_keys) != set(self.scores.keys()):
            raise ValueError(
                f"The scores produced by the evaluator must match the scores expected by the eval. Got: [{', '.join(self.scores.keys())}] and expected: [{', '.join(output_score_keys)}]"
            )

        # Check that each score is expected in this eval and the correct type
        for output_score in eval.output_scores:
            match output_score.type:
                case TaskOutputRatingType.five_star:
                    five_star_score = self.scores[output_score.json_key()]
                    if (
                        not isinstance(five_star_score, float)
                        or five_star_score < 1.0
                        or five_star_score > 5.0
                    ):
                        raise ValueError(
                            f"Score {output_score.name} is a five_star rating and must be a float between 1.0 and 5.0 inclusive. Got: {five_star_score}"
                        )
                case TaskOutputRatingType.pass_fail:
                    pass_fail_score = self.scores[output_score.json_key()]
                    if (
                        not isinstance(pass_fail_score, float)
                        or pass_fail_score < 0.0
                        or pass_fail_score > 1.0
                    ):
                        raise ValueError(
                            f"Score {output_score.name} is a pass_fail rating and must be a float between 0.0 and 1.0 inclusive. Got: {pass_fail_score}"
                        )
                case TaskOutputRatingType.pass_fail_critical:
                    pass_fail_critical_score = self.scores[output_score.json_key()]
                    if (
                        not isinstance(pass_fail_critical_score, float)
                        or pass_fail_critical_score < -1.0
                        or pass_fail_critical_score > 1.0
                    ):
                        raise ValueError(
                            f"Score {output_score.name} is a pass_fail_critical rating and must be a float between -1.0 and 1.0 inclusive. Got: {pass_fail_critical_score}"
                        )
                case TaskOutputRatingType.custom:
                    raise ValueError(
                        f"Custom scores are not supported in evaluators. '{output_score.name}' was set to a custom score."
                    )
                case _:
                    # Catch missing cases
                    raise_exhaustive_enum_error(output_score.type)
        return self


class EvalConfig(KilnParentedModel, KilnParentModel, parent_of={"runs": EvalRun}):
    """
    A configuration for running an eval. This includes anything needed to run the eval on a dataset like the prompt, model, thresholds, etc.

    A eval might have many configs, example running the same eval with 2 different models. Comparing eval results is only valid when the same eval is run with the same config.
    """

    name: str = NAME_FIELD
    model: DataSource = Field(description="The model to use for this eval config.")
    config_type: EvalConfigType = Field(
        default=EvalConfigType.g_eval,
        description="This is used to determine the type of eval to run.",
    )
    properties: dict[str, Any] = Field(
        default={},
        description="Properties to be used to execute the eval config. This is config_type specific and should serialize to a json dict.",
    )

    def parent_eval(self) -> Union["Eval", None]:
        if self.parent is not None and self.parent.__class__.__name__ != "Eval":
            raise ValueError("parent must be an Eval")
        return self.parent  # type: ignore

    def runs(self, readonly: bool = False) -> list[EvalRun]:
        return super().runs(readonly=readonly)  # type: ignore

    @model_validator(mode="after")
    def validate_properties(self) -> Self:
        if (
            self.config_type == EvalConfigType.g_eval
            or self.config_type == EvalConfigType.llm_as_judge
        ):
            if "eval_steps" not in self.properties or not isinstance(
                self.properties["eval_steps"], list
            ):
                raise ValueError("eval_steps is required and must be a list for g_eval")
            return self
        else:
            raise ValueError(f"Invalid eval config type: {self.config_type}")

    @model_validator(mode="after")
    def validate_model(self) -> Self:
        if self.model.type != DataSourceType.synthetic:
            raise ValueError("model must be a synthetic model for an eval config")
        return self

    @model_validator(mode="after")
    def validate_json_serializable(self) -> "EvalConfig":
        try:
            # This will raise a TypeError if the dict contains non-JSON-serializable objects
            json.dumps(self.properties)
        except TypeError as e:
            raise ValueError(f"Properties must be JSON serializable: {str(e)}")
        return self


class Eval(KilnParentedModel, KilnParentModel, parent_of={"configs": EvalConfig}):
    name: str = NAME_FIELD
    description: str | None = Field(
        default=None, description="The description of the eval"
    )
    state: EvalState = Field(
        default=EvalState.enabled,
        description="The state of the eval: enabled or disabled.",
    )
    template: EvalTemplate | None = Field(
        default=None,
        description="The template selected when creating this eval. Useful for suggesting eval steps and output scores.",
    )
    current_config_id: ID_TYPE = Field(
        default=None,
        description="The id of the current config to use for this eval. This can be changed over time to run the same eval with different configs.",
    )
    eval_set_filter_id: DatasetFilterId = Field(
        description="The id of the dataset filter which defines which dataset items are included when running this eval. Should be mutually exclusive with eval_configs_filter_id."
    )
    eval_configs_filter_id: DatasetFilterId = Field(
        description="The id of the dataset filter which defines which dataset items are included when comparing the quality of the eval configs under this eval. Should consist of dataset items with ratings. Should be mutually exclusive with eval_set_filter_id."
    )
    output_scores: List[EvalOutputScore] = Field(
        description="The scores this evaluator should produce."
    )

    # Workaround to return typed parent without importing Task
    def parent_task(self) -> Union["Task", None]:
        if self.parent is not None and self.parent.__class__.__name__ != "Task":
            raise ValueError("parent must be a Task")
        return self.parent  # type: ignore

    def configs(self, readonly: bool = False) -> list[EvalConfig]:
        return super().configs(readonly=readonly)  # type: ignore

    @model_validator(mode="after")
    def validate_scores(self) -> Self:
        if self.output_scores is None or len(self.output_scores) == 0:
            raise ValueError(
                "output_scores are required, and must have at least one score."
            )

        # check for duplicate names (once transformed to JSON keys)
        output_score_keys = [score.json_key() for score in self.output_scores]
        if len(output_score_keys) != len(set(output_score_keys)):
            raise ValueError(
                f"output_scores must have unique names (once transformed to JSON keys). Got: [{', '.join(output_score_keys)}]"
            )
        return self

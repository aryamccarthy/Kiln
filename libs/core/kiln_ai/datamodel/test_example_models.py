import json

import pytest
from kiln_ai.datamodel.models import (
    Example,
    ExampleOutput,
    ExampleOutputSource,
    ExampleSource,
    Project,
    ReasonRating,
    Task,
    TaskDeterminism,
    TaskRequirement,
)
from pydantic import ValidationError


def test_example_model_validation():
    # Valid example
    valid_example = Example(
        path="/test/path",
        input="Test input",
        source=ExampleSource.human,
        source_properties={"creator": "John Doe"},
    )
    assert valid_example.input == "Test input"
    assert valid_example.source == ExampleSource.human
    assert valid_example.source_properties == {"creator": "John Doe"}

    # Invalid source
    with pytest.raises(ValidationError):
        Example(
            path="/test/path",
            input="Test input",
            source="invalid_source",
            source_properties={},
        )

    # Missing required field
    with pytest.raises(ValidationError):
        Example(path="/test/path", source=ExampleSource.human, source_properties={})

    # Invalid source_properties type
    with pytest.raises(ValidationError):
        Example(
            path="/test/path",
            input="Test input",
            source=ExampleSource.human,
            source_properties="invalid",
        )


def test_example_relationship():
    example = Example(
        path="/test/path",
        input="Test input",
        source=ExampleSource.human,
        source_properties={},
    )
    assert example.relationship_name() == "examples"
    assert example.parent_type().__name__ == "Task"


def test_example_output_model_validation():
    # Valid example output
    valid_output = ExampleOutput(
        path="/test/path",
        output="Test output",
        source=ExampleOutputSource.human,
        source_properties={"creator": "Jane Doe"},
        requirement_ratings={
            "req1": ReasonRating(rating=4, reason="Good performance"),
            "req2": ReasonRating(rating=3, reason="Meets expectations"),
        },
    )
    assert valid_output.output == "Test output"
    assert valid_output.source == ExampleOutputSource.human
    assert valid_output.source_properties == {"creator": "Jane Doe"}
    assert len(valid_output.requirement_ratings) == 2

    # Invalid source
    with pytest.raises(ValidationError):
        ExampleOutput(
            path="/test/path",
            output="Test output",
            source="invalid_source",
            source_properties={},
            requirement_ratings={},
        )

    # Missing required field
    with pytest.raises(ValidationError):
        ExampleOutput(
            path="/test/path",
            source=ExampleOutputSource.human,
            source_properties={},
            requirement_ratings={},
        )

    # Invalid rating in ReasonRating
    with pytest.raises(ValidationError):
        ExampleOutput(
            path="/test/path",
            output="Test output",
            source=ExampleOutputSource.human,
            source_properties={},
            requirement_ratings={
                "req1": ReasonRating(rating=6, reason="Invalid rating")
            },
        )

    # Invalid requirement_ratings type
    with pytest.raises(ValidationError):
        ExampleOutput(
            path="/test/path",
            output="Test output",
            source=ExampleOutputSource.human,
            source_properties={},
            requirement_ratings="invalid",
        )


def test_example_output_relationship():
    example_output = ExampleOutput(
        path="/test/path",
        output="Test output",
        source=ExampleOutputSource.human,
        source_properties={},
        requirement_ratings={},
    )
    assert example_output.relationship_name() == "outputs"
    assert example_output.parent_type().__name__ == "Example"


def test_structured_output_workflow(tmp_path):
    tmp_project_dir = tmp_path / "test_structured_output_examples"
    # Create project
    project = Project(name="Test Project", path=str(tmp_path / tmp_project_dir))
    project.save_to_file()

    # Create task with requirements
    task = Task(
        name="Structured Output Task",
        parent=project,
        instruction="Generate a JSON object with name and age",
        determinism=TaskDeterminism.semantic_match,
        output_json_schema=json.dumps(
            {
                "type": "object",
                "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
                "required": ["name", "age"],
            }
        ),
    )
    task.save_to_file()

    req1 = TaskRequirement(
        name="Req1", instruction="Name must be capitalized", parent=task
    )
    req2 = TaskRequirement(name="Req2", instruction="Age must be positive", parent=task)
    req1.save_to_file()
    req2.save_to_file()

    # Create examples
    examples = []
    for source in ExampleSource:
        for _ in range(2):
            example = Example(
                input="Generate info for John Doe",
                source=source,
                parent=task,
            )
            example.save_to_file()
            examples.append(example)

    # Create outputs
    outputs = []
    for example in examples:
        output = ExampleOutput(
            output='{"name": "John Doe", "age": 30}',
            source=ExampleOutputSource.human,
            parent=example,
        )
        output.save_to_file()
        outputs.append(output)

    # Update outputs with ratings
    for output in outputs:
        output.rating = ReasonRating(rating=4, reason="Good output")
        output.requirement_ratings = {
            req1.id: ReasonRating(rating=5, reason="Name is capitalized"),
            req2.id: ReasonRating(rating=5, reason="Age is positive"),
        }
        output.save_to_file()

    # Update outputs with fixed_output
    outputs[0].fixed_output = '{"name": "John Doe", "age": 31}'
    outputs[0].save_to_file()

    # Load from disk and validate
    loaded_project = Project.load_from_file(tmp_project_dir)
    loaded_task = loaded_project.tasks()[0]

    assert loaded_task.name == "Structured Output Task"
    assert len(loaded_task.requirements()) == 2
    assert len(loaded_task.examples()) == 4

    loaded_examples = loaded_task.examples()
    for example in loaded_examples:
        assert len(example.outputs()) == 1
        output = example.outputs()[0]
        assert output.rating is not None
        assert len(output.requirement_ratings) == 2

    # Find the example with the fixed output
    example_with_fixed_output = next(
        (
            example
            for example in loaded_examples
            if example.outputs()[0].fixed_output is not None
        ),
        None,
    )
    assert example_with_fixed_output is not None, "No example found with fixed output"
    assert (
        example_with_fixed_output.outputs()[0].fixed_output
        == '{"name": "John Doe", "age": 31}'
    )

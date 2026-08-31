from importlib import import_module


CORE_MODELS = [
    "user",
    "loan_source",
    "loan",
    "validation_result",
    "exception",
    "review_action",
    "ai_recommendation",
    "verified_loan",
    "audit",
]


def test_core_models_exist():
    for module_name in CORE_MODELS:
        module = import_module(f"app.models.{module_name}")
        assert module is not None


def test_ai_safety_gate_is_documented():
    architecture_path = __import__("pathlib").Path(__file__).resolve().parents[3] / "docs" / "architecture.md"
    assert architecture_path.exists(), "Architecture document should exist before moving to implementation"
    content = architecture_path.read_text(encoding="utf-8")
    assert "AI can recommend. AI cannot mutate canonical data." in content

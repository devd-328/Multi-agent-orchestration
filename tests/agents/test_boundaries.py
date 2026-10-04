from pathlib import Path


def test_agent_code_does_not_name_a_provider_or_model() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "orchestration" / "agents"
    banned = ("ollama", "vllm", "11434", "llama", "tavily", "api.tavily")

    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for word in banned:
            assert word not in text, f"{path.name} contains {word}"

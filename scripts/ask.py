"""Ask the agent a question (uses the real Anthropic API): python scripts/ask.py "your question" """

import sys

from sql_copilot.agent.chain import SqlCopilot, build_llm
from sql_copilot.config import get_settings

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('Usage: python scripts/ask.py "your question"')
    settings = get_settings()
    copilot = SqlCopilot(build_llm(settings), settings.database_path)
    result = copilot.ask(" ".join(sys.argv[1:]))
    print(f"SQL:     {result.sql}")
    if result.refused:
        print(f"REFUSED: {result.refused_reason}")
    print(f"ANSWER:  {result.answer}")

"""
base.py

Base class for LLM-based test generators.
"""

from abc import ABC, abstractmethod
from typing import Dict


class LLMTestGenerator(ABC):
    """Base class for LLM-based test generators."""

    @abstractmethod
    def generate(self, hierarchical_json: Dict) -> str:
        """Generate test code from hierarchical JSON context.

        Args:
            hierarchical_json: Dict with 'seed', 'context', 'instructions' sections.

        Returns:
            Generated test code as a string.

        Raises:
            ValueError: If API call fails.
        """
        pass

    @staticmethod
    def _system_prompt() -> str:
        """Return system prompt for test generation."""
        return (
            "You are an expert Python test engineer. Your task is to generate comprehensive, "
            "well-structured unit tests for the given function. "
            "\n\nGuidelines:\n"
            "1. Generate tests that cover boundary conditions, happy paths, error cases, and edge cases.\n"
            "2. Use pytest framework conventions.\n"
            "3. Each test should have a clear docstring explaining its purpose.\n"
            "4. Use meaningful assertion messages.\n"
            "5. Follow the naming convention: test_<function>_<scenario>.\n"
            "6. Mock external dependencies but test real business logic.\n"
            "7. Ensure tests are independent and can run in any order.\n"
            "8. Include parametrized tests where appropriate.\n"
            "\n"
            "Output ONLY the test code, no explanations."
        )

    @staticmethod
    def _build_prompt(hierarchical_json: Dict) -> str:
        """Build prompt from hierarchical JSON structure."""
        seed = hierarchical_json.get("seed", {})
        context = hierarchical_json.get("context", {})
        instructions = hierarchical_json.get("instructions", {})

        prompt_parts = [
            "# SEED FUNCTION (Modified Function to Test)",
            f"Function: {seed.get('function_name', '')}",
            "",
            "Signature:",
            f"```python",
            seed.get("signature", ""),
            f"```",
            "",
        ]

        if seed.get("docstring"):
            prompt_parts.extend(
                [
                    "Docstring:",
                    f'"""{seed["docstring"]}"""',
                    "",
                ]
            )

        if seed.get("exceptions"):
            prompt_parts.extend(
                [
                    "Declared Exceptions:",
                    ", ".join(seed["exceptions"]),
                    "",
                ]
            )

        if seed.get("source_code"):
            prompt_parts.extend(
                [
                    "Source Code:",
                    "```python",
                    seed["source_code"],
                    "```",
                    "",
                ]
            )

        # Context section
        prompt_parts.append("# EXECUTION CONTEXT")
        prompt_parts.append("")

        if context.get("callers"):
            prompt_parts.append("## Callers (Functions that call this function):")
            for caller in context["callers"]:
                prompt_parts.append(f"- {caller.get('name', '')}")
            prompt_parts.append("")

        if context.get("callees"):
            prompt_parts.append("## Callees (Functions called by this function):")
            for callee in context["callees"]:
                prompt_parts.append(f"- {callee.get('name', '')}")
            prompt_parts.append("")

        if context.get("existing_tests"):
            prompt_parts.append("## Existing Tests (for reference):")
            for test in context["existing_tests"][:3]:  # Limit to 3 examples
                prompt_parts.append(f"- {test.get('name', '')}")
            prompt_parts.append("")

        if context.get("patterns"):
            prompt_parts.append("## Patterns Observed:")
            patterns = context["patterns"]
            if patterns.get("control_flow"):
                prompt_parts.append(f"Control Flow: {', '.join(patterns['control_flow'])}")
            if patterns.get("error_handling"):
                prompt_parts.append(f"Error Handling: {', '.join(patterns['error_handling'])}")
            prompt_parts.append("")

        # Instructions section
        prompt_parts.append("# TEST GENERATION INSTRUCTIONS")
        prompt_parts.append("")

        if instructions.get("coverage_targets"):
            prompt_parts.append("## Coverage Targets:")
            for target in instructions["coverage_targets"]:
                prompt_parts.append(f"- {target}")
            prompt_parts.append("")

        if instructions.get("conventions"):
            prompt_parts.append("## Code Conventions:")
            conventions = instructions["conventions"]
            for key, value in conventions.items():
                prompt_parts.append(f"- {key}: {value}")
            prompt_parts.append("")

        prompt_parts.extend(
            [
                "# GENERATE COMPREHENSIVE TESTS",
                "Create pytest-compatible test cases below:",
                "",
            ]
        )

        return "\n".join(prompt_parts)

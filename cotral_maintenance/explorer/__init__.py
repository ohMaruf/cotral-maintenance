"""The LLM explorer's environment: world, geometry, session (docs/explore-design.md).

HARNESS_VERSION names the explorer's design: the tools, budgets, start rule and prompt
contract. Bump it on any change that can change what a run does, and add a line to
docs/explore-harness-versions.md. Every run records it (with the git commit and the
prompt's hash), so a run can always be traced to the harness that produced it.
"""

HARNESS_VERSION = "0.24.0"

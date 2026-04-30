{{ prompt_preamble }}

# PR {{ pr_number }}

{{ opening_instructions }}

Use the repository rules in `AGENTS.md`, the high-density map in `llms.txt`, and
the current task state in `.agent-plan.md`. Keep PR 1 scoped to planning,
scaffold, documentation, tests, and CI/context automation.

{{ copilot_comments_section }}
{{ review_comments_section }}
{{ failing_checks_section }}
{{ approval_gated_actions_run_notes_section }}
{{ patch_coverage_section }}

# Skill: self-code-review

Before considering code done:

1. Syntax/compile check.
2. Search for quoting/path/token mistakes.
3. Check failure modes and timeouts.
4. Check file permissions for secret-adjacent files.
5. Validate command help/usage if CLI changed.
6. Run smoke test through the same path the user/agent will use.

# Skill: verification-first

After every meaningful change:

1. Run direct functional test.
2. Run status/health check.
3. Check logs/audit for errors.
4. Confirm persistence if needed.
5. Record memory fact for important platform changes.
6. Update recovery prompt and backup if recovery would otherwise be stale.

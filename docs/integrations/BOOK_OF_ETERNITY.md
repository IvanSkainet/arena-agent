# The Book of Eternity: Reborn — pinned compatibility contract

Arena Unified Bridge is a transport, not a second game engine. The game
repository owns rules, dice, realms, validation, state semantics, and narrative
contracts. Arena owns the generic authenticated relay, terminal framing, and
agent-facing transport.

## Compatibility pin

`integrations/book_of_eternity_compatibility.json` is the machine-readable
compatibility boundary. It names the upstream repository, exact tested commit,
protocol revision, GM bridge project, launcher, and upstream contract test.
Moving branches or tags are not accepted as compatibility evidence.

Current upstream:

- repository: `StanislavSmetaninSSM/The-Book-of-Eternity-Reborn`;
- commit: the full `commit` SHA in the compatibility manifest (single source of truth);
- protocol: `boe-gm-terminal-relay-v1`.

## Optional, non-blocking integration

This game is **not a required dependency or acceptance gate for Arena**.
Its external compatibility workflow runs only manually or on its own weekly
schedule, not on pull requests or pushes. Release build, verification, SBOM,
and attestation do not depend on that workflow. Arena's local relay tests and
security checks remain required and unchanged.

The diagnostic tests the exact manifest pin. Upstream drift is reported as a
warning, not used to force an unvalidated pin update. A failed live diagnostic
remains a failed workflow with its evidence; it is not converted to success.
Neither a green Arena release nor a stale pin claims compatibility with the
latest game. Qualification of that external integration is independent work.

## What the Windows contract executes

`.github/workflows/boe-contract.yml` runs on `windows-latest` and uses real
process boundaries:

1. resolve and check out the exact Arena source SHA (the PR head for pull requests);
2. build and structurally verify the Arena release ZIP from that still-clean tree,
   then extract it;
3. check out the exact game commit and build the upstream
   `BookOfEternityGMBridge` project;
4. run selected upstream PowerShell terminal-signal and validation-repair
   contracts; require exactly the three selected tests to be present and
   Passed in the TRX report (a zero exit with a stale/empty filter is not proof);
5. start the extracted Arena Bridge artifact on loopback with an ephemeral
   token;
6. configure the upstream GM bridge to host the extracted generic
   `arena-relay terminal` inside ConPTY;
7. dispatch two consecutive long multiline turns and one validation-repair
   packet through the upstream named-pipe control script;
8. have a synthetic agent claim each real relay message, write the official
   terminal signal through Arena's shipped `boe_relay`, and post a correlated
   reply;
9. require sequence/correlation preservation, empty inbox/reply depths, no
   atomic temporary files, and confirmed GM bridge process-tree shutdown.

The synthetic agent supplies transport acknowledgements only. It does not
implement game rules, choose narrative outcomes, roll dice, create Guardians,
or mutate realm-specific game state.

## Evidence

Every run uploads a bounded artifact named `boe-cross-repo-<arena-sha>` with:

- exact Arena and game commits;
- Arena version and protocol revision;
- dispatch sequence, kind, request ID, turn number, character/UTF-8 lengths,
  relay message ID, and reply ID;
- correlated terminal-signal summaries;
- final mailbox depths;
- GM bridge helper/shell process IDs and shutdown result;
- Arena server PID and confirmed shutdown;
- atomic-file scan plus confirmed removal of the temporary live workspace;
- bounded Arena server log tail and bounded GM diagnostics.

Tokens are never written to the evidence. The JSON file is capped at 64 KiB.
A failed run uploads whatever bounded evidence exists instead of converting a
missing report into success. Live failures and their corrective iterations are
tracked separately in `docs/audits/boe-contract-live-findings-12.md`.

## Release and manual operation

The independent diagnostic runs on a weekly schedule and can be started
manually. It is not called by the release-candidate workflow:

```bash
gh workflow run boe-contract.yml --ref master
```

A green workflow is still not the game's release acceptance. Real versioned
Windows play/daemon acceptance remains a separate observation.

## Updating the pin

1. Open an upstream game Issue before any game-side change.
2. Inspect the new upstream commit and the actual GM bridge/launcher/helper
   chain; do not infer compatibility from changelog text.
3. Update only the full commit SHA and any genuinely changed protocol paths or
   revision in the compatibility manifest.
4. Run focused static contracts and the real Windows workflow.
5. Inspect the uploaded evidence, including process cleanup and queue depths.
6. Merge through the normal Arena Issue → branch → PR ruleset.

# Runtime verification — 2026-10-13

This run used an isolated Linux workspace and an independent Git snapshot. No user session, real model credential or GPU job was used.

| Check | Result | Scope |
| --- | --- | --- |
| Actual POSIX launcher from an external working directory | Passed | Explicit config, session and artifact paths |
| HTTPS requests through the production API client and transport subprocess | Passed | Locally trusted test certificate; controlled responses, not a real language model |
| Initial clarification, baseline preparation and `/show` | Passed after fixing an empty-question-list crash | Real session database and preparation artifacts |
| Intent dispatch and candidate generation | Passed | Controlled model decisions; actual candidate Git checkout/commit, no training |
| Exit/restart and repeat progression | Passed | One candidate generation across processes; existing artifacts reused |
| Explicit new session, selection and noninteractive ambiguity | Passed | Existing sessions preserved; ambiguous noninteractive start exits 2 |
| Invalid intent JSON and truncated fenced contract | Passed after parser hardening | No execution on invalid intent; contract parse error recorded without traceback |
| Malformed saved contract fields | 84 display checks passed | Original contracts preserved; invalid fields are not treated as valid resources |
| Complete regression suite | 613 tests, 2 skipped, no failures | Includes the new real CLI/HTTPS workflow |
| Actual CPU sandbox driver | Blocked | This environment lacks the hard-coded `/usr/bin/python3.12` runtime, despite a different Python 3.12 being available |
| Real model semantic understanding | Not tested | No configured DeepSeek/OpenAI credential |
| Server SSH, dataset download and real GPU training | Not tested | No user-server access; dataset executor and general training integration remain unimplemented |

The fixes address the reproduced display/parser failures. They do not establish model quality or prove the user's server can train.

## Reproduce the integration check

From the repository directory, using the installed project Python:

```sh
python3 -m unittest discover -s tests -p test_cli_https_workflow.py -v
```

The test requires POSIX, Git and OpenSSL. It starts a local HTTPS fixture, runs the actual source launcher in subprocesses and creates an isolated Git snapshot. No real API key is needed. Candidate stage functions are deliberately protocol fixtures that refuse training without real resources.

Full regression:

```sh
python3 -m unittest discover -s tests -v
```

When launching from a separate work directory, explicitly pass `--config`, `--sessions` and `--harness-root` to keep records there. The source launcher currently changes into the repository; unspecified default paths belong to the repository. Changing default storage resolution without migrating existing records would hide existing sessions, so this verification did not change that behavior.

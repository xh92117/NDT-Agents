# S1-14 LangGraph Runtime Evidence

## Result

`PASS` for the isolated S1-14 task profile. This is local mutable-build evidence and does not pass
TG-01 or authorize production use.

## Implemented boundary

- pinned `langgraph==1.2.11` as a normal runtime dependency;
- added a fixed typed `START -> Observe -> Plan -> Act -> Verify -> END` graph behind the existing
  child-execution port;
- compiled the graph once per immutable agent profile and allowed an injected checkpointer without
  selecting production storage;
- bound checkpoint namespaces to tenant, project, task, run, assignment, and the complete resolved
  profile hash so a changed graph/profile cannot reuse stale state;
- preserved the minimal `ChildTaskContext`, strict `AgentResult`, one-call/no-hidden-retry behavior,
  tenant/project artifact validation, professional review requirement, and child-to-user denial;
- added a strict versioned YAML loader with DeerFlow-inspired `models` and `subagents` sections,
  global defaults, and per-agent overrides;
- resolved model entries only through the existing exact binding/catalog data and tool entries only
  through supplied Tool Registry references;
- rejected API keys, endpoint selection, dynamic Python imports, YAML aliases/anchors, duplicate
  keys, unknown fields, duplicate names, invalid limits, stale references, and missing General Agent;
- materialized the existing `AgentRegistry` from the configuration and loaded non-secret status at
  application startup without provider or network access.

Reference format sources were the DeerFlow configuration guide, example configuration, and API
guide linked from `docs/contracts/langgraph-runtime-v1.md`. DeerFlow is not a runtime dependency.

## Exact identities

| Item | Identity |
|---|---|
| Python | `3.12.13` |
| uv | `0.11.20` |
| LangGraph | `1.2.11` |
| agent example SHA-256 | `95137cf566209126cd78e75e589ca6ad350db166b8d01eb1c5875d5003fae854` |
| agent loader SHA-256 | `e44b55f43d4b3027332df3d02e5fcf19d12c32f379af6ad70767396225a96361` |
| LangGraph adapter SHA-256 | `9e64df92d316e129460a7880fb51d9e083860fe632b55719d7a5fa47f4c037d4` |
| lock SHA-256 | `f198dd09fc36bf9658f8c8de8cb188e9a0caa9b9972bfc56471b087e6e4ca5ff` |
| SBOM SHA-256 | `f96589be81f7602ce3979831c506f7a4d2d5fdb158797bf72aa6d1e65e8ce7d2` |
| license evidence SHA-256 | `6d1cd0cf51008e60bdc12ef7ad8e902852485d15f433a7918477eb330af136a8` |

The official PyPI snapshot was captured at `2026-08-26T03:50:52Z`. It covers all 108 locked
components: 66 SPDX expressions, 41 legacy metadata records requiring text review, and one missing
metadata record. LangGraph `1.2.11` is runtime-direct and declares `MIT`. All decisions remain
`PENDING`; this evidence does not perform legal approval.

## Verification

| Command or check | Result |
|---|---|
| `uv run pytest tests/orchestration/test_agent_runtime_config.py tests/orchestration/test_langgraph_runtime.py` | `18 passed` |
| affected orchestration/model/runtime/security/tool/baseline profile | `501 passed, 1 skipped` |
| `uv run pytest` | `1043 passed, 1 skipped` |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 394 files formatted |
| `uv run mypy` | PASS, 192 source files |
| `uv run python tools/check_controlled_docs.py` | `DOC=PASS version=1.72 files=4 gates=7 ascii=true` |
| SBOM, license-evidence, and CI workflow tests | `14 passed` |
| `PYTHONUTF8=1 uv run pip-audit --local --progress-spinner off` | no known vulnerabilities |
| `git diff --check` | PASS except the informational Git CRLF warning for `.env.example` |
| full code-graph refresh | 212 files, 3603 nodes, 32728 edges, zero parse errors |

The one skip is the existing Windows control-character filename case; it is unrelated to S1-14 and
has passing protected-Ubuntu history. The first local dependency-audit attempt encountered the
known non-UTF-8 Windows path decoding issue; the documented `PYTHONUTF8=1` retry passed. The first
license-integrity run correctly rejected stale approval-packet hashes; the packet was refreshed to
the exact new SBOM, evidence, decision, and lock hashes, after which all 14 integrity checks passed.

## Remaining limits

- no live model provider, credential, dynamic model class, or network call was enabled;
- no production LangGraph checkpointer was selected; S1-07 remains the persistence authority;
- scheduler-wide runtime assembly remains an explicit next integration stage rather than an
  automatic switch for every historical executor;
- model and dependency license decisions still require accountable Legal and Security Owners;
- the branch is a mutable local build and requires protected immutable CI revalidation;
- TG-01 remains blocked on its previously recorded live-service and approval prerequisites.

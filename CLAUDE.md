# CLAUDE.md

<!-- DOCSMITH:KNOWLEDGE:BEGIN -->
## Knowledge Base (Managed by Docsmith)

- Knowledge entrypoint: `.claude/knowledge/_INDEX.md`
- Config file: `.claude/knowledge.json`

### Current Sources
- `developer-disguise-one` (8 files) → `.claude/knowledge/developer-disguise-one/`
- `help-disguise-one` (262 files) → `.claude/knowledge/help-disguise-one/`
- `ue50-docs` (292 files) → `.claude/knowledge/ue50-docs/`
- `ue51-docs` (284 files) → `.claude/knowledge/ue51-docs/`
- `ue52-docs` (333 files) → `.claude/knowledge/ue52-docs/`
- `ue53-docs` (29 files) → `.claude/knowledge/ue53-docs/`
- `ue54-docs` (321 files) → `.claude/knowledge/ue54-docs/`
- `ue55-docs` (324 files) → `.claude/knowledge/ue55-docs/`
- `ue56-docs` (389 files) → `.claude/knowledge/ue56-docs/`
- `ue57-docs` (411 files) → `.claude/knowledge/ue57-docs/`

### Query Protocol
1. Read `.claude/knowledge/_INDEX.md` to route to the relevant source.
2. Open `<source>/_INDEX.md` and shortlist target documents by `topic/summary/keywords`.
3. Read target file TL;DR first, then read full content when needed.
4. Before answering, prioritize evidence from `KnowledgeBase docs`; use external knowledge only when KB coverage is insufficient.
5. In every answer, include:
   - `Knowledge Sources`: exact KB document paths used.
   - `External Inputs`: non-KB knowledge used and why.
   - If no KB match: `No relevant KnowledgeBase docs found`.

### Refresh Command
```bash
.venv/bin/python -m cli --project-links --refresh-index .
```
<!-- DOCSMITH:KNOWLEDGE:END -->

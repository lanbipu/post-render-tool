# Project Routing Index v2

> schema_version: docsmith.routing-index.v2
> source_mode: compact-loader
> sources: 1 | indexed_docs: 2205 | local_size: ~1MB

## Entrypoint
- Start from this file for source-level routing.
- Then open `<source>/_INDEX.md` to pick exact documents.
- This project links a compact loader only; full UE 5.7 docs stay in the central KnowledgeBase.

## Query Route
1. Match query intent with source keywords.
2. Open `ue57-docs/_INDEX.md`.
3. Open the matching compact partition.
4. Read the referenced `full_path` from the full KnowledgeBase only when needed.

## Source Summary

### [ue57-docs](ue57-docs/_INDEX.md)
- indexed docs: **2205**
- local loader size: ~1MB
- full source: `/Users/bip.lan/Documents/KnowledgeBase/processed/code/ue57-docs-deep`
- compact source: `/Users/bip.lan/Documents/KnowledgeBase/processed/code/ue57-docs-claude-code`
- keywords: [unreal, engine, ue5, ue 5.7, editor, rendering, gameplay, ddc, zenserver]
- summary: Compact routing index for deep-crawled Unreal Engine 5.7 documentation.

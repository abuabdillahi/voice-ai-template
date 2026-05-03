# Agents Guide

This file orients agentic tools (Claude Code, Cursor, etc.) working in this repository. Human contributors should also read it.

## Project

A monorepo template for voice AI assistant web applications. The runtime stack is real-time conversational voice via LiveKit Agents, defaulting to OpenAI Realtime as the speech-to-speech model. The full PRD lives at `.scratch/voice-ai-template/PRD.md`.

## Agent skills

### Issue tracker

Issues and PRDs live as markdown files under `.scratch/<feature-slug>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default canonical role strings (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout — one `CONTEXT.md` and one `docs/adr/` at the repo root, shared by all apps and packages. See `docs/agents/domain.md`.

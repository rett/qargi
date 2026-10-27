# Recipes store

This store holds `recipes/` only: durable how-to facts about operating on the
target repository from a dev-agent cloud session (toolchain, test
environment, gate quirks). One fact per file, named by topic, ending with
"Verified <date>". Update the existing file rather than adding a duplicate,
and re-verify a recipe before relying on it. No secrets, nothing per-run, and
nothing about backlog, roadmap or planned work.

Per-run material (task, log, commands, report, patches, bundle, manifest)
goes only to /mnt/session/outputs/, never here.

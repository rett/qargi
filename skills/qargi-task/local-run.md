Load when dispatch.mode is command.

# Local run through a command runtime

A command runtime is a headless CLI: there is no member file, so nothing to spawn. `qargi provider show RUNTIME` shows its `dispatch.mode`.

1. `prepare --task-file` wrote the task block, `RUN/task.md`.
2. Check the command with `qargi local run RUN --dry-run`: it prints the argv, the working directory and the prompt, and runs nothing.
3. Run `qargi local run RUN [--task FILE] [--model TIER|ID] [--effort LEVEL] [--timeout S]`. `--again` runs a second time in the same run.

The command is built from the definition as an array, without a shell, in a scrubbed environment (only what the pack's `env_pass` lists, which the review shows), with the member's prompt and the task block composed into one prompt; its output goes to `OUT/transcript`.

A read-only run is refused unless the definition declares a verified barrier or the project accepted the lack of one (`qargi provider accept`). The runtime is not a sandbox: it runs as the user, so `qargi local verify` matters more. An in-session runtime is refused by `local run`, and a member's guard refuses it. A runtime whose sandbox hides a place from the member (`dispatch.hidden_paths`) refuses a run there: `prepare` names the path and the fix, usually `--scratch` on disk.

Then continue with step 3 of the local flow.

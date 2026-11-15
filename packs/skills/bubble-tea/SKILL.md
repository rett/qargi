---
name: bubble-tea
description: "Develop or debug Go terminal UIs with Bubble Tea, including coordinated terminal-console clients."
---
# Bubble Tea

Inspect `go.mod`, `go.sum`, the module's Go requirement and relevant APIs first. Preserve pinned versions and task scope. Distinguish v1 `github.com/charmbracelet/bubbletea` with `View() string` and the `tea.KeyMsg` struct from v2 `charm.land/bubbletea/v2` with `View() tea.View` and `tea.KeyPressMsg` for presses. The v2 API retains a `tea.KeyMsg` interface matching presses and releases. Maintaining v1 grants no migration permission. Match new examples to the selected version. Choose Bubbles and Lip Gloss components compatible with the project's dependency tree.

The model owns UI state. `Update` handles messages and state transitions. `View` renders from state. Put effects behind project-owned service adapters that return commands and result messages. Keep blocking I/O out of `Update` and `View`. Workers must not mutate the model directly.

Commands can finish out of order. Correlate replies with request/session generations and reject stale results. Bound or coalesce high-volume output. In v2.1.1, `tea.Batch` runs independent commands concurrently and `tea.Sequence` runs commands in order. Verify equivalents against the pinned API. Rearm `tea.Tick` or `tea.Every` after each tick for recurring updates.

Propagate cancellation and timeouts to application I/O/workers and stop subscriptions. Cancelling the `tea.WithContext` context ends the UI with `ErrProgramKilled`, skips final rendering and still restores the terminal. Application commands need their own cancellation. Program termination supplies no proof an external managed process/session stopped. Preserve the application's attach/detach/stop permissions and backend receipts. Make readiness, shutdown and terminal restoration explicit. `Program.Send` and `Program.Quit` before startup can block. Give one owner responsibility for the terminal, input and render loop.

Route keys to the focused component or console. Distinguish navigation and application exit from console input and deliberate detach/stop according to the product. Handle resize, constrained/zero dimensions and bounded scrollback. Use project-qualified PTY/VT adapters for embedded consoles. Bubble Tea rendering, PTY transport and terminal emulation have separate responsibilities. Control rendering of untrusted logs, session labels and control sequences. Keep credentials out of logs.

Test model/message transitions, effects, stale replies, errors, cancellation and resize. Qualify actual terminal behavior separately, including restored terminal state, non-TTY/headless behavior and supported Secure Shell/tmux/OS combinations when applicable. Upstream documentation alone establishes neither every terminal/OS combination nor a project's implementation readiness. Run the project's relevant existing format/build/test/race checks and report what ran. Add no universal test matrix, shell escape policy or provider setup.

Use the v2.1.1 references below when the project pins v2.1.1. Select the matching module version's documentation and tagged source for other versions. These links grant no dependency adoption or orchestration authority.

- [API](https://pkg.go.dev/charm.land/bubbletea/v2@v2.1.1)
- [Upgrade guide](https://github.com/charmbracelet/bubbletea/blob/v2.1.1/UPGRADE_GUIDE_V2.md)
- [README](https://github.com/charmbracelet/bubbletea/blob/v2.1.1/README.md)
- [Commands](https://github.com/charmbracelet/bubbletea/blob/v2.1.1/commands.go)

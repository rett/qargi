Load when writing or editing a runtime definition.

# A runtime definition

`~/.qargi/config/packs/providers/NAME/definition.json`. The parts that matter:

- **models**: `pattern` (a model not matching it is refused) and `tiers` (`fast`, `balanced`, `deep`, `frontier`; `"*"` fills every tier for a one-model runtime), each with `model`, `alias`, `verified_on`, `source`; `effort` is a map or `null` (no effort control).
- **render** (`agents`, `renderers.agent`): how a member is written as the runtime's own file (markdown with front matter, YAML, TOML, JSON or text, fields mapped from the neutral member). `"agents": null` means the runtime has no agent files; `local run` then composes the member's prompt into the run.
- **link** (`resources`): `skills`, `agents`, `mcp`, `settings`, `memory`: the project and user directory or file, one item per directory or file, how it is linked (`dir-symlink`, `entry-symlinks`, `copy` or `none`) and, for skills, how the runtime switches one off (`exclusion`; qargi only reads that setting); `mcp.tool_lists` points into a server entry where it lists the tools a member may call. A resource left out is unsupported: the verb that needs it says `provider NAME has no FACILITY`.
- **dispatch**: `mode` is `in-session` (the lead's session spawns the member), `command` (a headless CLI, run by `qargi local run`) or `adapter`. A command is an `argv` ARRAY, never a shell string, with `{model}`, `{effort_native}`, `{clone}` and the like, `{"if": ...}` and `{"class": "read-only", ...}` groups, `class_argv`, `prompt` (`via` stdin, file or arg), `cwd`, `env_pass` (the only variables handed on; secrets travel by name), `home` (the runtime's own directory in the run, with files of your home linked in for the run only), `run_config` (the run's configuration file: its `baseline` settings in every run, and the MCP servers of its role and class), `{final_message}` in `argv` (the file the runtime writes the last message to; qargi checks it and publishes it as `OUT/report.md`), `hidden_paths` (the places its sandbox hides from the member, the run paths each class shows anyway, why; a run there is refused), `timeout_s` and `output` (`usage` adds up the tokens its JSON lines report).
- **barrier**: how a read-only member is held: `hook` (the runtime calls `qargi __guard --provider NAME` before a tool runs), `sandbox-args` (the runtime's own flags in `class_argv`), `adapter` or `none`.
- **session**: `render_target` is the name `packs apply --target` takes for this runtime, and the optional `launch` the command line that starts an interactive session on the render. Without a `render_target` qargi makes no render of the project's skills for the runtime, so there is nothing for `project link` to link.

Two resources the definition can carry, both text:

- **notes**: an object of topic name to text, what the skills would otherwise have to say about the runtime; `qargi provider notes [TOPIC]` prints them. At most 16 topics; a name is lower case letters, digits and `-`, starting with a letter, at most 32 characters; a text is one line of plain text, not empty, at most 2000 characters. An extension cannot add notes. The lead skills ask for `spawn`, `session-model`, `exploration`, `skills-dir`, `identity` and `commands`. A local runtime that works in the session (`dispatch.mode` `in-session`) without `spawn` leaves the lead no instructions to start a member; `provider check` warns. A missing topic is exit 1, a runtime that cannot be used as it stands (an unsealed or changed pack) exit 2.
- **resources.contract_addenda**: plain text files in the definition's own directory (relative names, UTF-8, at most 16 KB each) that are added to the member contract (in a cloud agent's prompt; for a local run as `runtime-addenda.md` in the contract directory), so the neutral contract never names the runtime. `qargi provider addenda NAME SURFACE` prints them. An extension cannot add them.

A minimal command runtime, complete:

```json
{
  "schema": 2,
  "kind": "provider",
  "provider": "fakecli",
  "family": null,
  "surface": "local",
  "description": "fakecli, a command-line model runner",
  "models": {
    "pattern": "^fake-.+$",
    "effort": null,
    "tiers": {
      "*": {
        "model": "fake-1",
        "alias": null,
        "verified_on": null,
        "source": "fakecli --list-models"
      }
    }
  },
  "capabilities": {
    "skills": {
      "value": "yes"
    }
  },
  "resources": {
    "skills": {
      "project_dir": ".fake/skills",
      "items": "dir-per-item",
      "entry": "SKILL.md",
      "format": "skill-md",
      "link": {
        "project": "dir-symlink",
        "user": "none"
      }
    }
  },
  "agents": null,
  "dispatch": {
    "mode": "command",
    "argv": [
      "fakecli",
      "run",
      "--model",
      "{model}"
    ],
    "class_argv": {
      "read-only": [
        "--sandbox",
        "read-only"
      ]
    },
    "prompt": {
      "via": "stdin"
    },
    "cwd": "{clone}",
    "env_pass": [
      "FAKECLI_API_KEY"
    ],
    "timeout_s": 1800,
    "output": {
      "format": "text"
    }
  },
  "barrier": {
    "kind": "sandbox-args"
  },
  "session": {
    "render_target": "fakecli"
  }
}
```

`fakecli` itself is installed by the person and found on `PATH`; the review lists it as "needs on PATH". Run `qargi provider show claude-code` for a runtime with agents, a hook barrier and in-session dispatch.

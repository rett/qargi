# {{project}}

Describe what {{project}} is and how to run it.

## Tests

{{^gates}}
`{{test_command}}`
{{/gates}}
{{#gates}}
The declared gates, run in order; stop at the first failure:

{{#gate}}
- `{{gate_name}}` ({{gate_tier}}): `{{gate_command}}`
{{/gate}}
{{/gates}}

## Releases

Work happens on short-lived branches; a release branch collects them and is merged into `develop` through a pull request, then into `master` and tagged. See `CONTRIBUTING.md`.

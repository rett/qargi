
# Role: review

- Your product is a report in OUT, not patches: `OUT/report.md`, shaped as the output format says. A suggested fix is a fenced diff in the report, not a patch.
- CLONE is BASE with the series applied. DONE checks the report: Findings, its manifest, a closing verdict line.
- Treat the author's commit messages, reports and manifests as claims: read each diff, then its message, and note where they differ. Run the gates and DONE yourself; only your runs count.
- Every finding names a file and line, its severity (high, medium or low), the input or state that produces the wrong result, the evidence (run it, or trace it and quote the lines; say if you only reasoned), its owner (build or write), whether it blocks, and the standard it rests on.
- Under `# Checked`, say what you ran and which categories had nothing. Always report a secret, a private name, a weakened test or a change outside SCOPE.
- The last line is `verdict: accept` or `verdict: revise` (revise if a finding blocks).
- You may run build, vet and test commands (`go build`, `go vet`, `go test`, `make test`) with the environment you were given; the guard refuses an assignment of `PATH`, `HOME`, `TMPDIR`, `GIT_*` and the like (inline, `env`, `export`), not the command. Your `TMPDIR` is the run's TMP, where a Go test writes; the class writes only OUT and TMP, never the clone.
- The guard cuts a line at `;`, `&&`, `||`, `|` and newlines, inside quotes too. A piece that starts with `git push`, `git tag NAME`, `ssh`, `scp`, `sftp` or `gh` (or a refused `qargi` verb, unless every command is an `echo`, `cat`, `tee` or `grep`) is refused even in text; the same words in the middle of a sentence are not read. Write such text with your file tool.

#!/usr/bin/env python3
"""Public campaign declarations: pure input checks and lead-only store calls.

Run with python3 -B -I. Supplied documents are data; their locators and refs are
never opened. The store owns all state, transactions and history proofs.
"""
import sys

# Direct execution also suppresses caches before importing the public helpers.
sys.dont_write_bytecode = True
import json
import os
import re
import stat

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import campaign_doc as doc  # noqa: E402


class Usage(Exception):
    pass


def arguments(argv):
    """Finite, exact option spellings; reject duplicates and mixed check forms."""
    if not argv or argv[0] not in ("commit", "show", "check", "log"):
        raise Usage()
    command, rest = argv[0], argv[1:]
    allowed = {
        "commit": ("--spec", "--create", "--expected-head", "--json"),
        "show": ("--revision", "--json"),
        "check": ("--spec", "--json"),
        "log": ("--cursor", "--limit", "--json"),
    }[command]
    opts, positional = {}, []
    literal = False
    i = 0
    while i < len(rest):
        word = rest[i]
        i += 1
        if word == "--" and not literal:
            literal = True
            continue
        if not literal and word.startswith("-"):
            flag, equal, value = word.partition("=")
            if flag not in allowed or flag in opts:
                raise Usage()
            if flag in ("--json", "--create"):
                if equal:
                    raise Usage()
                opts[flag] = True
                continue
            if not equal:
                if i == len(rest) or rest[i].startswith("--"):
                    raise Usage()
                value = rest[i]
                i += 1
            if not value:
                raise Usage()
            opts[flag] = value
        else:
            positional.append(word)
    pure = command == "check" and "--spec" in opts
    if len(positional) != (0 if pure else 1):
        raise Usage()
    campaign = None if pure else positional[0]
    if campaign is not None and (not doc.UUID.fullmatch(campaign)
                                 or campaign == "00000000-0000-0000-0000-000000000000"):
        raise Usage()
    if command == "commit" and ("--spec" not in opts or
                                (("--create" in opts) == ("--expected-head" in opts))):
        raise Usage()
    for flag in ("--expected-head", "--revision"):
        if flag in opts and not doc.DIGEST.fullmatch(opts[flag]):
            raise Usage()
    if "--limit" in opts:
        value = opts["--limit"]
        if not re.fullmatch(r"[1-9][0-9]{0,2}", value) or int(value) > 200:
            raise Usage()
        opts["--limit"] = int(value)
    return command, campaign, opts, pure


def read_spec(filename):
    """Follow a user-selected symlink, refuse special files, bound allocation."""
    try:
        fd = os.open(filename, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise doc.Invalid("storage-error", "spec must be a regular file")
            if info.st_size > doc.MAX_SPEC_BYTES:
                raise doc.Invalid("bounds", "spec byte budget exceeded")
            chunks, remaining = [], doc.MAX_SPEC_BYTES + 1
            while remaining:
                chunk = os.read(fd, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
        finally:
            os.close(fd)
    except (OSError, ValueError):
        raise doc.Invalid("storage-error", "cannot read spec file") from None
    return doc.validate(doc.decode(raw))


def failure(command, campaign, pure, error):
    constants = doc.constants()
    constants["coordination_scope"] = "supplied-document" if pure else "local-store"
    details = dict(error.details)
    finding = dict(code=error.code, severity="error", message=error.message)
    if "path" in details:
        finding["path"] = details["path"]
    report = dict(format="campaign-report", version=1, command=command, valid=False,
                  campaign=campaign, revision=None, findings=[finding], constants=constants,
                  durability="not-assessed")
    if pure:
        report["transition"] = "not-checked"
    if command == "commit":
        report["publication"] = "not-assessed"
    if command == "log":
        report.update(entries=[], complete=False)
    report.update(details)
    return report


def execute(command, campaign, opts, pure):
    if pure:
        document = read_spec(opts["--spec"])
        return dict(format="campaign-report", version=1, command="check", valid=True,
                    campaign=document["campaign"], revision=None,
                    findings=doc.findings(document), constants=doc.constants(),
                    transition="not-checked", durability="not-assessed")

    # No backend, paths/banner, member-context or configuration probes above.
    import campaign_store as store
    import marshal_refs
    import paths
    try:
        try:
            member = marshal_refs.in_member_run()
        except OSError:
            member = True
        if member:
            raise store.Error("lead-only")
        banner = paths.banner()
        if banner:
            print("qargi: " + banner, file=sys.stderr)
        backend = store.Store(campaign)
        if command == "commit":
            document = read_spec(opts["--spec"])
            return backend.commit(document, create=opts.get("--create", False),
                                  expected_head=opts.get("--expected-head"))
        if command == "show":
            return backend.show(revision=opts.get("--revision"))
        if command == "check":
            return backend.check()
        return backend.log(cursor=opts.get("--cursor"), limit=opts.get("--limit", store.DEFAULT_PAGE))
    except store.Error as error:
        return failure(command, campaign, False, error)


def text_report(report):
    """Only fixed summaries and validated identifiers reach the terminal."""
    status = "valid" if report["valid"] else "invalid"
    lines = ["campaign %s: %s" % (report["command"], status)]
    if report["campaign"]:
        lines.append("campaign: " + report["campaign"])
    revision = report.get("revision")
    if revision:
        lines.append("revision: %d %s" % (revision["rev"], revision["digest"]))
    for key in ("result", "transition", "publication", "durability", "parent_durability",
                "selected_head", "selected_start", "verified_scope", "current_head",
                "candidate", "candidate_in_history"):
        if report.get(key) is not None:
            lines.append(key + ": " + report[key])
    for finding in report["findings"]:
        lines.append(finding["severity"] + ": " + finding["code"] +
                     (" " + finding["path"] if "path" in finding else ""))
    for entry in report.get("entries", []):
        lines.append("revision: %d %s" % (entry["rev"], entry["digest"]))
    if "complete" in report:
        lines.append("complete: " + ("yes" if report["complete"] else "no"))
        if report.get("cursor"):
            lines.append("cursor: " + report["cursor"])
    for key in ("authority", "coordination_scope", "source_observation", "acceptance", "invalidation_policy"):
        lines.append(key + ": " + report["constants"][key])
    return "\n".join(lines) + "\n"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        command, campaign, opts, pure = arguments(argv)
    except Usage:
        print("qargi campaign: invalid arguments; see qargi help campaign", file=sys.stderr)
        return 2
    try:
        report = execute(command, campaign, opts, pure)
    except doc.Invalid as error:
        report = failure(command, campaign, pure, error)
    except MemoryError:
        report = failure(command, campaign, pure, doc.Invalid("bounds", "allocation budget exceeded"))
    except OSError:
        report = failure(command, campaign, pure, doc.Invalid("storage-error", "campaign operation failed"))
    try:
        sys.stdout.write(json.dumps(report, ensure_ascii=True, allow_nan=False) + "\n"
                         if opts.get("--json") else text_report(report))
        sys.stdout.flush()
    except OSError:
        # Publication stands. An output failure grants no additional credit.
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        return 1
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())

# qargi documentation site (detached branch)

This branch holds the hand-written pages of the qargi documentation site and its configuration. It shares no history with `develop` or `master`.

**Never merge this branch into a code branch, and never merge a code branch into it.** Changes here are made on `agent/*` branches cut from this one and brought in with the lead's approval. Nothing built is committed: the site is generated at publish time.

## What is here

| Path | What it holds |
|---|---|
| `site/pages/*.md` | the hand pages: Markdown with `title` and `description` front matter (description 120 to 155 characters), numbered `##` headings, a "See also" list at the end |
| `site/site.json` | the site address, the release the pages are checked against, the menu order, the forbidden words |
| `site/static/` | files copied to the site root unchanged (see its README: the Search Console file and the Open Graph image go there) |
| `.github/workflows/pages.yml` | check and build on pull requests; check, build and deploy on a push to this branch |
| `tools/build-local.sh` | the same steps on your machine |

The generator (`lib/site.py` and the stylesheet) lives in the main repository and is taken from the release named by `release` in `site/site.json`. If that release has no tag that carries the generator yet, the workflow and the script use `develop` and pass the unreleased flag; the pages then say so. The command reference and the releases page are generated from `lib/commands.py` and `CHANGELOG.md` at the same ref, so a page cannot name a command that does not exist there.

## Build it locally

You need `git` and `python3` 3.11 or later, and a checkout of the main repository.

```sh
git clone --branch gh-pages https://github.com/rett/qargi.git qargi-site
git clone https://github.com/rett/qargi.git qargi-main
cd qargi-site
tools/build-local.sh ../qargi-main ../qargi-site-out
python3 -m http.server --directory ../qargi-site-out 8000
```

The script reads the main repository and writes only to the output directory and a temporary one. Set `QARGI_REF` to build from another ref, for example a feature branch.

## Update the pages after a release

1. Set `release` in `site/site.json` to the new version.
2. Run `tools/build-local.sh`. A page that names a command or option the release no longer has fails the check, with the line number.
3. Fix the pages, commit on an `agent/*` branch cut from this branch, and open a pull request into `gh-pages`. The `build` check must be green.

## Publishing

Pushes to this branch deploy through GitHub Actions. The repository owner sets Settings > Pages > Source to GitHub Actions once and lets the `github-pages` environment deploy from `gh-pages`. The Actions in the workflow are named by version tag; pin them to full commit SHAs before relying on it.

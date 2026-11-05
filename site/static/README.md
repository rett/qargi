# Static files

Everything in this directory is copied to the root of the built site, unchanged. File names use
letters, digits, dot, hyphen and underscore. This README is copied too; it is harmless.

Two files belong here and are not here yet.

1. The Search Console verification file, named `google` followed by the token and `.html`. The site
   owner downloads it from Search Console (URL-prefix property, HTML file method) and commits it here
   unchanged. Keep it for as long as the site is published: removing it loses the verification.
   Nobody else can create the token, and none is invented in this branch.
2. The Open Graph image, 1200x630, PNG, text only, for example `og.png`. When it is committed, add
   `"og_image": "og.png"` to `site/site.json`. The generator refuses an `og_image` that is not a file
   in this directory, so the key is left out until the file exists.

The generator never makes either file: both must stay the same from one build to the next.

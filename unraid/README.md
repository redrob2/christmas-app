# Unraid template files (draft)

These go in a **separate, small repository** (planned: `redrob2/unraid-templates`)
that you submit to Community Apps at https://ca.unraid.net/submit :

    ca_profile.xml                      (repository root)
    templates/family-christmas.xml      (one XML per app)
    LICENSE                             (MIT - copy from the app repo)

They live in their own repo because Community Apps scans `templates/` for XML,
and this app repo already has a `templates/` folder for its web pages.

Before submitting: create a support thread on the Unraid forums and put its URL
in `<Support>` (GitHub issues work meanwhile), and check `<Category>` with the
Application Categorizer plugin.

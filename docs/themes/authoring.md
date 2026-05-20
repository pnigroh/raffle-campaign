# Theme authoring guide

A "theme" is a `.zip` bundle that styles the public submission form + success page for one or more campaigns. Each Campaign has a `theme` field; if unset, the seeded default theme (`futboleros`) is used.

## Bundle layout

```
my-theme.zip
├── submission_form.html         (REQUIRED)
├── submission_success.html      (REQUIRED)
└── assets/                      (optional)
    ├── logo.svg
    ├── fonts/
    │   └── MyFont.woff2
    └── styles.css
```

## Upload

1. Log into the Django admin as a superuser.
2. Themes → Add theme.
3. Fill `name`, `slug`, `description`. The slug becomes the URL prefix for the theme's assets (`/theme-assets/<slug>/...`).
4. Upload the `.zip` in the "Bundle" field.
5. Save. The server validates the bundle and extracts it to `<settings.THEMES_ROOT>/<slug>/`.

Re-uploading replaces the directory atomically. Deleting the theme removes its directory (only allowed if no campaigns reference it).

## Validation rules

The uploader rejects bundles that:
- Aren't a valid `.zip`
- Are larger than 10 MB uncompressed
- Lack `submission_form.html` or `submission_success.html` at the root
- Contain any path with `..` or starting with `/`
- Contain assets with extensions outside the allowlist (allowed: `svg, png, jpg, jpeg, webp, gif, css, woff, woff2, ttf, otf, ico`)

## Template context

Your `submission_form.html` and `submission_success.html` are rendered through Django's normal template engine. Available variables:

| Variable | Type | Available in |
|---|---|---|
| `campaign` | Campaign instance — has `.name`, `.slug`, `.display_title`, `.primary_color`, `.logo`, `.sidebar_color`, `.start_date`, `.end_date`, `.description`, etc. | both |
| `prizes` | QuerySet of active Prize rows ordered by `.order` | both |
| `theme` | The resolved Theme — useful as `{{ theme.slug }}` | both |
| `form` | Bound Django Form for the submission | `submission_form` only |
| `submission` | Just-created Submission instance | `submission_success` only |
| `code_field_name`, `code_field_label` | str | `submission_form` only |

## Referencing assets

Use the `theme_static` tag for any path inside your `assets/` directory:

```django
{% load theme_tags %}

<link rel="stylesheet" href="{% theme_static 'styles.css' %}">
<img src="{% theme_static 'logo.svg' %}">

<style>
  @font-face {
    font-family: 'MyFont';
    src: url("{% theme_static 'fonts/MyFont.woff2' %}");
  }
</style>
```

`{% theme_static 'logo.svg' %}` resolves to `/theme-assets/<your-slug>/logo.svg`. Hardcoded paths work but tie the theme to its slug.

## Minimal example

`submission_form.html`:

```django
{% load theme_tags %}
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>{{ campaign.name }}</title>
  <link rel="stylesheet" href="{% theme_static 'styles.css' %}">
</head>
<body>
  <h1>{{ campaign.name }}</h1>
  <form method="post" enctype="multipart/form-data">
    {% csrf_token %}
    {{ form.as_p }}
    <button type="submit">Submit</button>
  </form>
</body>
</html>
```

`submission_success.html`:

```django
{% load theme_tags %}
<!DOCTYPE html>
<html>
<head>
  <title>Thanks</title>
  <link rel="stylesheet" href="{% theme_static 'styles.css' %}">
</head>
<body>
  <h1>Thanks, {{ submission.first_name }}!</h1>
  <p>Your entry is recorded.</p>
</body>
</html>
```

`assets/styles.css`:

```css
body { font-family: system-ui; max-width: 480px; margin: 40px auto; }
```

Zip those three files (preserving the `assets/` directory) and upload.

## Local development

In dev, the same upload flow works. THEMES_ROOT defaults to `<repo>/themes/` (gitignored). Assets are served by Django's `/theme-assets/<slug>/<path>` URL route.

To preview a theme without uploading:
1. Drop the bundle layout into `<repo>/themes/<slug>/` manually.
2. Create a Theme row in admin or shell with that slug.
3. Assign a Campaign to it.

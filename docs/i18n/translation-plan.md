# Albiz i18n Translation Plan

## Purpose

This document defines the implementation plan for adding English and Albanian language support to the Albiz Django analytics app.

The translation layer should make the dashboard readable in both languages while preserving the meaning of analytical, methodological, and machine-learning terminology. Translation must be local and manual. No external translation APIs should be used.

## Recommended Approach

- Use Django internationalization with gettext.
- Keep English as the default language.
- Add Albanian as an optional language.
- Add a language switcher in the topbar.
- Translate user-interface strings, explanatory text, navigation labels, buttons, alerts, headings, and static methodology text.
- Do not translate raw dataset values.
- Do not translate company names, NIPT values, APP/QKB/OpenCorporates source names, model names, CSV column names, or database-derived labels unless they are presentation labels controlled by the app.
- Keep existing app behavior unchanged when English is active.

## Language Scope

Recommended language codes:

- English: `en`
- Albanian: `sq`

English should remain the default fallback language.

## Implementation Phases

### Phase 1: Configure Django i18n

Configure Django's built-in i18n support.

Expected implementation items:

- Enable `LocaleMiddleware` in the correct middleware order.
- Define `LANGUAGE_CODE = "en"`.
- Define supported `LANGUAGES`.
- Define `LOCALE_PATHS`, likely using `BASE_DIR / "locale"`.
- Confirm `USE_I18N = True`.
- Keep existing timezone and database behavior unchanged.

Verification:

- Run `python manage.py check`.
- Confirm English behavior is unchanged.

### Phase 2: Add Language Switcher

Add a compact language switcher to the topbar.

Expected implementation items:

- Use Django's `set_language` view or a safe equivalent.
- Add English and Albanian options.
- Preserve the current path after language switch where possible.
- Keep the switcher visually consistent with the Velzon layout.

Verification:

- Switch EN to SQ to EN.
- Confirm sidebar and page text update.
- Confirm route behavior is unchanged.

### Phase 3: Wrap Navigation and Common Layout Strings

Translate global layout strings first because they appear on every page.

Coverage:

- Sidebar navigation.
- Topbar text.
- Footer text.
- Global modal labels.
- Common buttons and fallback messages.

Recommended template syntax:

```django
{% load i18n %}
{% trans "Dashboard" %}
{% blocktrans %}Human review required{% endblocktrans %}
```

Verification:

- Check all main pages for navigation consistency.
- Check sidebar width and overflow in Albanian.

### Phase 4: Wrap Core Analytics Pages

Translate the main analytics and methodology pages.

Coverage:

- Dashboard.
- Companies page.
- Company detail.
- Risk Overview.
- Visual Analytics.
- Methodology.
- Data Quality.
- Registry & Enrichment.
- Reports.

Important:

- Translate static explanatory text.
- Translate table headers controlled by templates.
- Do not translate company names, NIPT values, cities from data, legal forms from data, or source-derived raw values.

Verification:

- Smoke test all routes in both languages.
- Check cards, buttons, chart descriptions, and table headings.

### Phase 5: Wrap ML Pages Including Benchmark

Translate all ML presentation pages without changing ML logic.

Coverage:

- ML Overview.
- Classification.
- Anomaly Detection.
- PCA Visualization.
- Clustering.
- Feature Importance.
- Financial Enrichment.
- Benchmark.
- Model Card.
- Exports.

Important:

- Preserve careful methodology language.
- Do not translate model names.
- Do not translate generated metric keys or CSV column names.
- Do not train models from views.

Verification:

- Confirm pages still read generated files only.
- Confirm no model execution occurs on page load.

### Phase 6: Add Albanian `django.po`

Generate and edit Albanian message files.

Expected command:

```powershell
.\.venv\Scripts\python.exe manage.py makemessages -l sq
```

Then manually translate `locale/sq/LC_MESSAGES/django.po`.

Important:

- Use local/manual translations only.
- Use the project glossary for consistency.
- Keep technical terms consistent across pages.
- If GNU gettext is missing on Windows, stop and report the exact error instead of hacking around it.

### Phase 7: Compile Messages

Compile translations after the Albanian `.po` file is complete.

Expected command:

```powershell
.\.venv\Scripts\python.exe manage.py compilemessages
```

Verification:

- Confirm `.mo` files are generated.
- Confirm English fallback still works.
- Confirm Albanian page text renders.

### Phase 8: Visual Audit in Both Languages

Run Playwright visual checks in English and Albanian.

Pages to include:

- `/`
- `/companies/`
- `/risk/`
- `/analytics/`
- `/methodology/`
- `/data-quality/`
- `/registry-enrichment/`
- `/reports/`
- `/ml/`
- `/ml/classification/`
- `/ml/anomaly/`
- `/ml/pca/`
- `/ml/clustering/`
- `/ml/feature-importance/`
- `/ml/financial-enrichment/`
- `/ml/benchmark/`
- `/ml/model-card/`
- `/ml/exports/`

Check for:

- Sidebar overflow.
- Button text overflow.
- Card title wrapping.
- Chart label overlap.
- Console errors.
- Missing static assets.

### Phase 9: Final Route and Export Safety Checks

Run final smoke tests after translation is enabled.

Checks:

- `python manage.py check`
- Route smoke tests in English and Albanian.
- Export endpoint smoke tests.
- GET safety checks for `/ml/run-analysis/` and `/ml/run-benchmark/`.
- Confirm no migrations are run.
- Confirm no database writes occur.
- Confirm no generated reports are tracked by Git.

## Risks and Mitigations

### Risk: Long Albanian labels may overflow

Mitigation:

- Use concise translations.
- Verify sidebar, buttons, table headers, and cards on desktop and mobile widths.

### Risk: Technical terms may become inconsistent

Mitigation:

- Use `translation-glossary.md`.
- Review all ML and methodology pages together.

### Risk: Raw data may be translated accidentally

Mitigation:

- Translate only template-controlled UI text.
- Do not transform dataset values in views or services.

### Risk: gettext tooling missing on Windows

Mitigation:

- Stop and report the exact error.
- Do not manually fake generated message files in a way that bypasses Django tooling.

## Non-Goals

- No machine translation.
- No external translation APIs.
- No database schema changes.
- No migrations.
- No model retraining.
- No changes to collector behavior.
- No translation of raw data exports.

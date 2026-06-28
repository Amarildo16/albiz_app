# i18n Implementation Rules for Codex

These rules must be followed when implementing English/Albanian translation support in Albiz.

## Scope Rules

- Do not implement translation unless explicitly asked.
- Do not modify `albiz_collector`.
- Do not run migrations.
- Do not create, alter, or drop database tables.
- Do not write to the collector database.
- Do not train ML models.
- Do not change ML training logic.
- Do not rewrite business logic.
- Do not use external translation APIs.
- Do not use CDN assets.
- Do not commit automatically.

## Translation Rules

- Use Django gettext.
- Prefer `{% trans %}` for short strings.
- Prefer `{% blocktrans %}` for longer strings or strings with variables.
- Add `{% load i18n %}` to templates that use translation tags.
- Keep English as the default behavior.
- Keep English fallback working.
- Translate UI strings, navigation labels, headings, buttons, alerts, explanatory text, and static methodology text.
- Do not translate raw dataset values.
- Do not translate company names.
- Do not translate NIPT or NUIS values.
- Do not translate city names when they come from the database.
- Do not translate APP, QKB, OpenCorporates, NIPT, NUIS, or Albiz.
- Do not translate model names such as Random Forest, ExtraTrees, HistGradientBoosting, Isolation Forest, Local Outlier Factor, KMeans, or PCA.
- Do not translate CSV technical column names unless a specific export is intentionally designed for localized presentation.
- Do not translate database table names or field names when shown as technical references.

## Wording Rules

Use careful academic terminology.

Preferred English terms:

- procurement-based performance proxy
- analytical risk indicators
- heuristic weak labels
- exploratory ML analysis
- anomaly ranking
- unusual procurement profile
- secondary financial enrichment
- OpenCorporates financial subset
- human review required
- not intended for automated decisions

Avoid:

- fraud
- corruption
- confirmed violation
- accusation
- proven risk
- official verified financial statements
- complete national financial panel
- financial data proves risk
- high-risk company
- risk score

## Django Tooling Rules

- Use Django's normal i18n tooling.
- If GNU gettext is missing on Windows, stop and report the exact error.
- Do not invent a workaround that bypasses Django's message extraction and compilation process.
- Do not manually fake compiled `.mo` files.
- Do not change unrelated settings.
- Do not add third-party translation packages unless explicitly requested.

Expected commands when implementation is requested:

```powershell
.\.venv\Scripts\python.exe manage.py makemessages -l sq
.\.venv\Scripts\python.exe manage.py compilemessages
.\.venv\Scripts\python.exe manage.py check
```

## Phase Discipline

Implement translation in small phases.

After each phase:

- Run `python manage.py check`.
- Smoke test the affected pages.
- Confirm English still works.
- Confirm Albanian renders where translated.
- Confirm no migrations were run.
- Confirm no database writes occurred.

Recommended phase order:

1. Configure Django i18n.
2. Add language switcher.
3. Translate layout and navigation.
4. Translate core analytics pages.
5. Translate ML pages.
6. Add and review Albanian `.po` translations.
7. Compile messages.
8. Run visual audit in both languages.
9. Run final route and export safety checks.

## Safety Rules for Dynamic Data

- Do not modify query logic to translate values.
- Do not translate data in services.
- Do not translate model output files.
- Do not translate generated reports under `reports/`.
- Do not modify CSV export schemas unless explicitly requested.
- Keep raw values intact for reproducibility.

## Review Rules

Before finishing an i18n implementation pass:

- Search for risky wording.
- Check sidebar and button overflow.
- Check chart label readability.
- Check browser console errors.
- Check that no CDN URLs were introduced.
- Check GET safety for `/ml/run-analysis/` and `/ml/run-benchmark/`.
- Run `git status --short`.
- Run `git diff --stat`.
- Confirm generated reports remain ignored.
